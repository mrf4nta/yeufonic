"""Robust syllable splitting, phrase alignment, and ABC lyric embedding.

Aligns human lyrics to vocal melody notes within an ABC score so that YuE2
synthesizes sung vocals with syllable timing and pitch accuracy.
"""
from __future__ import annotations

import re
from typing import Any


def split_word_syllables(word: str) -> list[str]:
    """Split an English word into hyphenated syllables for singing notes.

    Preserves existing hyphens, trailing hyphens, leading/trailing punctuation,
    silent 'e' stems before suffixes (-ment, -ful, -less, -ly, -ness), and
    consonant-le patterns.
    """
    if not word:
        return []
    if "-" in word:
        parts = [p for p in word.split("-") if p]
        if not parts:
            return []
        ends_with_hyphen = word.endswith("-")
        return [p + "-" if i < len(parts) - 1 or ends_with_hyphen else p for i, p in enumerate(parts)]

    m = re.match(r"^([^a-zA-Z]*)([a-zA-Z\x27\u2019]+)([^a-zA-Z]*)$", word)
    if not m:
        return [word]
    prefix, core, suffix = m.group(1), m.group(2), m.group(3)
    if len(core) <= 3:
        return [word]

    vowels = list(re.finditer(r"[aeiouy]+", core, re.IGNORECASE))
    if len(vowels) <= 1:
        return [word]

    indices = [{"start": vm.start(), "end": vm.end(), "str": vm.group(0)} for vm in vowels]
    forced_cut = None
    lower_core = core.lower()

    if len(indices) > 1:
        last_v = indices[-1]
        # Silent trailing 'e' (e.g. dance, love, alone, life, take, Jude)
        if last_v["end"] == len(core) and last_v["str"].lower() == "e":
            is_cons_le = len(core) >= 3 and lower_core[-2] == "l" and not re.search(r"[aeiouy]", lower_core[-3])
            if not is_cons_le:
                indices.pop()
        # Silent 'e' in '-ed' unless preceded by 't' or 'd' (e.g. walked vs waited)
        elif last_v["end"] == len(core) - 1 and lower_core.endswith("ed"):
            before_e = lower_core[-3] if len(lower_core) >= 3 else ""
            if before_e and before_e not in ("t", "d"):
                indices.pop()
        # Silent 'e' before suffixes -ment, -ful, -less, -ly, -ness (e.g. movement, lovely, careful)
        else:
            suf_m = re.match(r"^([a-z]+[aeiouy][a-z]*e)(ment|ful|less|ly|ness)$", lower_core)
            if suf_m:
                e_pos = len(suf_m.group(1)) - 1
                for vi, idx_item in enumerate(indices):
                    if idx_item["start"] == e_pos and idx_item["str"].lower() == "e":
                        indices.pop(vi)
                        forced_cut = e_pos + 1
                        break

    if len(indices) <= 1:
        return [word]

    cuts = []
    if forced_cut is not None:
        cuts.append(forced_cut)
    else:
        for i in range(len(indices) - 1):
            v1_end = indices[i]["end"]
            v2_start = indices[i + 1]["start"]
            num_cons = v2_start - v1_end
            if num_cons <= 1:
                cuts.append(v1_end)
            elif num_cons == 2:
                pair = lower_core[v1_end:v2_start]
                if pair in ("th", "ch", "sh", "ph", "wh", "ck", "qu"):
                    cuts.append(v1_end)
                else:
                    cuts.append(v1_end + 1)
            else:
                cuts.append(v1_end + 1)

    syllables = []
    last_idx = 0
    for c in cuts:
        if 0 < c < len(core):
            syllables.append(core[last_idx:c] + "-")
            last_idx = c
    if last_idx < len(core):
        syllables.append(core[last_idx:])

    if not syllables:
        return [word]
    syllables[0] = prefix + syllables[0]
    syllables[-1] = syllables[-1] + suffix
    return syllables


