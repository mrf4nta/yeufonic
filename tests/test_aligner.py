"""Tests for syllabification, monotonic phrase alignment, and ABC lyric embedding."""
import pytest
from app import aligner, score


def test_split_word_syllables_basic():
    """Verify standard English words split into sung syllables with hyphens."""
    assert aligner.split_word_syllables("better") == ["bet-", "ter"]
    assert aligner.split_word_syllables("remember") == ["re-", "mem-", "ber"]
    assert aligner.split_word_syllables("shoulder") == ["shoul-", "der"]
    assert aligner.split_word_syllables("refrain") == ["ref-", "rain"]
    assert aligner.split_word_syllables("performing") == ["per-", "for-", "ming"]


def test_split_word_syllables_silent_e_and_suffixes():
    """Verify silent trailing e rules and suffixes like -ment, -ful."""
    # Monosyllabic words with silent e
    assert aligner.split_word_syllables("make") == ["make"]
    assert aligner.split_word_syllables("Jude") == ["Jude"]
    assert aligner.split_word_syllables("take") == ["take"]
    assert aligner.split_word_syllables("colder") == ["col-", "der"]

    # Silent e before -ment
    assert aligner.split_word_syllables("movement") == ["move-", "ment"]
    # Silent e before -ful
    assert aligner.split_word_syllables("careful") == ["care-", "ful"]


def test_split_word_syllables_punctuation_and_hyphens():
    """Verify punctuation and pre-existing hyphens are preserved."""
    assert aligner.split_word_syllables("Hey,") == ["Hey,"]
    assert aligner.split_word_syllables("bad!") == ["bad!"]
    assert aligner.split_word_syllables("Na-na-na") == ["Na-", "na-", "na"]


def test_extract_lyrics_sections():
    """Verify lyric section header parsing and dangling connector clause handling."""
    lyrics = """[Verse 1]
Hey, Jude, don't make it bad
Take a sad song and

[Chorus]
make it better
"""
    sections = aligner.extract_lyrics_sections(lyrics)
    assert len(sections) == 2
    assert sections[0]["name"] == "Verse 1"
    # Dangling 'and' was moved to prefix the next line
    assert "and make it better" in sections[1]["lines"][0]


def test_align_lines_to_notes():
    """Verify DP alignment maps lines to notes respecting rests and under-allocation penalties."""
    # 2 lines, 6 notes: 3 notes, rest gap, 3 notes
    tokens = [["Hey,", "Jude,"], ["make", "it", "bet-", "ter"]]
    notes = [
        {"start_tick": 0, "dur": 4},
        {"start_tick": 4, "dur": 4},
        {"start_tick": 8, "dur": 4},
        {"start_tick": 24, "dur": 4},  # gap of 12 ticks
        {"start_tick": 28, "dur": 4},
        {"start_tick": 32, "dur": 4},
        {"start_tick": 36, "dur": 4},
    ]
    splits = aligner.align_lines_to_notes(tokens, notes, ticks_per_bar=16)
    assert len(splits) == 2
    assert splits[0]["start_idx"] == 0
    assert splits[0]["end_idx"] == 3
    assert splits[1]["start_idx"] == 3
    assert splits[1]["end_idx"] == 7


def test_align_lyrics_to_abc_clean_roundtrip():
    """Verify full ABC score has w: lines embedded cleanly and passes score check."""
    abc = """X:1
T:Alignment Test
M:4/4
L:1/16
Q:1/4=80
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:F
% verse
V: Vocal
"Am"C4A,10A,2|"C"C2D2G,8z4|"Edim"G,2A,2_B,4F6F2|"F"E2C2D2C_B,A,7z|
"C7"z2C2D2D4D2GF2E-|"Dm7"EFD2C5z3F,2G,2|"C"A,2D2C4z2C2_B,2A,2|"Csus4"E,2F,2F,5z7|
V: Ins
[C,F,A,]16|[C,E,G,]16|[E,G,_B,]16|[F,,F,A,]16|
[C,F,A,]16|[F,,F,A,]16|[C,E,G,]16|[F,,F,A,]16|
"""

    lyrics = """[Verse 1]
Hey, Jude, don't make it bad
Take a sad song and make it better
Remember to let her into your heart
Then you can start to make it better
"""

    aligned = aligner.align_lyrics_to_abc(abc, lyrics)
    assert "w: " in aligned
    assert "Hey, Jude, don't" in aligned
    assert "make it bet- ter" in aligned

    # Check for validity
    issues = score.problems(aligned)
    assert issues == []


def test_align_lyrics_to_abc_preserves_score_when_no_lyrics():
    """Verify empty or whitespace lyrics returns identical ABC unchanged."""
    abc = """X:1
T:No Lyrics
M:4/4
L:1/16
Q:1/4=120
K:C
% verse
V: Vocal
C4D4E4G4|G4F4E4D4|C4D4E4G4|G4F4E4D4|
V: Ins
[CEG]16|[G,B,D]16|[CEG]16|[G,B,D]16|
"""
    assert aligner.align_lyrics_to_abc(abc, "") == abc
    assert aligner.align_lyrics_to_abc(abc, "   \n\n  ") == abc


def test_align_lyrics_updates_abc_section_tags():
    """Verify that structured lyrics update ABC section comments to % chorus, % bridge, etc."""
    abc = """X:1
T:Multi Section Test
M:4/4
L:1/16
Q:1/4=100
K:C
% verse
V: Vocal
C4D4E4F4|G4A4B4c4|
V: Ins
[CEG]16|[CEG]16|
% verse
V: Vocal
c4B4A4G4|F4E4D4C4|
V: Ins
[G,B,D]16|[CEG]16|
% verse
V: Vocal
E4F4G4A4|B4c4d4e4|
V: Ins
[A,CE]16|[CEG]16|
"""
    lyrics = """[Verse 1]
Here comes the sun
It is alright

[Chorus]
Sun, sun, sun
Here it comes

[Outro]
Yeah yeah yeah
"""
    aligned = aligner.align_lyrics_to_abc(abc, lyrics)
    assert "% verse" in aligned
    assert "% chorus" in aligned
    assert "% outro" in aligned


def test_build_render_graph_strips_w_lines():
    """Verify that build_render_graph strips embedded w: lines from the score sent to YuE2."""
    from app import jobs
    take = {
        "id": "t123",
        "style": "indie rock",
        "lyrics": "[Verse 1]\nHello world",
        "abc": "X:1\nK:C\n% verse\nV: Vocal\nC4D4E4F4|\nw: Hel- lo world _ |\nV: Ins\n[CEG]16|\n",
        "seed": 42,
        "mode": "melody",
        "max_duration": 180,
    }
    graph = jobs.build_render_graph(take)
    submitted_abc = graph["11"]["inputs"]["abc"]
    assert "w: " not in submitted_abc
    assert "Hel- lo" not in submitted_abc
    assert "C4D4E4F4" in submitted_abc

