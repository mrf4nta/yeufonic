"""Standard MIDI File (SMF) parser and ABC score converter.

Pure-Python implementation with zero external dependencies. Parses SMF format 0 and 1,
extracts duration, tempo, meter, key, markers/sections, and lyrics, and converts
tracks/channels into clean, valid ABC score notation with Vocal and Ins voices.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

# Pitch spelling mappings
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SHARP_NAMES = ["C", "^C", "D", "^D", "E", "F", "^F", "G", "^G", "A", "^A", "B"]
FLAT_NAMES = ["C", "_D", "D", "_E", "E", "F", "_G", "G", "_A", "A", "_B", "B"]

FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm", "Abm"}

MAJOR_KEYS_BY_SF = {
    0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
    -1: "F", -2: "Bb", -3: "Eb", -4: "Ab", -5: "Db", -6: "Gb", -7: "Cb",
}
MINOR_KEYS_BY_SF = {
    0: "Am", 1: "Em", 2: "Bm", 3: "F#m", 4: "C#m", 5: "G#m", 6: "D#m", 7: "A#m",
    -1: "Dm", -2: "Gm", -3: "Cm", -4: "Fm", -5: "Bbm", -6: "Ebm", -7: "Abm",
}

# Krumhansl-Schmuckler key profiles for key estimation fallback
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

CHORD_TEMPLATES = [
    # (name_suffix, intervals_mod_12, required_interval_if_any)
    ("", (0, 4, 7), None),             # Major
    ("m", (0, 3, 7), None),            # Minor
    ("7", (0, 4, 7, 10), 10),          # Dominant 7: must have minor 7th
    ("maj7", (0, 4, 7, 11), 11),       # Major 7: must have major 7th
    ("m7", (0, 3, 7, 10), 10),         # Minor 7: must have minor 7th
    ("dim", (0, 3, 6), 6),             # Diminished: must have diminished 5th
    ("sus4", (0, 5, 7), 5),            # Sus4: must have 4th
]


def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
    """Read a variable-length quantity from data starting at pos."""
    val = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return val, pos


def midi_to_abc_pitch(pitch: int, key: str = "C") -> str:
    """Convert MIDI pitch number (0-127) to ABC note string."""
    is_flat = key in FLAT_KEYS
    names = FLAT_NAMES if is_flat else SHARP_NAMES

    octave = (pitch // 12) - 1
    semitone = pitch % 12
    raw = names[semitone]

    acc = ""
    letter = raw
    if raw.startswith(("^", "_")):
        acc = raw[0]
        letter = raw[1:]

    if octave < 4:
        note_body = letter + ("," * (4 - octave))
    elif octave == 4:
        note_body = letter
    elif octave == 5:
        note_body = letter.lower()
    else:
        note_body = letter.lower() + ("'" * (octave - 5))

    return acc + note_body


class MidiParser:
    """Parses binary Standard MIDI Files into events and notes."""

    def __init__(self, data: bytes):
        self.data = data
        self.division = 480
        self.format = 0
        self.ntrks = 0
        self.tempo_events: list[tuple[int, int]] = []  # (tick, us_per_beat)
        self.time_sigs: list[tuple[int, int, int]] = []  # (tick, num, den)
        self.key_sigs: list[tuple[int, int, int]] = []  # (tick, sf, mi)
        self.markers: list[tuple[int, str]] = []  # (tick, marker_text)
        self.lyrics: list[tuple[int, str]] = []  # (tick, lyric_text)
        self.track_names: dict[int, str] = {}
        self.notes: list[dict[str, Any]] = []
        self._parse()

    def _parse(self) -> None:
        if len(self.data) < 14 or self.data[:4] != b"MThd":
            raise ValueError("Invalid MIDI file: missing MThd header")

        header_len = int.from_bytes(self.data[4:8], "big")
        self.format = int.from_bytes(self.data[8:10], "big")
        self.ntrks = int.from_bytes(self.data[10:12], "big")
        raw_div = int.from_bytes(self.data[12:14], "big")

        if raw_div & 0x8000:
            # SMPTE timecode: frames per sec, ticks per frame
            fps = (-(raw_div >> 8) & 0x7F) or 25
            tpf = raw_div & 0xFF
            self.division = int(fps * tpf * 0.5) or 480
        else:
            self.division = raw_div or 480

        pos = 8 + header_len
        track_idx = 0

        while pos + 8 <= len(self.data):
            chunk_type = self.data[pos:pos + 4]
            chunk_len = int.from_bytes(self.data[pos + 4:pos + 8], "big")
            pos += 8
            chunk_data = self.data[pos:pos + chunk_len]
            pos += chunk_len

            if chunk_type == b"MTrk":
                self._parse_track(track_idx, chunk_data)
                track_idx += 1

    def _parse_track(self, track_idx: int, chunk: bytes) -> None:
        pos = 0
        curr_tick = 0
        running_status = None
        open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}  # (ch, pitch) -> list of (start_tick, vel)

        while pos < len(chunk):
            delta, pos = _read_vlq(chunk, pos)
            curr_tick += delta
            if pos >= len(chunk):
                break

            b = chunk[pos]
            if b & 0x80:
                status = b
                pos += 1
                if status < 0xF0:
                    running_status = status
                else:
                    running_status = None
            else:
                status = running_status
                if status is None:
                    pos += 1
                    continue

            msg_type = status & 0xF0
            channel = status & 0x0F

            if msg_type == 0x80:  # Note Off
                if pos + 2 > len(chunk):
                    break
                pitch = chunk[pos]
                pos += 2
                key = (channel, pitch)
                if key in open_notes and open_notes[key]:
                    start_tick, vel = open_notes[key].pop(0)
                    dur = max(1, curr_tick - start_tick)
                    self.notes.append({
                        "track": track_idx, "channel": channel, "pitch": pitch,
                        "start_tick": start_tick, "end_tick": curr_tick,
                        "duration_ticks": dur, "velocity": vel,
                    })

            elif msg_type == 0x90:  # Note On
                if pos + 2 > len(chunk):
                    break
                pitch = chunk[pos]
                vel = chunk[pos + 1]
                pos += 2
                key = (channel, pitch)
                if vel == 0:
                    # Note On with velocity 0 is Note Off
                    if key in open_notes and open_notes[key]:
                        start_tick, o_vel = open_notes[key].pop(0)
                        dur = max(1, curr_tick - start_tick)
                        self.notes.append({
                            "track": track_idx, "channel": channel, "pitch": pitch,
                            "start_tick": start_tick, "end_tick": curr_tick,
                            "duration_ticks": dur, "velocity": o_vel,
                        })
                else:
                    open_notes.setdefault(key, []).append((curr_tick, vel))

            elif msg_type in (0xA0, 0xB0, 0xE0):
                pos += 2
            elif msg_type in (0xC0, 0xD0):
                pos += 1
            elif status == 0xFF:  # Meta event
                if pos >= len(chunk):
                    break
                meta_type = chunk[pos]
                pos += 1
                meta_len, pos = _read_vlq(chunk, pos)
                meta_bytes = chunk[pos:pos + meta_len]
                pos += meta_len

                if meta_type == 0x51 and len(meta_bytes) == 3:  # Set Tempo
                    tempo_us = int.from_bytes(meta_bytes, "big")
                    self.tempo_events.append((curr_tick, tempo_us))
                elif meta_type == 0x58 and len(meta_bytes) >= 2:  # Time Signature
                    num = meta_bytes[0]
                    den = 2 ** meta_bytes[1]
                    self.time_sigs.append((curr_tick, num, den))
                elif meta_type == 0x59 and len(meta_bytes) >= 2:  # Key Signature
                    sf = int.from_bytes(meta_bytes[:1], "big", signed=True)
                    mi = meta_bytes[1]
                    self.key_sigs.append((curr_tick, sf, mi))
                elif meta_type in (0x01, 0x05):  # Text or Lyric
                    text = meta_bytes.decode("utf-8", errors="replace").strip()
                    if text:
                        self.lyrics.append((curr_tick, text))
                elif meta_type == 0x03:  # Track Name
                    name = meta_bytes.decode("utf-8", errors="replace").strip()
                    if name:
                        self.track_names[track_idx] = name
                elif meta_type == 0x06:  # Marker
                    marker = meta_bytes.decode("utf-8", errors="replace").strip()
                    if marker:
                        self.markers.append((curr_tick, marker))

            elif status in (0xF0, 0xF7):  # SysEx
                sysex_len, pos = _read_vlq(chunk, pos)
                pos += sysex_len

        # Close any lingering notes
        for (channel, pitch), starts in open_notes.items():
            for start_tick, vel in starts:
                dur = max(1, curr_tick - start_tick)
                self.notes.append({
                    "track": track_idx, "channel": channel, "pitch": pitch,
                    "start_tick": start_tick, "end_tick": curr_tick,
                    "duration_ticks": dur, "velocity": vel,
                })


def calculate_duration(parser: MidiParser) -> float:
    """Calculate exact duration in seconds from tempo map and note/track ticks."""
    tempo_map = sorted(parser.tempo_events, key=lambda x: x[0])
    if not tempo_map or tempo_map[0][0] > 0:
        tempo_map.insert(0, (0, 500000))  # Default 120 BPM

    max_tick = 0
    for note in parser.notes:
        if note["end_tick"] > max_tick:
            max_tick = note["end_tick"]

    if max_tick == 0:
        return 0.0

    seconds = 0.0
    div = parser.division

    for i, (t_start, us_beat) in enumerate(tempo_map):
        t_next = tempo_map[i + 1][0] if i + 1 < len(tempo_map) else max_tick
        t_end = min(max_tick, t_next)
        if t_end > t_start:
            dt = t_end - t_start
            seconds += (dt / div) * (us_beat / 1_000_000.0)
        if t_next >= max_tick:
            break

    return round(seconds, 2)


def estimate_key(parser: MidiParser) -> str:
    """Estimate musical key from key signature events or note pitch classes."""
    if parser.key_sigs:
        sf, mi = parser.key_sigs[0][1], parser.key_sigs[0][2]
        if mi == 1:
            return MINOR_KEYS_BY_SF.get(sf, "Am")
        return MAJOR_KEYS_BY_SF.get(sf, "C")

    # Fallback: Krumhansl-Schmuckler correlation
    pitch_counts = [0.0] * 12
    for n in parser.notes:
        pitch_counts[n["pitch"] % 12] += n["duration_ticks"]

    total = sum(pitch_counts)
    if total == 0:
        return "C"

    best_key = "C"
    best_corr = -999.0

    for root in range(12):
        # Shift profile
        maj_prof = [MAJOR_PROFILE[(i - root) % 12] for i in range(12)]
        min_prof = [MINOR_PROFILE[(i - root) % 12] for i in range(12)]

        def corr(p1, p2):
            mean1 = sum(p1) / 12.0
            mean2 = sum(p2) / 12.0
            num = sum((a - mean1) * (b - mean2) for a, b in zip(p1, p2))
            den = math.sqrt(sum((a - mean1) ** 2 for a in p1) * sum((b - mean2) ** 2 for b in p2))
            return num / den if den != 0 else 0.0

        c_maj = corr(pitch_counts, maj_prof)
        if c_maj > best_corr:
            best_corr = c_maj
            best_key = PITCH_NAMES[root]

        c_min = corr(pitch_counts, min_prof)
        if c_min > best_corr:
            best_corr = c_min
            best_key = PITCH_NAMES[root] + "m"

    return best_key


def detect_bar_chord(pitches: list[int], key: str, last_chord: str) -> str:
    """Determine the most fitting chord symbol for a bar given its sounding pitches."""
    if not pitches:
        return last_chord or (key.replace("m", "m") if key.endswith("m") else key)

    pitch_classes = set(p % 12 for p in pitches)
    lowest = min(pitches) % 12

    best_chord = None
    best_score = -1.0

    for root in range(12):
        root_name = PITCH_NAMES[root]
        for suffix, intervals, required_iv in CHORD_TEMPLATES:
            if required_iv is not None and ((root + required_iv) % 12) not in pitch_classes:
                continue

            target_pcs = set((root + iv) % 12 for iv in intervals)
            matched = len(pitch_classes & target_pcs)
            extra = len(pitch_classes - target_pcs)
            score = (matched * 2.0 - extra * 0.5)
            if root in pitch_classes:
                score += 1.0  # Root note is present
            if root == lowest:
                score += 1.5  # Matching bass note

            if score > best_score:
                best_score = score
                best_chord = root_name + suffix

    if best_chord and best_score >= 1.5:
        return best_chord
    return last_chord or (key.replace("m", "m") if key.endswith("m") else key)


def midi_to_abc(data: bytes, title: str = "") -> str:
    """Convert MIDI binary data into an ABC score with Vocal and Ins staves."""
    return parse_midi(data, title=title)["abc"]


def midi_duration(data: bytes) -> float:
    """Return total playback duration in seconds of a MIDI file."""
    parser = MidiParser(data)
    return calculate_duration(parser)


def parse_midi(data: bytes, title: str = "") -> dict[str, Any]:
    """Parse MIDI data into ABC score, duration, tempo, meter, key, and lyrics."""
    parser = MidiParser(data)
    duration_sec = calculate_duration(parser)

    # Meter
    if parser.time_sigs:
        num, den = parser.time_sigs[0][1], parser.time_sigs[0][2]
    else:
        num, den = 4, 4
    meter_str = f"{num}/{den}"

    # Tempo (BPM)
    if parser.tempo_events:
        us_per_beat = parser.tempo_events[0][1]
        bpm = round(60_000_000 / us_per_beat)
    else:
        bpm = 120

    # Key
    key = estimate_key(parser)

    # Clean Title
    if not title:
        for t_idx, name in parser.track_names.items():
            if name and not any(kw in name.lower() for kw in ("vocal", "piano", "guitar", "bass", "drum")):
                title = name
                break
    title = title or "Imported MIDI"

    # Quantization settings: grid is L: 1/16
    ticks_per_quarter = parser.division
    ticks_per_16th = ticks_per_quarter / 4.0
    ticks_per_bar = num * (16 // den) if den in (1, 2, 4, 8, 16) else 16

    # Filter melodic notes (skip channel 9 General MIDI percussion)
    melodic_notes = [n for n in parser.notes if n["channel"] != 9]
    if not melodic_notes:
        melodic_notes = parser.notes  # Fall back if only drum channel exists

    # Classify into Vocal (lead/melody) and Ins (accompaniment/harmony)
    tracks = sorted(set(n["track"] for n in melodic_notes))
    vocal_notes: list[dict[str, Any]] = []
    ins_notes: list[dict[str, Any]] = []

    # Check track names for hints
    vocal_tracks = set()
    for t in tracks:
        name = parser.track_names.get(t, "").lower()
        if any(w in name for w in ("vocal", "melody", "lead", "voice", "sing", "solo")):
            vocal_tracks.add(t)

    if vocal_tracks:
        for n in melodic_notes:
            if n["track"] in vocal_tracks:
                vocal_notes.append(n)
            else:
                ins_notes.append(n)
    elif len(tracks) > 1:
        # Highest average pitch track is vocal/lead
        avg_pitches = {}
        for t in tracks:
            t_notes = [n for n in melodic_notes if n["track"] == t]
            avg_pitches[t] = sum(n["pitch"] for n in t_notes) / len(t_notes) if t_notes else 0
        lead_track = max(avg_pitches, key=avg_pitches.get)
        for n in melodic_notes:
            if n["track"] == lead_track:
                vocal_notes.append(n)
            else:
                ins_notes.append(n)
    else:
        # Single track: split polyphony
        # Notes starting at same tick: highest pitch goes to vocal, others to ins
        by_start: dict[int, list[dict[str, Any]]] = {}
        for n in melodic_notes:
            by_start.setdefault(n["start_tick"], []).append(n)
        for start_t, group in by_start.items():
            sorted_group = sorted(group, key=lambda x: x["pitch"], reverse=True)
            vocal_notes.append(sorted_group[0])
            for lower_note in sorted_group[1:]:
                ins_notes.append(lower_note)

    # Quantize notes to 16th grid
    def quantize_note(n: dict[str, Any], voice_name: str) -> dict[str, Any]:
        q_start = round(n["start_tick"] / ticks_per_16th)
        q_end = max(q_start + 1, round(n["end_tick"] / ticks_per_16th))
        return {
            "pitch": n["pitch"],
            "voice": voice_name,
            "start_tick": q_start,
            "duration_ticks": q_end - q_start,
        }

    q_vocal = [quantize_note(n, "Vocal") for n in vocal_notes]
    q_ins = [quantize_note(n, "Ins") for n in ins_notes]

    max_tick = 0
    for n in q_vocal + q_ins:
        if n["start_tick"] + n["duration_ticks"] > max_tick:
            max_tick = n["start_tick"] + n["duration_ticks"]

    total_bars = max(4, math.ceil(max_tick / ticks_per_bar)) if ticks_per_bar > 0 else 4

    # Segment notes into bars and handle ties across bar boundaries
    # bar_segments[voice][bar_idx] -> list of {tick_in_bar, duration_ticks, pitch, tied}
    bar_segments: dict[str, dict[int, list[dict[str, Any]]]] = {"Vocal": {}, "Ins": {}}
    for b in range(total_bars):
        bar_segments["Vocal"][b] = []
        bar_segments["Ins"][b] = []

    for n in q_vocal + q_ins:
        voice = n["voice"]
        cur_tick = n["start_tick"]
        rem_dur = n["duration_ticks"]
        while rem_dur > 0:
            b_idx = cur_tick // ticks_per_bar
            if b_idx >= total_bars:
                break
            t_in_bar = cur_tick % ticks_per_bar
            space = ticks_per_bar - t_in_bar
            seg_dur = min(rem_dur, space)
            is_tied = rem_dur > seg_dur
            bar_segments[voice][b_idx].append({
                "tick_in_bar": t_in_bar,
                "duration_ticks": seg_dur,
                "pitch": n["pitch"],
                "tied": is_tied,
            })
            rem_dur -= seg_dur
            cur_tick += seg_dur

    # Identify chords for each bar
    bar_chords: list[str] = []
    last_chord = key.replace("m", "m") if key.endswith("m") else key
    for b in range(total_bars):
        sounding_pitches = [seg["pitch"] for seg in bar_segments["Vocal"][b] + bar_segments["Ins"][b]]
        ch = detect_bar_chord(sounding_pitches, key, last_chord)
        bar_chords.append(ch)
        last_chord = ch

    # Generate sections (intro, verse, chorus, outro)
    sections: list[tuple[int, str]] = []
    if parser.markers:
        for m_tick, m_text in parser.markers:
            q_tick = round(m_tick / ticks_per_16th)
            b_idx = min(total_bars - 1, q_tick // ticks_per_bar)
            name = m_text.strip().lower()
            if any(s in name for s in ("intro", "verse", "chorus", "bridge", "outro")):
                clean_sec = next(s for s in ("intro", "verse", "chorus", "bridge", "outro") if s in name)
                sections.append((b_idx, clean_sec))

    if not sections or sections[0][0] > 0:
        sections.insert(0, (0, "intro"))

    # If no markers or only intro, divide naturally
    if len(sections) == 1:
        if total_bars > 8:
            sections = [(0, "intro"), (4, "verse")]
            if total_bars > 16:
                sections.append((12, "chorus"))
            if total_bars > 24:
                sections.append((total_bars - 4, "outro"))
        else:
            sections = [(0, "verse")]

    # Deduplicate and sort sections by barIndex
    sections = sorted(dict(sections).items(), key=lambda x: x[0])

    # Build ABC score string
    lines: list[str] = [
        "X:1",
        f"T:{title}",
        f"M:{meter_str}",
        "L:1/16",
        f"Q:1/4={bpm}",
        'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
        'V: Ins clef=treble name="Ins Melody" snm="Inst."',
        f"K:{key}",
    ]

    # Render bar helper
    def render_bar(segs: list[dict[str, Any]], chord_name: str | None) -> str:
        if not segs:
            prefix = f'"{chord_name}"' if chord_name else ""
            return f"{prefix}z{ticks_per_bar}"

        # Group notes by tick_in_bar
        segs_by_tick: dict[int, list[dict[str, Any]]] = {}
        for s in segs:
            segs_by_tick.setdefault(s["tick_in_bar"], []).append(s)

        sorted_ticks = sorted(segs_by_tick.keys())
        cur_t = 0
        tokens: list[str] = []

        for idx, t in enumerate(sorted_ticks):
            if t > cur_t:
                gap = t - cur_t
                chord_prefix = f'"{chord_name}"' if (chord_name and idx == 0 and cur_t == 0) else ""
                tokens.append(f"{chord_prefix}z{gap if gap > 1 else ''}")
                cur_t = t

            chord_prefix = f'"{chord_name}"' if (chord_name and idx == 0 and cur_t == 0) else ""
            group = segs_by_tick[t]
            dur = group[0]["duration_ticks"]
            dur_str = str(dur) if dur > 1 else ""
            is_tied = group[0]["tied"]
            tie_str = "-" if is_tied else ""

            if len(group) == 1:
                n_str = midi_to_abc_pitch(group[0]["pitch"], key)
                tokens.append(f"{chord_prefix}{n_str}{dur_str}{tie_str}")
            else:
                chord_pitches = "".join(midi_to_abc_pitch(g["pitch"], key) for g in group)
                tokens.append(f"{chord_prefix}[{chord_pitches}]{dur_str}{tie_str}")

            cur_t += dur

        if cur_t < ticks_per_bar:
            gap = ticks_per_bar - cur_t
            tokens.append(f"z{gap if gap > 1 else ''}")

        return "".join(tokens)

    # Render section by section
    for s_idx, (s_bar, s_name) in enumerate(sections):
        next_s_bar = sections[s_idx + 1][0] if s_idx + 1 < len(sections) else total_bars
        end_bar = min(total_bars, next_s_bar)
        if s_bar >= end_bar:
            continue

        lines.append(f"% {s_name}")

        for voice in ("Vocal", "Ins"):
            lines.append(f"V: {voice}")
            bar_strs = []
            for b in range(s_bar, end_bar):
                chord_to_emit = bar_chords[b] if voice == "Vocal" else None
                bar_str = render_bar(bar_segments[voice][b], chord_to_emit)
                bar_strs.append(bar_str)

            # Group up to 4 bars per line
            for chunk_start in range(0, len(bar_strs), 4):
                chunk = bar_strs[chunk_start:chunk_start + 4]
                lines.append("|".join(chunk) + "|")

    abc_text = "\n".join(lines) + "\n"

    # Extract lyrics if present
    extracted_lyrics = None
    if parser.lyrics:
        words = [txt for _, txt in sorted(parser.lyrics, key=lambda x: x[0])]
        raw_text = " ".join(words)
        # Clean up syllable hyphens if any
        raw_text = raw_text.replace(" - ", " ").replace(" -", "").strip()
        if raw_text:
            extracted_lyrics = raw_text

    min_score_dur = round(total_bars * (num * (4.0 / den)) * (60.0 / bpm), 2)
    if duration_sec < min_score_dur and total_bars == 4:
        duration_sec = min_score_dur

    return {
        "duration": duration_sec,
        "abc": abc_text,
        "tempo": bpm,
        "key": key,
        "meter": meter_str,
        "title": title,
        "lyrics": extracted_lyrics,
        "sections": [s_name for _, s_name in sections],
    }