def extract_lyrics_sections(lyrics_text: str) -> list[dict[str, Any]]:
    """Partition lyrics into tagged sections (verse, chorus, bridge, etc.).

    Filters scraper artifacts and stitches dangling connector clauses across section headers.
    """
    sections: list[dict[str, Any]] = []
    current_sec: dict[str, Any] = {"name": "", "lines": []}
    raw_lines = (lyrics_text or "").splitlines()
    skipping_scraper = False

    for r in raw_lines:
        line = r.strip()
        if not line:
            if skipping_scraper:
                skipping_scraper = False
            continue
        tag_match = re.match(
            r"^(?:(?:\*{1,2}\s*)?\[([^\]]+)\](?:\s*\*{1,2})?|(?:#{1,6}|\*{1,2})\s*([A-Za-z]+(?:\s+[A-Za-z0-9_-]+)*)\s*(?:\*{1,2})?)$",
            line,
        )
        if tag_match:
            skipping_scraper = False
            sec_name = (tag_match.group(1) or tag_match.group(2)).strip()
            pending_dangling = None
            if current_sec["lines"]:
                last_line = current_sec["lines"][-1]
                if re.search(r"\b(?:the|a|an|and|to|it|of|in|that|with|for|or|as|by|on|at|so)\s*$", last_line, re.I):
                    pending_dangling = current_sec["lines"].pop()
            if current_sec["name"] or current_sec["lines"]:
                sections.append(current_sec)
            current_sec = {"name": sec_name, "lines": []}
            if pending_dangling:
                current_sec["pending_prefix"] = pending_dangling
        else:
            if re.match(r"^(\d+\s+Contributors?|Embed|\d+\s+Translations?)$", line, re.I):
                continue
            if re.match(r"^You might also like", line, re.I):
                skipping_scraper = True
                continue
            if skipping_scraper:
                continue
            if "pending_prefix" in current_sec:
                prefix = current_sec.pop("pending_prefix")
                if re.match(r"^[a-z]", line):
                    line = prefix + " " + line
                else:
                    current_sec["lines"].append(prefix)
            current_sec["lines"].append(line)

    if "pending_prefix" in current_sec:
        current_sec["lines"].insert(0, current_sec.pop("pending_prefix"))
    if current_sec["name"] or current_sec["lines"]:
        sections.append(current_sec)
    return sections


def tokenize_lyric_lines(lines: list[str]) -> list[str]:
    """Break a list of lyric lines into individual syllable tokens."""
    tokens = []
    for l in lines:
        cleaned = re.sub(r"\([^)]*\)", "", l).strip()
        if not cleaned:
            continue
        for m in re.finditer(r"([^\s-]+-?)", cleaned):
            raw_tok = m.group(1).strip()
            if raw_tok and raw_tok != "-":
                sylls = split_word_syllables(raw_tok)
                tokens.extend(sylls)
    return tokens


