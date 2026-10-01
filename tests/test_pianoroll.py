"""Tests for the visual Piano Roll / MIDI editor and ABC bidirectional conversion."""
import json
import subprocess
from pathlib import Path

from app import score

PIANOROLL_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "pianoroll.js"


def run_node_script(js_code: str) -> dict:
    """Run a small JS snippet importing pianoroll.js and return parsed JSON result."""
    script = f"""
    const {{ parseAbc, serializeToAbc, PianoRoll, extractLyricsSections, tokenizeLyricLines, matchScoreSectionToLyricSection, splitWordSyllables }} = require({json.dumps(str(PIANOROLL_JS))});
    {js_code}
    """
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_abc_to_piano_roll_roundtrip():
    """Verify that an ABC score converts to Piano Roll model and serializes back without loss."""
    raw_abc = (
        "X:1\n"
        "T:Melody Test\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=128\n"
        "V: Vocal clef=treble name=\"Vocal Melody\" snm=\"Vocal\"\n"
        "V: Ins clef=treble name=\"Ins Melody\" snm=\"Inst.\"\n"
        "K:C\n"
        "% intro\n"
        "V: Vocal\n"
        "\"C\"z4 c4 d4 e4 | \"G\"d8 \"C\"c8 | \"F\"a4 g4 f4 e4 | \"C\"c16 |\n"
        "V: Ins\n"
        "\"C\"C8 E8 | \"G\"G8 C8 | \"F\"F8 A8 | \"C\"C16 |\n"
    )

    js = f"""
    const input = {json.dumps(raw_abc)};
    const model = parseAbc(input);
    const output = serializeToAbc(model);
    console.log(JSON.stringify({{
        noteCount: model.notes.length,
        voices: model.voices,
        sections: model.sections,
        chords: model.chords,
        outputAbc: output
    }}));
    """
    data = run_node_script(js)

    assert data["noteCount"] == 17
    assert "Vocal" in data["voices"] and "Ins" in data["voices"]
    assert len(data["sections"]) >= 1
    assert len(data["chords"]) >= 4

    out_abc = data["outputAbc"]
    assert score.problems(out_abc) == []
    est_orig = score.estimate(raw_abc)
    est_out = score.estimate(out_abc)
    assert est_orig == est_out
    assert est_out["bars"] == 4
    assert est_out["bpm"] == 128


def test_piano_roll_note_editing():
    """Verify modifying note pitch, timing, duration, adding and deleting notes in Piano Roll."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% intro\n"
        "V: Vocal\n"
        "\"C\"c4 d4 e4 f4 | \"G\"g16 | \"Am\"a8 e8 | \"F\"f16 |\n"
        "V: Ins\n"
        "z16 | z16 | z16 | z16 |\n"
    )

    js = f"""
    const input = {json.dumps(raw_abc)};
    const model = parseAbc(input);

    // 1. Move pitch of first note (C5/72 -> D5/74)
    model.notes[0].pitch = 74;

    // 2. Lengthen second note from 4 ticks to 6 ticks
    model.notes[1].durationTicks = 6;

    // 3. Shift third note later by 2 ticks
    model.notes[2].startTick += 2;
    model.notes[2].durationTicks = 2;

    // 4. Delete fourth note
    model.notes.splice(3, 1);

    // 5. Add a new note in Ins voice at bar 1 (tick 16)
    model.notes.push({{
        id: 999,
        voice: 'Ins',
        pitch: 60,
        startTick: 16,
        durationTicks: 8
    }});

    const output = serializeToAbc(model);
    console.log(JSON.stringify({{ outputAbc: output }}));
    """
    data = run_node_script(js)
    edited_abc = data["outputAbc"]

    assert score.problems(edited_abc) == []
    est = score.estimate(edited_abc)
    assert est["bars"] == 4
    assert est["bpm"] == 120


def test_piano_roll_tied_notes_across_bars():
    """Verify notes crossing measure boundaries are tied with '-' in ABC and re-merged on read."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=100\n"
        "K:C\n"
        "% intro\n"
        "V: Vocal\n"
        "\"C\"z16 | \"G\"z16 | \"F\"z16 | \"C\"z16 |\n"
        "V: Ins\n"
        "z16 | z16 | z16 | z16 |\n"
    )

    js = f"""
    const input = {json.dumps(raw_abc)};
    const model = parseAbc(input);

    // Create a note spanning across bar 0 into bar 1:
    // Starts at tick 12 of bar 0, lasts 20 ticks (ends at tick 16 of bar 1)
    model.notes.push({{
        id: 101,
        voice: 'Vocal',
        pitch: 65, // F4
        startTick: 12,
        durationTicks: 20
    }});

    const outAbc = serializeToAbc(model);
    const reparsed = parseAbc(outAbc);

    console.log(JSON.stringify({{
        outAbc: outAbc,
        reparsedNoteCount: reparsed.notes.length,
        firstNote: reparsed.notes[0]
    }}));
    """
    data = run_node_script(js)
    out_abc = data["outAbc"]

    assert "F4-" in out_abc or "f4-" in out_abc or "F" in out_abc
    assert score.problems(out_abc) == []

    # Verify re-parsing merges it back into one continuous 20-tick note
    assert data["reparsedNoteCount"] == 1
    assert data["firstNote"]["startTick"] == 12
    assert data["firstNote"]["durationTicks"] == 20
    assert data["firstNote"]["pitch"] == 65


