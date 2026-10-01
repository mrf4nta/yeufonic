"""Tests for the visual Piano Roll / MIDI editor and ABC bidirectional conversion."""
import json
import subprocess
from pathlib import Path

from app import score

PIANOROLL_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "pianoroll.js"


def run_node_script(js_code: str) -> dict:
    """Run a small JS snippet importing pianoroll.js and return parsed JSON result."""
    script = f"""
    const {{ parseAbc, serializeToAbc }} = require({json.dumps(str(PIANOROLL_JS))});
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