def align_lines_to_notes(
    lines_tokens: list[list[str]], notes: list[dict[str, Any]], ticks_per_bar: int = 16
) -> list[dict[str, int]]:
    """Monotonic boundary-aware sequence alignment via dynamic programming.

    Aligns multiple lyric lines to a sequence of vocal notes while respecting
    musical phrase boundaries (rests, bar lines, downbeats).
    """
    L = len(lines_tokens)
    N = len(notes)
    if L == 0 or N == 0:
        return []
    if L == 1:
        return [{"line_idx": 0, "start_idx": 0, "end_idx": N}]

    b_score = [0.0] * N
    for i in range(1, N):
        prev = notes[i - 1]
        curr = notes[i]
        rest = curr["start_tick"] - (prev["start_tick"] + prev["dur"])
        s = 0.0
        if rest >= 16:
            s += 100
        elif rest >= 8:
            s += 60
        elif rest >= 4:
            s += 40
        elif rest >= 2:
            s += 20
        elif rest > 0:
            s += 8

        if prev["dur"] >= 8:
            s += 15
        elif prev["dur"] >= 6:
            s += 8

        prev_bar = prev["start_tick"] // ticks_per_bar
        curr_bar = curr["start_tick"] // ticks_per_bar
        if curr_bar > prev_bar:
            s += 10 * (curr_bar - prev_bar)
        if (curr["start_tick"] % ticks_per_bar) == 0:
            s += 8
        b_score[i] = s

    def seg_cost(l: int, j: int, i: int) -> float:
        T = len(lines_tokens[l])
        M = i - j
        if M <= 0:
            return 10000.0
        if M == T:
            diff_cost = 0.0
        elif M > T:
            diff_cost = (M - T) * 2.0
        else:
            diff_cost = (T - M) * 35.0  # High penalty against dropping lyric words
        boundary_bonus = b_score[j] if j > 0 else 0.0
        return diff_cost - boundary_bonus

    dp = [[1e9] * (N + 1) for _ in range(L + 1)]
    parent = [[-1] * (N + 1) for _ in range(L + 1)]

    for b_idx in range(1, N + 1):
        dp[1][b_idx] = seg_cost(0, 0, b_idx)

    for l in range(2, L + 1):
        for ni in range(l, N + 1):
            for pj in range(l - 1, ni):
                c = dp[l - 1][pj] + seg_cost(l - 1, pj, ni)
                if c < dp[l][ni]:
                    dp[l][ni] = c
                    parent[l][ni] = pj

    splits = []
    curr_i = N
    for bl in range(L, 0, -1):
        prev_j = 0 if bl == 1 else parent[bl][curr_i]
        if prev_j < 0:
            prev_j = 0
        splits.insert(0, {"line_idx": bl - 1, "start_idx": prev_j, "end_idx": curr_i})
        curr_i = prev_j

    return splits


def assign_lyrics_to_vocal_notes(
    lines: list[str], sec_vocal_notes: list[dict[str, Any]], ticks_per_bar: int = 16
) -> int:
    """Assign lyric tokens from lines to a slice of vocal notes."""
    if not lines or not sec_vocal_notes:
        return 0
    line_tokens_list = []
    for l in lines:
        toks = tokenize_lyric_lines([l])
        if toks:
            line_tokens_list.append(toks)
    if not line_tokens_list:
        return 0

    splits = align_lines_to_notes(line_tokens_list, sec_vocal_notes, ticks_per_bar)
    count = 0

    for sp in splits:
        toks = line_tokens_list[sp["line_idx"]]
        seg_notes = sec_vocal_notes[sp["start_idx"] : sp["end_idx"]]
        if not seg_notes:
            continue
        limit = min(len(seg_notes), len(toks))
        for k in range(limit):
            seg_notes[k]["lyric"] = toks[k]
            count += 1
        for ek in range(limit, len(seg_notes)):
            seg_notes[ek]["lyric"] = "_"
    return count