def test_key_accidentals_flats_and_sharps():
    """Verify flat keys (F, Bb, Dm) and sharp keys (G, D, A) format accidentals cleanly."""
    js = """
    const inputF = `X:1\\nM:4/4\\nL:1/16\\nQ:1/4=110\\nK:F\\n% intro\\nV: Vocal\\n\"F\"z16|\"Bb\"z16|\"C\"z16|\"F\"z16|\\nV: Ins\\nz16|z16|z16|z16|\\n`;
    const modelF = parseAbc(inputF);
    // Add Bb4 (pitch 70)
    modelF.notes.push({ id: 1, voice: 'Vocal', pitch: 70, startTick: 0, durationTicks: 4 });
    const outF = serializeToAbc(modelF);

    const inputG = `X:1\\nM:4/4\\nL:1/16\\nQ:1/4=110\\nK:G\\n% intro\\nV: Vocal\\n\"G\"z16|\"D\"z16|\"C\"z16|\"G\"z16|\\nV: Ins\\nz16|z16|z16|z16|\\n`;
    const modelG = parseAbc(inputG);
    // Add F#4 (pitch 66)
    modelG.notes.push({ id: 2, voice: 'Vocal', pitch: 66, startTick: 0, durationTicks: 4 });
    const outG = serializeToAbc(modelG);

    console.log(JSON.stringify({ outF, outG }));
    """
    data = run_node_script(js)

    assert score.problems(data["outF"]) == []
    assert "_B" in data["outF"] or "_b" in data["outF"]

    assert score.problems(data["outG"]) == []
    assert "^F" in data["outG"] or "^f" in data["outG"]


def test_good_score_roundtrip_and_editing():
    """Verify that a real YuE2 plan (like GOOD in test_score) roundtrips with 0 problems."""
    good_abc = (
        'X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=97\n'
        'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
        'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:Dm\n'
        '% intro\nV: Vocal\n'
        '"Dm"d8f8a8z8|"Dm"z32|"Dm"z32|"Bbmaj7"z32|\n'
        'V: Ins\n'
        'Z|D2F2E2F2|D,4D,4|B,,4A,4|\n'
        'V: Vocal\n'
        '"Gm"z32|"Bm7b5"z32|"C7/Bb"z16"Bm7"z16|"Bm7"z32|\n'
    )
    assert score.problems(good_abc) == []
    est_orig = score.estimate(good_abc)

    js = f"""
    const input = {json.dumps(good_abc)};
    const model = parseAbc(input);
    const out = serializeToAbc(model);

    // Edit in piano roll: add a note in Vocal voice in bar 1
    model.notes.push({{
        id: 777,
        voice: 'Vocal',
        pitch: 62, // D4
        startTick: 32, // Bar 1 (since L:1/32 has 32 ticks per bar)
        durationTicks: 8
    }});
    const edited = serializeToAbc(model);

    console.log(JSON.stringify({{ out, edited }}));
    """
    data = run_node_script(js)

    assert score.problems(data["out"]) == []
    est_out = score.estimate(data["out"])
    assert est_out["bars"] == est_orig["bars"]
    assert est_out["bpm"] == est_orig["bpm"]

    assert score.problems(data["edited"]) == []
    est_edited = score.estimate(data["edited"])
    assert est_edited["bars"] == est_orig["bars"]


