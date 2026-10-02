"""Tests for MIDI import, binary SMF parsing, ABC conversion, and source integration."""
import io
import struct
from pathlib import Path

import pytest

from app import midi, score
from app.db import one


def _vlq(n: int) -> bytes:
    """Encode an integer as a MIDI variable-length quantity."""
    out = bytearray()
    out.append(n & 0x7F)
    n >>= 7
    while n > 0:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def create_smf(
    tracks: list[list[tuple[int, bytes]]],
    division: int = 480,
    fmt: int = 1,
) -> bytes:
    """Build a standard MIDI file byte buffer.
    Each track is a list of (delta_ticks, event_bytes).
    """
    header = b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division)
    body = bytearray()
    for trk_events in tracks:
        trk_bytes = bytearray()
        for delta, event in trk_events:
            trk_bytes += _vlq(delta)
            trk_bytes += event
        # End of track if not present
        if not trk_bytes.endswith(b"\xFF\x2F\x00"):
            trk_bytes += _vlq(0) + b"\xFF\x2F\x00"
        body += b"MTrk" + struct.pack(">I", len(trk_bytes)) + trk_bytes
    return header + bytes(body)


def test_smf_parser_invalid_header():
    """Ensure parser refuses non-MIDI data."""
    with pytest.raises(ValueError, match="Invalid MIDI file"):
        midi.MidiParser(b"RIFF....WAVEfmt ")