def align_lyrics_to_abc(abc_text: str, lyrics_text: str) -> str:
    """Embed lyrics into an ABC score with accurate w: lines matched to vocal melody notes.

    Preserves ABC headers, chords, instrument staves, and section markers.
    """
    if not abc_text or not lyrics_text or not lyrics_text.strip():
        return abc_text

    lyric_sections = extract_lyrics_sections(lyrics_text)
    if not lyric_sections:
        return abc_text

    lines = abc_text.splitlines()

    # Determine meter
    ticks_per_bar = 16
    for l in lines:
        if l.startswith("M:"):
            m = re.match(r"M:\s*(\d+)/(\d+)", l)
            if m:
                num, den = int(m.group(1)), int(m.group(2))
                ticks_per_bar = num * (16 // den) if den in (1, 2, 4, 8, 16) else 16
                break

    # Parse vocal notes and bar structure from ABC
    # Note regex: chord "...", rest z\d*, bracket chord [...]\d*, single note [_^=]*[A-Ga-g][,']*\d*
    tok_re = re.compile(
        r'\"([^\"]*)\"|([zZ])(\d*)|\[([^\]]+)\](\d*)(-?)|([_^=]*[A-Ga-g][,\']*)(\d*)(-?)'
    )

    vocal_notes: list[dict[str, Any]] = []
    # Structure of lines: list of (line_type, content, extra_info)
    # line_type: 'header', 'section', 'voice_header', 'music_vocal', 'music_other', 'w_line', 'comment'
    parsed_lines = []
    curr_voice = None
    curr_bar = 0

    # Map bar_num -> list of note objects
    bar_to_notes: dict[int, list[dict[str, Any]]] = {}
    # Track section tags with bar indices
    score_sections: list[dict[str, Any]] = []
    curr_sec_name = "% verse"

    for l in lines:
        raw = l.strip()
        if not raw:
            parsed_lines.append(("empty", l, None))
            continue
        if raw.startswith("w:") or raw.startswith("W:"):
            # Skip existing lyric lines; will be regenerated freshly
            continue
        if raw.startswith("%"):
            curr_sec_name = raw
            score_sections.append({"bar": curr_bar, "text": raw})
            parsed_lines.append(("section", l, curr_bar))
            continue
        if raw.startswith("V:"):
            vm = re.match(r"^V:\s*(\S+)", raw)
            if vm:
                curr_voice = vm.group(1)
            parsed_lines.append(("voice_header", l, curr_voice))
            continue
        if re.match(r"^[A-Za-z]:", raw):
            parsed_lines.append(("header", l, None))
            continue

        if curr_voice == "Vocal":
            # Musical bars line for Vocal
            bar_strs = [b.strip() for b in raw.split("|") if b.strip()]
            line_bar_indices = []
            for b_str in bar_strs:
                b_num = curr_bar
                curr_bar += 1
                line_bar_indices.append(b_num)
                b_notes = []
                cur_t = 0
                for tm in tok_re.finditer(b_str):
                    if tm.group(1):  # chord
                        pass
                    elif tm.group(2):  # rest
                        r_dur = int(tm.group(3) or "1")
                        cur_t += r_dur
                    elif tm.group(4):  # chord bracket
                        c_dur = int(tm.group(5) or "1")
                        tied = tm.group(6) == "-"
                        note_obj = {
                            "bar": b_num,
                            "tick_in_bar": cur_t,
                            "start_tick": b_num * ticks_per_bar + cur_t,
                            "dur": c_dur,
                            "tied": tied,
                            "pitch": tm.group(4),
                            "lyric": "",
                        }
                        b_notes.append(note_obj)
                        vocal_notes.append(note_obj)
                        cur_t += c_dur
                    elif tm.group(7):  # single note
                        n_dur = int(tm.group(8) or "1")
                        tied = tm.group(9) == "-"
                        note_obj = {
                            "bar": b_num,
                            "tick_in_bar": cur_t,
                            "start_tick": b_num * ticks_per_bar + cur_t,
                            "dur": n_dur,
                            "tied": tied,
                            "pitch": tm.group(7),
                            "lyric": "",
                        }
                        b_notes.append(note_obj)
                        vocal_notes.append(note_obj)
                        cur_t += n_dur
                bar_to_notes[b_num] = b_notes
            parsed_lines.append(("music_vocal", l, line_bar_indices))
        else:
            parsed_lines.append(("music_other", l, None))

    if not vocal_notes:
        return abc_text

    vocal_notes.sort(key=lambda n: n["start_tick"])

    # Group vocal notes by score section
    if not score_sections:
        score_sections = [{"bar": 0, "text": "% verse"}]
    else:
        score_sections.sort(key=lambda x: x["bar"])

    vocal_score_sections = []
    for si, s_item in enumerate(score_sections):
        next_bar = score_sections[si + 1]["bar"] if si + 1 < len(score_sections) else float("inf")
        s_start = s_item["bar"] * ticks_per_bar
        s_end = next_bar * ticks_per_bar
        sec_notes = [n for n in vocal_notes if s_start <= n["start_tick"] < s_end]
        if sec_notes:
            vocal_score_sections.append({
                "bar": s_item["bar"],
                "text": s_item["text"],
                "notes": sec_notes,
            })

    # Subdivide coarse sections at musical pauses if score has fewer sections than lyrics
    if vocal_score_sections and len(vocal_score_sections) < len(lyric_sections):
        refined = []
        for sec_item in vocal_score_sections:
            notes = sec_item["notes"]
            splits = [0]
            last_b = notes[0]["start_tick"] // ticks_per_bar
            for ni in range(len(notes) - 1):
                e1 = notes[ni]["start_tick"] + notes[ni]["dur"]
                s2 = notes[ni + 1]["start_tick"]
                gap = s2 - e1
                b2 = s2 // ticks_per_bar
                if (gap >= 5 or (b2 - last_b) >= 14) and (b2 - last_b) >= 6:
                    splits.append(ni + 1)
                    last_b = b2
            splits.append(len(notes))
            if len(splits) > 2:
                for sp in range(len(splits) - 1):
                    sub_notes = notes[splits[sp] : splits[sp + 1]]
                    if sub_notes:
                        sub_bar = sub_notes[0]["start_tick"] // ticks_per_bar
                        refined.append({
                            "bar": sub_bar,
                            "text": sec_item["text"] if sp == 0 else "% verse",
                            "notes": sub_notes,
                        })
            else:
                refined.append(sec_item)
        if len(refined) > len(vocal_score_sections):
            vocal_score_sections = refined

    # Assign lyric sections monotonically to vocal score sections
    assigned_count = 0
    if vocal_score_sections and lyric_sections:
        curr_lyric_idx = 0
        num_score = len(vocal_score_sections)
        num_lyric = len(lyric_sections)

        for vsi in range(num_score):
            target_sec = vocal_score_sections[vsi]
            target_notes = target_sec["notes"]
            if not target_notes:
                continue

            rem_score = num_score - vsi
            rem_lyric = num_lyric - curr_lyric_idx

            if rem_lyric <= 0:
                for n in target_notes:
                    n["lyric"] = "_"
                continue

            lines_to_assign = []
            if rem_score <= 1:
                for li in range(curr_lyric_idx, num_lyric):
                    lines_to_assign.extend(lyric_sections[li]["lines"])
                curr_lyric_idx = num_lyric
            elif rem_score <= rem_lyric:
                take_count = rem_lyric // rem_score
                for li2 in range(curr_lyric_idx, curr_lyric_idx + take_count):
                    lines_to_assign.extend(lyric_sections[li2]["lines"])
                curr_lyric_idx += take_count
            else:
                lines_to_assign = lyric_sections[curr_lyric_idx]["lines"]
                curr_lyric_idx += 1

            if lines_to_assign:
                assigned_count += assign_lyrics_to_vocal_notes(lines_to_assign, target_notes, ticks_per_bar)

    # Fallback global alignment if no lyrics assigned
    if assigned_count == 0:
        all_lines = []
        for lsi in lyric_sections:
            all_lines.extend(lsi["lines"])
        assigned_count += assign_lyrics_to_vocal_notes(all_lines, vocal_notes, ticks_per_bar)

    # Reconstruct ABC text with w: lines
    out_lines = []
    for l_type, l_content, l_extra in parsed_lines:
        if l_type == "music_vocal":
            out_lines.append(l_content)
            # Build matching w: line for the bars in this line
            bar_indices = l_extra
            bar_lyric_tokens = []
            has_lyrics_in_line = False

            for b_idx in bar_indices:
                b_notes = bar_to_notes.get(b_idx, [])
                tokens_in_bar = []
                for n in b_notes:
                    lyr = n.get("lyric", "")
                    if lyr:
                        tokens_in_bar.append(lyr)
                        has_lyrics_in_line = True
                    else:
                        tokens_in_bar.append("*")
                while tokens_in_bar and tokens_in_bar[-1] == "*":
                    tokens_in_bar.pop()
                bar_lyric_tokens.append(" ".join(tokens_in_bar))

            if has_lyrics_in_line:
                w_str = "w: " + " | ".join(bar_lyric_tokens) + " |"
                out_lines.append(w_str)
        else:
            out_lines.append(l_content)

    return "\n".join(out_lines) + "\n"