def test_piano_roll_transport_stepping():
    """Verify transport operations: stepNext, stepPrev (at boundary vs mid-bar), and rewindToStart."""
    js = """
    PianoRoll.model = parseAbc("X:1\\nM:4/4\\nL:1/16\\nQ:1/4=120\\nK:C\\n% intro\\nV: Vocal\\nz16|z16|z16|z16|\\n");
    PianoRoll.playheadTick = 0;

    // 1. Step forward 1 bar (16 ticks per bar in 4/4 with L:1/16)
    PianoRoll.stepNext();
    const tick1 = PianoRoll.playheadTick;

    // 2. Step forward another bar
    PianoRoll.stepNext();
    const tick2 = PianoRoll.playheadTick;

    // 3. Move playhead midway into bar 2 (tick 37)
    PianoRoll.seekTick(37);

    // 4. Stepping back while midway into bar 2 rewinds to the start of bar 2 (tick 32)
    PianoRoll.stepPrev();
    const tick3 = PianoRoll.playheadTick;

    // 5. Stepping back while at the start of bar 2 steps back to bar 1 (tick 16)
    PianoRoll.stepPrev();
    const tick4 = PianoRoll.playheadTick;

    // 6. Rewind to start returns to bar 0 (tick 0)
    PianoRoll.rewindToStart();
    const tick5 = PianoRoll.playheadTick;

    console.log(JSON.stringify({ tick1, tick2, tick3, tick4, tick5 }));
    """
    data = run_node_script(js)

    assert data["tick1"] == 16
    assert data["tick2"] == 32
    assert data["tick3"] == 32
    assert data["tick4"] == 16
    assert data["tick5"] == 0


def test_piano_roll_multi_selection_and_mass_deletion():
    """Verify multi-selection, select all, deselect, and mass deletion of selected notes."""
    js = """
    PianoRoll.model = parseAbc("X:1\\nM:4/4\\nL:1/16\\nQ:1/4=120\\nK:C\\n% intro\\nV: Vocal\\n\\"C\\"c4 d4 e4 f4 | \\"G\\"g16 |\\nV: Ins\\nz16|z16|\\n");
    PianoRoll.currentVoice = "Vocal";
    PianoRoll.clearSelection();

    const noteCountInitial = PianoRoll.model.notes.length; // 5 notes (c4, d4, e4, f4, g16)

    // 1. Select all in active voice
    PianoRoll.selectAll();
    const allSelectedCount = PianoRoll.selectedNoteIds.length;

    // 2. Clear selection
    PianoRoll.clearSelection();
    const hasSelAfterClear = PianoRoll.hasSelection();

    // 3. Select first 2 notes
    const id0 = PianoRoll.model.notes[0].id;
    const id1 = PianoRoll.model.notes[1].id;
    PianoRoll.selectNote(id0, false);
    PianoRoll.selectNote(id1, true); // add to selection
    const twoSelected = PianoRoll.selectedNoteIds.length;
    const is0Sel = PianoRoll.isNoteSelected(id0);
    const is1Sel = PianoRoll.isNoteSelected(id1);

    // 4. Delete selected notes (mass deletion)
    PianoRoll.deleteSelectedNotes();
    const countAfterDelete = PianoRoll.model.notes.length;
    const hasSelAfterDelete = PianoRoll.hasSelection();

    const outAbc = serializeToAbc(PianoRoll.model);

    console.log(JSON.stringify({
        noteCountInitial,
        allSelectedCount,
        hasSelAfterClear,
        twoSelected,
        is0Sel,
        is1Sel,
        countAfterDelete,
        hasSelAfterDelete,
        outAbc
    }));
    """
    data = run_node_script(js)

    assert data["noteCountInitial"] == 5
    assert data["allSelectedCount"] == 5
    assert data["hasSelAfterClear"] is False
    assert data["twoSelected"] == 2
    assert data["is0Sel"] is True
    assert data["is1Sel"] is True
    assert data["countAfterDelete"] == 3
    assert data["hasSelAfterDelete"] is False
    assert score.problems(data["outAbc"]) == []