def test_midi_duration_constant_tempo():
    """Verify duration calculation with a standard 120 BPM tempo."""
    # 120 BPM = 2 beats per second = 500,000 us/beat
    # 4 beats = 2.0 seconds (1920 ticks at div 480)
    meta = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 500,000 us (120 bpm)
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
    ]
    notes = [
        (0, bytes([0x90, 60, 80])),  # Note On C4
        (1920, bytes([0x80, 60, 0])),  # Note Off after 1920 ticks (4 beats = 2.0s)
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([meta + notes], division=480, fmt=0)
    dur = midi.midi_duration(data)
    assert dur == 2.0


def test_midi_duration_tempo_change():
    """Verify duration calculation across tempo changes."""
    # Beat 1 at 120 BPM (0.5s)
    # Beat 2 at 60 BPM (1.0s, 1,000,000 us)
    # Total = 1.5s
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 bpm (500,000 us)
        (0, bytes([0x90, 60, 80])),
        (480, b"\xFF\x51\x03\x0F\x42\x40"),  # 60 bpm (1,000,000 us)
        (480, bytes([0x80, 60, 0])),  # Note Off after 1 beat at 60 bpm
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([events], division=480, fmt=0)
    dur = midi.midi_duration(data)
    assert dur == 1.5


def test_pitch_to_abc():
    """Verify MIDI pitch numbers convert correctly to ABC note strings in various keys."""
    assert midi.midi_to_abc_pitch(60, "C") == "C"      # C4
    assert midi.midi_to_abc_pitch(62, "C") == "D"      # D4
    assert midi.midi_to_abc_pitch(72, "C") == "c"      # C5
    assert midi.midi_to_abc_pitch(84, "C") == "c'"     # C6
    assert midi.midi_to_abc_pitch(48, "C") == "C,"     # C3
    assert midi.midi_to_abc_pitch(36, "C") == "C,,"    # C2
    # Sharp key accidentals
    assert midi.midi_to_abc_pitch(61, "C") == "^C"
    assert midi.midi_to_abc_pitch(66, "G") == "^F"
    # Flat key accidentals
    assert midi.midi_to_abc_pitch(61, "F") == "_D"
    assert midi.midi_to_abc_pitch(70, "Bb") == "_B"


def test_chord_detection():
    """Verify chord estimation finds appropriate triad and seventh chords."""
    # C major triad: C, E, G
    assert midi.detect_bar_chord([60, 64, 67], "C", "C") == "C"
    # A minor triad: A, C, E
    assert midi.detect_bar_chord([57, 60, 64], "C", "C") == "Am"
    # G dominant 7: G, B, D, F
    assert midi.detect_bar_chord([55, 59, 62, 65], "C", "C") == "G7"
    # Empty pitches: retains previous or key
    assert midi.detect_bar_chord([], "G", "G") == "G"


def test_parse_single_track_midi_to_abc():
    """Test full conversion of a single-track MIDI into clean ABC score."""
    # 4 bars of 4/4 at 120 BPM in G major
    # Bar 1: G4(67) 4 ticks, B4(71) 4 ticks, D5(74) 8 ticks
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 BPM
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
        (0, b"\xFF\x59\x02\x01\x00"),  # 1 sharp (G major)
        (0, b"\xFF\x03\x09SingleMel"),  # Track name
        # Bar 1 notes
        (0, bytes([0x90, 67, 80])),
        (480, bytes([0x80, 67, 0, 0x90, 71, 80])),
        (480, bytes([0x80, 71, 0, 0x90, 74, 80])),
        (960, bytes([0x80, 74, 0])),
        # Bar 2 notes
        (0, bytes([0x90, 71, 80])),
        (1920, bytes([0x80, 71, 0])),
        # Bar 3 notes
        (0, bytes([0x90, 67, 80])),
        (1920, bytes([0x80, 67, 0])),
        # Bar 4 notes
        (0, bytes([0x90, 67, 80])),
        (1920, bytes([0x80, 67, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([events], division=480, fmt=0)
    parsed = midi.parse_midi(data, "Single Track Tune")

    assert parsed["key"] == "G"
    assert parsed["meter"] == "4/4"
    assert parsed["tempo"] == 120
    assert parsed["duration"] >= 8.0

    abc = parsed["abc"]
    assert "V: Vocal" in abc
    assert "V: Ins" in abc
    assert "K:G" in abc
    assert "Q:1/4=120" in abc

    # Validate against Yeufonic's score checker
    issues = score.problems(abc)
    assert issues == [], f"Generated ABC has issues: {issues}"

    # Estimate matches bars and duration
    est = score.estimate(abc)
    assert est is not None
    assert est["bars"] >= 4
    assert est["bpm"] == 120


def test_parse_multi_track_vocal_and_instrumental():
    """Test format 1 MIDI with designated Vocal and Piano accompaniment tracks."""
    # Track 0: Metadata & Vocal melody
    t0 = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 BPM
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
        (0, b"\xFF\x59\x02\x00\x00"),  # C major
        (0, b"\xFF\x03\x05Vocal"),
        # 4 bars of vocal notes
        (0, bytes([0x90, 72, 90])), (480, bytes([0x80, 72, 0])),
        (0, bytes([0x90, 74, 90])), (480, bytes([0x80, 74, 0])),
        (0, bytes([0x90, 76, 90])), (480, bytes([0x80, 76, 0])),
        (0, bytes([0x90, 79, 90])), (480, bytes([0x80, 79, 0])),
        # Bar 2
        (0, bytes([0x90, 76, 90])), (1920, bytes([0x80, 76, 0])),
        # Bar 3
        (0, bytes([0x90, 74, 90])), (1920, bytes([0x80, 74, 0])),
        # Bar 4
        (0, bytes([0x90, 72, 90])), (1920, bytes([0x80, 72, 0])),
        (0, b"\xFF\x2F\x00"),
    ]

    # Track 1: Accompaniment / Chords
    t1 = [
        (0, b"\xFF\x03\x05Piano"),
        # Bar 1 C major chord (C3 48, G3 55, E4 64)
        (0, bytes([0x91, 48, 70, 0x00, 0x91, 55, 70, 0x00, 0x91, 64, 70])),
        (1920, bytes([0x81, 48, 0, 0x00, 0x81, 55, 0, 0x00, 0x81, 64, 0])),
        # Bar 2 A minor chord (A2 45, E3 52, C4 60)
        (0, bytes([0x91, 45, 70, 0x00, 0x91, 52, 70, 0x00, 0x91, 60, 70])),
        (1920, bytes([0x81, 45, 0, 0x00, 0x81, 52, 0, 0x00, 0x81, 60, 0])),
        # Bar 3 F major chord (F2 41, C3 48, A3 57)
        (0, bytes([0x91, 41, 70, 0x00, 0x91, 48, 70, 0x00, 0x91, 57, 70])),
        (1920, bytes([0x81, 41, 0, 0x00, 0x81, 48, 0, 0x00, 0x81, 57, 0])),
        # Bar 4 G major chord (G2 43, D3 50, B3 59)
        (0, bytes([0x91, 43, 70, 0x00, 0x91, 50, 70, 0x00, 0x91, 59, 70])),
        (1920, bytes([0x81, 43, 0, 0x00, 0x81, 50, 0, 0x00, 0x81, 59, 0])),
        (0, b"\xFF\x2F\x00"),
    ]

    data = create_smf([t0, t1], division=480, fmt=1)
    parsed = midi.parse_midi(data, "Two Track Ballad")
    abc = parsed["abc"]

    assert score.problems(abc) == []
    # Vocal voice should carry the melody notes
    assert "c4d4e4g4" in abc
    # Ins voice should contain chords
    assert "[C,G,E]16" in abc


def test_note_tied_across_bars():
    """Verify notes that cross bar boundaries are properly split and tied with hyphen."""
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 BPM
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
        # Note starts at beat 3 (tick 1440), lasts 2 beats (960 ticks), ending at beat 5 (bar 1 beat 1)
        (1440, bytes([0x90, 60, 80])),
        (960, bytes([0x80, 60, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([events], division=480, fmt=0)
    parsed = midi.parse_midi(data, "Tied Note Test")
    abc = parsed["abc"]

    assert "C4-|" in abc or "C4-" in abc
    assert score.problems(abc) == []


def test_extract_lyrics_and_markers():
    """Verify lyrics and section markers are cleanly extracted."""
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
        (0, b"\xFF\x06\x05intro"),  # Marker
        (0, b"\xFF\x05\x05Hel-"),  # Lyric
        (0, bytes([0x90, 60, 80])),
        (480, bytes([0x80, 60, 0])),
        (0, b"\xFF\x05\x02lo"),  # Lyric
        (0, bytes([0x90, 62, 80])),
        (480, bytes([0x80, 62, 0])),
        (0, b"\xFF\x05\x06 world"),  # Lyric
        (0, bytes([0x90, 64, 80])),
        (960, bytes([0x80, 64, 0])),
        (0, b"\xFF\x06\x05verse"),  # Marker
        (0, bytes([0x90, 67, 80])),
        (1920, bytes([0x80, 67, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([events], division=480, fmt=0)
    parsed = midi.parse_midi(data, "Lyric Test")

    assert parsed["lyrics"] is not None
    assert "world" in parsed["lyrics"].lower()
    assert "% intro" in parsed["abc"]
    assert "% verse" in parsed["abc"]


# ---------------------------------------------------------------- API Tests
def test_upload_midi_source(client):
    """Test uploading a .mid file creates a source record marked done with ABC."""
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 BPM
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
        (0, b"\xFF\x59\x02\x00\x00"),  # C
        (0, bytes([0x90, 60, 80])),
        (1920, bytes([0x80, 60, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    midi_data = create_smf([events], division=480, fmt=0)

    res = client.post(
        "/api/sources",
        files={"file": ("song.mid", io.BytesIO(midi_data), "audio/midi")},
        data={"title": "Uploaded MIDI Test"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Uploaded MIDI Test"
    assert data["transcribe_state"] == "done"
    assert data["abc"] is not None
    assert "V: Vocal" in data["abc"]
    assert data["duration"] >= 2.0

    src_id = data["id"]

    # Check GET /api/sources list includes it
    list_res = client.get("/api/sources")
    assert list_res.status_code == 200
    sources = list_res.json()
    matched = [s for s in sources if s["id"] == src_id]
    assert len(matched) == 1
    assert bool(matched[0]["has_score"]) is True
    assert matched[0]["score_bpm"] == 120

    # Peaks endpoint returns synthetic peaks without 500 error
    peaks_res = client.get(f"/api/sources/{src_id}/peaks")
    assert peaks_res.status_code == 200
    assert "peaks" in peaks_res.json()

    # Audio endpoint returns the MIDI file
    audio_res = client.get(f"/api/sources/{src_id}/audio")
    assert audio_res.status_code == 200
    assert audio_res.headers["content-type"] == "audio/midi"

    # Transcribe endpoint returns done immediately
    tr_res = client.post(f"/api/sources/{src_id}/transcribe")
    assert tr_res.status_code == 200
    assert tr_res.json()["transcribe_state"] == "done"

    # Stems endpoint refuses MIDI
    stems_res = client.post(f"/api/sources/{src_id}/stems", json={"model": "htdemucs"})
    assert stems_res.status_code == 400

    # Lyrics endpoint refuses MIDI
    lyr_res = client.post(f"/api/sources/{src_id}/lyrics")
    assert lyr_res.status_code == 400


def test_cover_from_midi_source(client):
    """Test generating a cover from an imported MIDI source hands over its score."""
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
        (0, bytes([0x90, 60, 80])), (480, bytes([0x80, 60, 0])),
        (0, bytes([0x90, 62, 80])), (480, bytes([0x80, 62, 0])),
        (0, bytes([0x90, 64, 80])), (480, bytes([0x80, 64, 0])),
        (0, bytes([0x90, 67, 80])), (480, bytes([0x80, 67, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    midi_data = create_smf([events], division=480, fmt=0)
    upload_res = client.post(
        "/api/sources",
        files={"file": ("cover_me.midi", io.BytesIO(midi_data), "audio/midi")},
        data={"title": "MIDI Cover Base"},
    )
    src_id = upload_res.json()["id"]

    # Queue cover take
    take_res = client.post(
        "/api/takes",
        json={
            "source_id": src_id,
            "title": "My MIDI Cover",
            "style": "indie rock",
            "lyrics": "hello world",
        },
    )
    assert take_res.status_code == 200
    take_data = take_res.json()
    assert take_data["source_id"] == src_id
    assert take_data["status"] == "queued"
    assert "V: Vocal" in take_data["abc"]


def test_instrumental_from_midi_source(client):
    """Test generating an instrumental from an imported MIDI source uses its score."""
    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
        (0, bytes([0x90, 60, 80])), (480, bytes([0x80, 60, 0])),
        (0, bytes([0x90, 62, 80])), (480, bytes([0x80, 62, 0])),
        (0, bytes([0x90, 64, 80])), (480, bytes([0x80, 64, 0])),
        (0, bytes([0x90, 67, 80])), (480, bytes([0x80, 67, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    midi_data = create_smf([events], division=480, fmt=0)
    upload_res = client.post(
        "/api/sources",
        files={"file": ("inst_base.mid", io.BytesIO(midi_data), "audio/midi")},
        data={"title": "MIDI Inst Base"},
    )
    src_id = upload_res.json()["id"]

    # Queue instrumental
    inst_res = client.post(
        "/api/instrumentals",
        json={
            "source_id": src_id,
            "title": "My MIDI Instrumental",
            "style": "ambient electronic",
            "structure": "[instrumental]",
        },
    )
    assert inst_res.status_code == 200
    inst_data = inst_res.json()
    assert inst_data["source_id"] == src_id
    assert inst_data["status"] == "queued"
    # Tune was moved from Vocal to Ins for instrumental
    assert "V: Ins" in inst_data["abc"]


def test_multi_track_vocal_selection_and_polyphony_reduction():
    """Verify multiple vocal tracks (vox, choir) are merged monophonically, and lead guitar is not treated as vocal."""
    # Track 0: Lead Vox
    t0 = [
        (0, b"\xFF\x01\x08Lead Vox"),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),  # 4/4
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 bpm
        (0, bytes([0x90, 60, 80])), (480, bytes([0x80, 60, 0])),
        (480, bytes([0x90, 62, 80])), (480, bytes([0x80, 62, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    # Track 1: Choir (overlapping vocal)
    t1 = [
        (0, b"\xFF\x01\x05Choir"),
        (480, bytes([0x91, 72, 80])), (480, bytes([0x81, 72, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    # Track 2: Lead Guitr (should NOT be treated as vocal)
    t2 = [
        (0, b"\xFF\x01\x0ALead Guitr"),
        (0, bytes([0x92, 76, 80])), (960, bytes([0x82, 76, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    # Track 3: Piano (accompaniment)
    t3 = [
        (0, b"\xFF\x01\x05Piano"),
        (0, bytes([0x93, 48, 80, 0x00, 0x93, 52, 80, 0x00, 0x93, 55, 80])),
        (960, bytes([0x83, 48, 0, 0x00, 0x83, 52, 0, 0x00, 0x83, 55, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([t0, t1, t2, t3], division=480, fmt=1)
    parsed = midi.parse_midi(data, "Multi Vocal Test")
    abc = parsed["abc"]
    assert "V: Vocal" in abc
    assert "V: Ins" in abc
    # No score problems
    assert score.problems(abc) == []
    # Lyrics should NOT contain track names
    assert parsed["lyrics"] is None


def test_real_bohemian_rhapsody_midi_conversion():
    """Verify the Bohemian Rhapsody MIDI converts cleanly without score problems or track name pollution."""
    midi_path = Path("/mnt/c/Users/paul/Downloads/Queen - Bohemian Rhapsody.mid")
    if not midi_path.exists():
        pytest.skip("Bohemian Rhapsody MIDI not present in Downloads")
    data = midi_path.read_bytes()
    parsed = midi.parse_midi(data, "Queen - Bohemian Rhapsody")
    assert parsed["lyrics"] is None
    assert parsed["meter"] == "2/4"
    assert parsed["tempo"] == 78
    assert parsed["duration"] > 300
    abc = parsed["abc"]
    assert score.problems(abc) == []
    est = score.estimate(abc)
    assert est["bars"] > 100


def test_real_yesterday_midi_conversion():
    """Verify Yesterday MIDI converts to F major with accurate chord detection and section placement."""
    midi_path = Path("data/sources/6256bb1cf564e776-yesterday.mid")
    if not midi_path.exists():
        midi_path = Path("/mnt/c/Users/paul/Downloads/yesterday.mid")
    if not midi_path.exists():
        pytest.skip("yesterday.mid not found")

    data = midi_path.read_bytes()
    parsed = midi.parse_midi(data, "yesterday")
    assert parsed["key"] == "F"
    assert parsed["meter"] == "4/4"
    abc = parsed["abc"]
    assert score.problems(abc) == []

    # Check intro and verse sections
    assert "% intro" in abc
    assert "% verse" in abc

    # Chords in F major: F, Em7, Dm, Bb (not Csus4 or A#maj7)
    assert '"F"' in abc
    assert '"Bb"' in abc
    assert '"A#maj7"' not in abc

    # Bracket chords preserved in accompaniment
    assert "[CF]" in abc or "[A,CF]" in abc or "[_B,,_B,D]" in abc


def test_vocal_melody_legato_gap_closing():
    """Verify that articulation micro-gaps (<= 1 sixteenth note) are closed to legato phrasing
    while genuine musical rests (>= 2 sixteenth notes) are preserved."""
    # 4/4 meter, div 480 -> 1 sixteenth = 120 ticks, 1 eighth = 240 ticks
    # Note 1: 0..160 (staccato eighth, release gap of 80 ticks to next note at 240)
    # Note 2: 240..400 (staccato eighth, release gap of 80 ticks to next note at 480)
    # Note 3: 480..880 (dur 400 ticks, release gap of 80 ticks to next note at 960)
    # Note 4: 960..1200 (dur 240 ticks)
    t0 = [
        (0, b"\xFF\x01\x05Vocal"),
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
        (0, b"\xFF\x51\x03\x07\xA1\x20"),
        (0, bytes([0x90, 60, 80])), (160, bytes([0x80, 60, 0])),
        (80, bytes([0x90, 62, 80])), (160, bytes([0x80, 62, 0])),
        (80, bytes([0x90, 64, 80])), (400, bytes([0x80, 64, 0])),
        (80, bytes([0x90, 65, 80])), (240, bytes([0x80, 65, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    data = create_smf([t0], division=480, fmt=0)
    parsed = midi.parse_midi(data, "Gap Closing Test")
    abc = parsed["abc"]
    assert score.problems(abc) == []
    # Notes 1 & 2 should be legato eighth notes (dur 2 sixteenths) rather than 'C z D z'
    vocal_bars = score.vocal_bars(abc)
    first_bar = vocal_bars[0]
    assert "Cz" not in first_bar
    assert "Dz" not in first_bar
    assert "C2D2E4F2" in first_bar


def test_real_hey_jude_midi_conversion():
    """Verify Hey Jude MIDI converts cleanly with legato vocal phrasing and banner noise excluded."""
    midi_paths = list(Path("data/sources").glob("*beatles-hey-jude*.mid"))
    if not midi_paths:
        pytest.skip("Hey Jude MIDI not found")
    data = midi_paths[0].read_bytes()
    parsed = midi.parse_midi(data, "Hey Jude")
    assert parsed["key"] == "F"
    assert parsed["meter"] == "4/4"
    assert parsed["tempo"] == 74
    assert parsed["lyrics"] is None  # BBS banner comments filtered out
    abc = parsed["abc"]
    assert score.problems(abc) == []
    vocal_bars = score.vocal_bars(abc)
    # Bar 3 was '_B3zf5zfzezcz' before gap closing; now cleanly legato '_B4f6f2e2c2'
    assert "_B4f6f2e2c2" in vocal_bars[3]


def test_hey_jude_synth_lead_melody_classification():
    """Verify track classifier selects Track 8 (Smooth Synth) over Track 0 (4150 strumming guitar notes)."""
    p = Path("data/sources/1afc5fac27224e3e-the-beatles-hey-jude.mid")
    if not p.exists():
        pytest.skip("Hey Jude new MIDI not found")
    data = p.read_bytes()
    parsed = midi.parse_midi(data, "The Beatles - Hey Jude")
    tracks = parsed["tracks"]
    vocal_track = next((t for t in tracks if t["role"] == "vocal"), None)
    assert vocal_track is not None
    assert vocal_track["track"] == 8
    assert "Synth" in vocal_track["name"]

    # Verify Vocal melody contains the authentic Hey Jude melody normalized to vocal singing register
    abc = parsed["abc"]
    assert score.problems(abc) == []
    assert parsed.get("octave_shift") == 1
    vocal_bars = score.vocal_bars(abc)
    assert "c4A10A2" in vocal_bars[0]  # Hey, Jude, don't (normalized +1 octave)


def test_source_tracks_and_retrack_api(client):
    """Verify GET /api/sources/{id}/tracks and POST /api/sources/{id}/retrack endpoints."""
    p = Path("data/sources/1afc5fac27224e3e-the-beatles-hey-jude.mid")
    if not p.exists():
        pytest.skip("Hey Jude new MIDI not found")
    res = client.post(
        "/api/sources",
        files={"file": ("hey_jude_test.mid", io.BytesIO(p.read_bytes()), "audio/midi")},
        data={"title": "Hey Jude Track Test"},
    )
    assert res.status_code == 200
    src_id = res.json()["id"]

    # Get tracks
    trk_res = client.get(f"/api/sources/{src_id}/tracks")
    assert trk_res.status_code == 200
    tracks = trk_res.json()["tracks"]
    assert len(tracks) >= 8
    t8 = next(t for t in tracks if t["track"] == 8)
    assert t8["role"] == "vocal"

    # Retrack: switch vocal to Track 8 explicitly with auto-octave
    retrack_res = client.post(
        f"/api/sources/{src_id}/retrack",
        json={"vocal_track": 8, "ins_track": 2},
    )
    assert retrack_res.status_code == 200
    retrack_data = retrack_res.json()
    assert "c4A10A2" in retrack_data["abc"]

    # Retrack: switch vocal to Track 8 explicitly with octave_shift=0 (original low baritone)
    retrack_res_0 = client.post(
        f"/api/sources/{src_id}/retrack",
        json={"vocal_track": 8, "ins_track": 2, "octave_shift": 0},
    )
    assert retrack_res_0.status_code == 200
    assert "C4A,10A,2" in retrack_res_0.json()["abc"]


def test_take_auto_embeds_lyrics_in_abc(client):
    """Verify that creating a take with lyrics automatically embeds w: lines into the ABC score."""
    p = Path("data/sources/1afc5fac27224e3e-the-beatles-hey-jude.mid")
    if not p.exists():
        pytest.skip("Hey Jude new MIDI not found")
    upload_res = client.post(
        "/api/sources",
        files={"file": ("hey_jude_lyrics_test.mid", io.BytesIO(p.read_bytes()), "audio/midi")},
        data={"title": "Hey Jude Lyrics Base"},
    )
    src_id = upload_res.json()["id"]

    lyrics = (
        "[Verse 1]\n"
        "Hey, Jude, don't make it bad\n"
        "Take a sad song and make it better\n"
        "Remember to let her into your heart\n"
        "Then you can start to make it better\n"
    )

    take_res = client.post(
        "/api/takes",
        json={
            "source_id": src_id,
            "title": "Hey Jude Aligned Take",
            "style": "piano ballad",
            "lyrics": lyrics,
        },
    )
    assert take_res.status_code == 200
    take_data = take_res.json()
    abc = take_data["abc"]
    assert "w: " in abc
    assert "Hey, Jude, don't" in abc
    assert "make it bet- ter" in abc
    assert score.problems(abc) == []