def test_piano_roll_group_moving_and_gap_filling():
    """Verify selecting multiple notes and shifting them together across the timeline."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% intro\n"
        "V: Vocal\n"
        "\"C\"c4 d4 e4 f4 | \"G\"g4 a4 b4 c'4 |\n"
        "V: Ins\n"
        "z16 | z16 |\n"
    )
    js = f"""
    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.currentVoice = "Vocal";

    // Delete notes 2 and 3 (e4, f4 at ticks 8 and 12)
    const id2 = PianoRoll.model.notes[2].id;
    const id3 = PianoRoll.model.notes[3].id;
    PianoRoll.selectedNoteIds = [id2, id3];
    PianoRoll.deleteSelectedNotes();

    // Select all the notes to the right of the gap (g4, a4, b4, c'4)
    PianoRoll.selectedNoteIds = [
        PianoRoll.model.notes[2].id,
        PianoRoll.model.notes[3].id,
        PianoRoll.model.notes[4].id,
        PianoRoll.model.notes[5].id
    ];

    // Shift them left by 8 ticks to close the gap
    const shiftTicks = -8;
    for (let i = 0; i < PianoRoll.model.notes.length; i++) {{
        const n = PianoRoll.model.notes[i];
        if (PianoRoll.isNoteSelected(n.id)) {{
            n.startTick += shiftTicks;
        }}
    }}

    const newStartTicks = PianoRoll.model.notes.map(n => n.startTick);
    const outAbc = serializeToAbc(PianoRoll.model);

    console.log(JSON.stringify({{
        newStartTicks,
        outAbc
    }}));
    """
    data = run_node_script(js)

    assert data["newStartTicks"] == [0, 4, 8, 12, 16, 20]
    assert score.problems(data["outAbc"]) == []


def test_abc_lyrics_parsing_and_serialization_roundtrip():
    """Verify that ABC with w: lyric lines parses syllables onto Vocal notes and roundtrips cleanly."""
    raw_abc = (
        "X:1\n"
        "T:Lyrics Test\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% verse\n"
        "V: Vocal\n"
        "\"C\"C4 D4 E4 G4 | \"G\"G4 F4 E4 D4 | \"Am\"A4 G4 E4 D4 | \"F\"C16 |\n"
        "w: Hel- lo beau- ti- | ful morn- ing light | shin- ing so bright | _ |\n"
        "V: Ins\n"
        "\"C\"C16 | \"G\"G16 | \"Am\"A16 | \"F\"F16 |\n"
    )
    js = f"""
    const model = parseAbc({json.dumps(raw_abc)});
    const vocalNotes = model.notes.filter(n => n.voice === 'Vocal');
    const lyrics = vocalNotes.map(n => n.lyric);
    const outputAbc = serializeToAbc(model);
    const reparsed = parseAbc(outputAbc);
    const reparsedLyrics = reparsed.notes.filter(n => n.voice === 'Vocal').map(n => n.lyric);

    console.log(JSON.stringify({{
        lyrics,
        reparsedLyrics,
        outputAbc
    }}));
    """
    data = run_node_script(js)

    expected = ["Hel-", "lo", "beau-", "ti-", "ful", "morn-", "ing", "light", "shin-", "ing", "so", "bright", ""]
    assert data["lyrics"] == expected
    assert data["reparsedLyrics"] == expected
    assert "w: Hel- lo beau- ti- | ful morn- ing light | shin- ing so bright |" in data["outputAbc"]
    assert score.problems(data["outputAbc"]) == []


def test_piano_roll_edit_lyrics_and_distribution():
    """Verify editLyricForNote updates single notes or distributes multiple words across notes."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% verse\n"
        "V: Vocal\n"
        "\"C\"C4 D4 E4 G4 | \"G\"G4 F4 E4 D4 |\n"
        "V: Ins\n"
        "z16 | z16 |\n"
    )
    js = f"""
    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.currentVoice = "Vocal";
    const vocalNotes = PianoRoll.model.notes.filter(n => n.voice === 'Vocal');

    // 1. Single syllable edit
    global.window = {{ prompt: () => "Sing" }};
    PianoRoll.editLyricForNote(vocalNotes[0].id);

    // 2. Multi-syllable distribution starting at note 1
    global.window = {{ prompt: () => "to the morn- ing sun" }};
    PianoRoll.editLyricForNote(vocalNotes[1].id);

    const resultingLyrics = PianoRoll.model.notes.filter(n => n.voice === 'Vocal').map(n => n.lyric);
    const outAbc = serializeToAbc(PianoRoll.model);

    console.log(JSON.stringify({{
        resultingLyrics,
        outAbc
    }}));
    """
    data = run_node_script(js)

    assert data["resultingLyrics"][:6] == ["Sing", "to", "the", "morn-", "ing", "sun"]
    assert "w: Sing to the morn- | ing sun |" in data["outAbc"]
    assert score.problems(data["outAbc"]) == []


def test_piano_roll_match_song_lyrics():
    """Verify auto-matching song lyrics text to vocal melody notes section by section."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% verse\n"
        "V: Vocal\n"
        "\"C\"C4 D4 E4 G4 | \"G\"G4 F4 E4 D4 |\n"
        "V: Ins\n"
        "z16 | z16 |\n"
        "% chorus\n"
        "V: Vocal\n"
        "\"F\"A4 B4 c4 d4 | \"C\"e16 |\n"
        "V: Ins\n"
        "z16 | z16 |\n"
    )
    song_lyrics = (
        "[Verse]\n"
        "Walk-ing down the lone-ly ave-nue\n\n"
        "[Chorus]\n"
        "We are fly-ing high\n"
    )
    js = f"""
    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.matchSongLyrics({json.dumps(song_lyrics)});

    const verseNotes = PianoRoll.model.notes.filter(n => n.voice === 'Vocal' && n.startTick < 32);
    const chorusNotes = PianoRoll.model.notes.filter(n => n.voice === 'Vocal' && n.startTick >= 32);
    const outAbc = serializeToAbc(PianoRoll.model);

    console.log(JSON.stringify({{
        verseLyrics: verseNotes.map(n => n.lyric),
        chorusLyrics: chorusNotes.map(n => n.lyric),
        outAbc
    }}));
    """
    data = run_node_script(js)

    assert data["verseLyrics"][:6] == ["Walk-", "ing", "down", "the", "lone-", "ly"]
    assert data["chorusLyrics"][:4] == ["We", "are", "fly-", "ing"]
    assert "w: Walk- ing down the | lone- ly ave- nue |" in data["outAbc"]
    assert "w: We are fly- ing | high |" in data["outAbc"]
    assert score.problems(data["outAbc"]) == []


def test_lyrics_move_and_delete_with_notes():
    """Verify moving or deleting notes updates lyric alignment and ABC serialization."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/16\n"
        "Q:1/4=120\n"
        "K:C\n"
        "% verse\n"
        "V: Vocal\n"
        "\"C\"C4 D4 E4 G4 | \"G\"G4 F4 E4 D4 |\n"
        "w: Hel- lo beau- ti- | ful morn- ing light |\n"
        "V: Ins\n"
        "z16 | z16 |\n"
    )
    js = f"""
    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.currentVoice = "Vocal";

    // Delete note with lyric 'beau-' (3rd note, index 2)
    const delId = PianoRoll.model.notes[2].id;
    PianoRoll.deleteNote(delId);

    // Move first note from tick 0 to tick 2
    PianoRoll.model.notes[0].startTick = 2;

    const outAbc = serializeToAbc(PianoRoll.model);
    const reparsed = parseAbc(outAbc);
    const remainingLyrics = reparsed.notes.filter(n => n.voice === 'Vocal').map(n => n.lyric);

    console.log(JSON.stringify({{
        remainingLyrics,
        outAbc
    }}));
    """
    data = run_node_script(js)

    assert "beau-" not in data["remainingLyrics"]
    assert data["remainingLyrics"] == ["Hel-", "lo", "ti-", "ful", "morn-", "ing", "light"]
    assert score.problems(data["outAbc"]) == []


def test_syllable_splitting():
    """Verify rule-based syllable hyphenation splits unhyphenated English words."""
    js = """
    console.log(JSON.stringify({
        walking: splitWordSyllables("walking"),
        avenue: splitWordSyllables("avenue"),
        tonight: splitWordSyllables("tonight"),
        manual: splitWordSyllables("walk-ing"),
        dont: splitWordSyllables("don't"),
        waited: splitWordSyllables("waited"),
        walked: splitWordSyllables("walked")
    }));
    """
    data = run_node_script(js)
    assert data["walking"] == ["wal-", "king"]
    assert data["avenue"] == ["a-", "ve-", "nue"]
    assert data["tonight"] == ["to-", "night"]
    assert data["manual"] == ["walk-", "ing"]
    assert data["dont"] == ["don't"]
    assert data["waited"] == ["wai-", "ted"]
    assert data["walked"] == ["walked"]


def test_unhyphenated_lyrics_matching_expands_to_vocal_notes():
    """Verify plain unhyphenated text splits across vocal notes without leaving large gaps."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/8\n"
        "Q:1/4=120\n"
        "K:C\n"
        "V: Vocal\n"
        "C D E F | G A B c |\n"
    )
    song_lyrics = "Walking down the avenue tonight"
    js = f"""
    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.matchSongLyrics({json.dumps(song_lyrics)});
    const assigned = PianoRoll.model.notes.filter(n => n.voice === 'Vocal').map(n => n.lyric);
    console.log(JSON.stringify({{ assigned }}));
    """
    data = run_node_script(js)
    assigned = data["assigned"]
    # 8 vocal notes should all receive syllables
    assert len(assigned) == 8
    assert assigned[0] == "Wal-"
    assert assigned[1] == "king"
    assert assigned[2] == "down"
    assert assigned[3] == "the"
    assert assigned[4] == "a-"
    assert assigned[5] == "ve-"
    assert assigned[6] == "nue"
    assert assigned[7] == "to-"


def test_lyrics_footer_and_dancing_ball_dom_rendering():
    """Verify lyrics footer DOM items and real-time dancing ball/illumination updates."""
    raw_abc = (
        "X:1\n"
        "M:4/4\n"
        "L:1/8\n"
        "Q:1/4=120\n"
        "K:C\n"
        "V: Vocal\n"
        "C2 D2 E2 F2 |\n"
        "w: Hel- lo world now |\n"
    )
    js = f"""
    // Minimal DOM environment for node
    class MockClassList {{
      constructor() {{ this.classes = new Set(); }}
      add(c) {{ this.classes.add(c); }}
      remove(c) {{ this.classes.delete(c); }}
      contains(c) {{ return this.classes.has(c); }}
    }}
    class MockElement {{
      constructor(id = '', tag = 'div') {{
        this.id = id;
        this.tagName = tag;
        this.classList = new MockClassList();
        this.style = {{}};
        this.dataset = {{}};
        this.children = [];
        this.innerHTML = '';
        this.textContent = '';
      }}
      addEventListener() {{}}
      removeEventListener() {{}}
      getBoundingClientRect() {{ return {{ left: 0, top: 0, width: 400, height: 44 }}; }}
      querySelector() {{ return null; }}
      querySelectorAll() {{ return []; }}
    }}

    const elements = {{
      'roll-lyrics-footer': new MockElement('roll-lyrics-footer'),
      'roll-lyrics-strip': new MockElement('roll-lyrics-strip'),
      'roll-lyrics-items': new MockElement('roll-lyrics-items'),
      'roll-dancing-ball': new MockElement('roll-dancing-ball'),
      'roll-playhead': new MockElement('roll-playhead'),
      'roll-ruler-playhead': new MockElement('roll-ruler-playhead'),
      'roll-time': new MockElement('roll-time'),
      'roll-grid-scroll': new MockElement('roll-grid-scroll'),
    }};
    elements['roll-dancing-ball'].classList.add('hidden');

    global.document = {{
      getElementById: (id) => elements[id] || null,
      querySelector: (sel) => {{
        if (sel === '.roll-lyric-item.illuminated') return null;
        if (sel === '.roll-note.singing-now') return null;
        return null;
      }},
      querySelectorAll: () => []
    }};

    PianoRoll.model = parseAbc({json.dumps(raw_abc)});
    PianoRoll.renderLyricsFooter();

    const footerHtml = elements['roll-lyrics-items'].innerHTML;
    const hasItems = footerHtml.includes('roll-lyric-item') && footerHtml.includes('Hel-') && footerHtml.includes('world');

    // Test playhead at tick 1.5 during playback
    PianoRoll.isPlaying = true;
    PianoRoll.updatePlayhead(1.5);
    const ballHiddenDuringSinging = elements['roll-dancing-ball'].classList.contains('hidden');
    const ballTransform = elements['roll-dancing-ball'].style.transform;

    // Test stop()
    PianoRoll.stop();
    const ballHiddenAfterStop = elements['roll-dancing-ball'].classList.contains('hidden');

    console.log(JSON.stringify({{
      hasItems,
      ballHiddenDuringSinging,
      ballTransform,
      ballHiddenAfterStop
    }}));
    """
    data = run_node_script(js)
    assert data["hasItems"] is True
    assert data["ballHiddenDuringSinging"] is False
    assert "translate3d" in data["ballTransform"]
    assert data["ballHiddenAfterStop"] is True



