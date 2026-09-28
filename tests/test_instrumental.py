"""Instrumentals: the structure, the LoRA in both graphs, and the score check."""
import subprocess
import pytest

from app import config, instrumental, jobs, score
from app.db import execute, one
from app.jobs import QUEUE

from conftest import make_take

TAKE = {"id": "t", "kind": "instrumental", "style": "surf rock", "lyrics": "[instrumental]", "abc": "X:1",
        "seed": 1, "mode": "melody", "max_duration": 60}
# What the LoRA writes: a Vocal voice of rests carrying the chords, the melody in Ins.
PLAN = ("X:1\nM:4/4\nL:1/16\nV: Vocal\nV: Ins\nK:Bb\n% intro\nV: Vocal\n"
        '"Gm"z16|"Eb"z16|"Bb"z16|"F"z16|\nV: Ins\nB4B4B4Bcd2|G4G4G4GAB2|F4F4F4FED2|C4C4C4C2D2|\n')
INS_ONLY = PLAN.replace("V: Vocal\n\"Gm\"z16|\"Eb\"z16|\"Bb\"z16|\"F\"z16|\n", "").replace("B4B4", '"Gm"B4B4', 1)


def drain():
    while not QUEUE.empty():
        QUEUE.get_nowait()


def test_structures_are_normalised():
    assert instrumental.normalise("") == "[instrumental]"
    assert instrumental.normalise("[Instrumental]") == "[instrumental]"
    assert instrumental.normalise("[Intro] [verse]\n[CHORUS]") == "[intro]\n[verse]\n[chorus]"
    assert instrumental.normalise("[intro 0:00-0:15]\n[verse 0:15-0:45]") == "[intro 0:00-0:15]\n[verse 0:15-0:45]"
    assert instrumental.seconds("[intro 0:00-0:15]\n[verse 0:15-1:05]") == 65


@pytest.mark.parametrize("bad", ["[solo]", "hello", "[intro 0:00-0:15]\n[verse]", "[intro 0:00-0:15]\n[verse 0:20-0:45]",
                                 "[intro 0:15-0:10]"])
def test_bad_structures_are_refused(bad):
    with pytest.raises(ValueError):
        instrumental.normalise(bad)


def test_the_lora_goes_on_the_text_side_of_both_graphs():
    plan = jobs.build_plan_graph(TAKE)
    assert plan["20"]["class_type"] == "LoraLoader" and plan["20"]["inputs"]["lora_name"] == config.INSTRUMENTAL_LORA
    assert plan["20"]["inputs"]["strength_model"] == 0.0 and plan["2"]["inputs"]["clip"] == ["20", 1]
    render = jobs.build_render_graph(TAKE)
    assert render["11"]["inputs"]["clip"] == ["20", 1] and render["14"]["inputs"]["model"] == ["10", 0]
    assert render["11"]["inputs"]["mode"] == "full"
    song = jobs.build_render_graph({**TAKE, "kind": "song"})
    assert "20" not in song and song["11"]["inputs"]["clip"] == ["10", 1]


def test_harmony_plans_get_the_lora_too():
    plan = jobs.build_plan_graph({**TAKE, "harmony": 3})
    assert plan["2"]["class_type"] == jobs.HARMONY_NODE and plan["2"]["inputs"]["clip"] == ["20", 1]


def test_instrumental_scores_pass_on_either_voice():
    assert score.problems(PLAN, instrumental=True) == []
    assert score.problems(INS_ONLY, instrumental=True) == []
    assert "no vocal part" in score.problems(INS_ONLY)
    assert "no instrument part" in score.problems("X:1\nK:C\n", instrumental=True)


def test_the_api_creates_an_instrumental(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", False)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    assert client.post("/api/instrumentals", json={}).status_code == 400
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    assert client.post("/api/instrumentals", json={"structure": "[solo]"}).status_code == 400
    made = client.post("/api/instrumentals", json={"style": "surf rock", "structure": "[Intro] [Verse]",
                                                   "interpretation": "wide"}).json()
    row = one("SELECT * FROM takes WHERE id = ?", (made["id"],))
    assert (row["kind"], row["lyrics"], row["title"], row["interpretation"]) == ("instrumental", "[intro]\n[verse]", "Untitled instrumental", "wide")
    assert QUEUE.get_nowait() == {"kind": "plan", "id": made["id"]}
    drain()


def test_variations_of_an_instrumental_stay_instrumental(client):
    take = make_take(kind="instrumental", title="Coastal drive", lyrics="[instrumental]", abc=PLAN)
    made = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["loose"]}).json()["created"]
    assert one("SELECT kind FROM takes WHERE id = ?", (made[0]["id"],))["kind"] == "instrumental"
    drain()


def test_the_lora_is_held_at_full_strength_whatever_the_take_says():
    """The Feel control is gone: any loosening let the vocal back in at real song
    lengths.  Takes saved as "varied" render like every other one."""
    assert instrumental.FEELS == {"steady": 1.0}
    for feel in (None, "steady", "varied", "nonsense"):
        assert jobs.build_plan_graph({**TAKE, "feel": feel})["20"]["inputs"]["strength_clip"] == 1.0
        assert jobs.build_render_graph({**TAKE, "feel": feel})["20"]["inputs"]["strength_clip"] == 1.0


def test_the_api_keeps_the_feel_and_variations_copy_it(client, monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    assert client.post("/api/instrumentals", json={"feel": "wobbly"}).status_code == 400
    made = client.post("/api/instrumentals", json={"feel": "varied"}).json()
    assert one("SELECT feel FROM takes WHERE id = ?", (made["id"],))["feel"] == "varied"
    drain()
    take = make_take(kind="instrumental", title="Lemon", lyrics="[instrumental]", abc=PLAN)
    from app.db import execute
    execute("UPDATE takes SET feel = 'varied' WHERE id = ?", (take["id"],))
    copy = client.post(f"/api/takes/{take['id']}/variations", json={"interpretations": ["tight"]}).json()["created"][0]
    assert one("SELECT feel FROM takes WHERE id = ?", (copy["id"],))["feel"] == "varied"
    drain()


def test_an_old_take_saved_as_varied_is_still_accepted(client, monkeypatch):
    """A page loaded before the control was removed may still send it."""
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])
    assert client.post("/api/instrumentals", json={"feel": "varied"}).status_code == 200
    assert client.post("/api/instrumentals", json={"feel": "wobbly"}).status_code == 400
    drain()


def test_a_silent_vocal_stem_is_not_called_singing(tmp_path):
    silence = tmp_path / "quiet.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "8", str(silence)], check=True)
    assert instrumental.sung_share(silence) == 0.0


def test_a_loud_vocal_stem_is_called_singing(tmp_path):
    tone = tmp_path / "loud.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:r=16000",
                    "-t", "8", str(tone)], check=True)
    assert instrumental.sung_share(tone) > instrumental.SUNG


def test_a_short_piece_is_checked_whole(tmp_path):
    short = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:r=16000",
                    "-t", "5", str(short)], check=True)
    out = instrumental.excerpt(short, tmp_path / "out.wav")
    assert out.exists()
    assert abs(instrumental.duration_of(out) - 5) < 0.5


def test_a_long_piece_is_sampled_not_read_whole(tmp_path):
    """Nine seconds from across the piece: enough to hear singing that runs
    through it, little enough to separate in a couple of seconds."""
    long = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:r=16000",
                    "-t", "120", str(long)], check=True)
    out = instrumental.excerpt(long, tmp_path / "out.wav")
    assert 7 < instrumental.duration_of(out) < 11


def test_the_share_reads_silence_and_singing_apart():
    import numpy as np
    rate = 16000
    quiet = np.zeros(rate * 6, dtype=np.float32)
    loud = (np.sin(np.arange(rate * 6) * 0.05) * 0.5).astype(np.float32)
    half = np.concatenate([quiet[: rate * 3], loud[: rate * 3]])
    assert instrumental.share_of(quiet, rate) == 0.0
    assert instrumental.share_of(loud, rate) == 1.0
    assert 0.4 < instrumental.share_of(half, rate) < 0.6


SINGING_PLAN = PLAN.replace('"Gm"z16|"Eb"z16|"Bb"z16|"F"z16|', '"Gm"B4A4G4F4|"Eb"E8G8|"Bb"B4d4f4d4|"F"c16|')


def test_a_plan_with_a_melody_in_the_vocal_part_is_spotted():
    """Measured on seventeen takes: every plan with notes in the Vocal voice sang,
    every plan with rests alone came out clean."""
    assert instrumental.sings(PLAN) == 0
    assert instrumental.sings(SINGING_PLAN) > 0
    assert instrumental.sings(INS_ONLY) == 0
    assert instrumental.sings("") == 0


def test_chord_symbols_are_not_mistaken_for_a_melody():
    chords_only = 'X:1\nM:4/4\nL:1/16\nV: Vocal\nK:C\n% intro\nV: Vocal\n"Gm"z16|"Bbmaj7"z16|"F/A"z16|\n'
    assert instrumental.sings(chords_only) == 0


def test_the_check_can_be_quick_thrifty_or_off():
    """Holding the separator cannot be undone once loaded, so the thrifty choice
    runs a separate program rather than pretending to free memory."""
    from app.db import set_setting
    assert jobs.check_mode() == "fast"            # the default
    for mode in ("thrifty", "off", "fast"):
        set_setting("instrumental.vocal_check", mode)
        assert jobs.check_mode() == mode
    set_setting("instrumental.vocal_check", "nonsense")
    assert jobs.check_mode() == "fast"            # anything unknown is the default
    set_setting("instrumental.vocal_check", "fast")


def test_off_means_no_answer_and_no_work(tmp_path, monkeypatch):
    from app.db import set_setting
    set_setting("instrumental.vocal_check", "off")
    monkeypatch.setattr(jobs.instrumental, "excerpt", lambda *a, **k: pytest.fail("should not have looked"))
    assert jobs.singing_share(tmp_path / "nothing.flac") is None
    set_setting("instrumental.vocal_check", "fast")


# A transcription of a recording with no vocal: the Vocal voice rests under the chords,
# the melody in Ins, and the transcriber's own section names.
RECORDED = ("X:1\nM:4/4\nL:1/16\nQ:1/4=90\nV: Vocal\nV: Ins\nK:C\n"
            '% intro\nV: Vocal\n"C"z16|"G"z16|\nV: Ins\nc4e4g4e4|B4d4g4d4|\n'
            '% verse\nV: Vocal\n"Am"z16|"F"z16|\nV: Ins\nA4c4e4c4|F4A4c4A4|\n'
            '% interlude\nV: Vocal\n"C"z16|\nV: Ins\nc16|\n'
            '% silence\nV: Vocal\nz16|\nV: Ins\nz16|\n')
SUNG = RECORDED.replace('"Am"z16|"F"z16|', '"Am"A4c4e4c4|"F"z16|')


def a_recording(abc):
    from app.db import execute
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc, transcribe_state)
               VALUES('rec1', 'Harbour backing', 'harbour.flac', '/x/harbour.flac', 'sha', 1.0, ?, 'done')""", (abc,))


def engine_ready(monkeypatch):
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", [config.CHECKPOINT])


def test_a_score_gives_its_sections_in_the_names_the_lora_knows():
    """One tag per section of the score, since a render pairs the two: an interlude is
    a bridge, and a silence opens, closes or stands between."""
    assert instrumental.structure_of(RECORDED) == "[intro]\n[verse]\n[bridge]\n[outro]"
    assert instrumental.structure_of("% silence\n% pre-chorus\n% silence\n% chorus\n% coda") == \
        "[intro]\n[pre-chorus]\n[bridge]\n[chorus]\n[outro]"
    assert instrumental.structure_of("X:1\nK:C\nV: Vocal\nc|") == "[instrumental]"


def test_an_instrumental_from_a_recording_renders_its_score_at_once(client, monkeypatch):
    """No plan: the recording's transcription is the score, its sections the structure,
    and the render is queued straight away with the instrumental LoRA's kind."""
    engine_ready(monkeypatch)
    a_recording(RECORDED)
    made = client.post("/api/instrumentals", json={"source_id": "rec1", "style": "surf rock",
                                                   "structure": "[chorus]"}).json()
    row = one("SELECT * FROM takes WHERE id = ?", (made["id"],))
    assert (row["kind"], row["source_id"], row["title"]) == ("instrumental", "rec1", "Harbour backing")
    assert row["abc"] == RECORDED and row["lyrics"] == "[intro]\n[verse]\n[bridge]\n[outro]", \
        "the score's sections, whatever structure the page had"
    assert QUEUE.get_nowait() == {"kind": "render", "id": made["id"]}
    assert jobs.build_render_graph(row)["20"]["inputs"]["lora_name"] == config.INSTRUMENTAL_LORA
    edited = RECORDED.replace("% interlude", "% chorus")
    again = client.post("/api/instrumentals", json={"source_id": "rec1", "abc": edited}).json()
    assert one("SELECT lyrics FROM takes WHERE id = ?", (again["id"],))["lyrics"] == "[intro]\n[verse]\n[chorus]\n[outro]", \
        "the score the editor sends wins over the recording's"
    drain()


def test_a_recording_without_a_score_is_refused(client, monkeypatch):
    engine_ready(monkeypatch)
    a_recording("")
    refused = client.post("/api/instrumentals", json={"source_id": "rec1"})
    assert refused.status_code == 400 and "transcribe this recording first" in refused.json()["detail"]
    assert client.post("/api/instrumentals", json={"source_id": "nope"}).status_code == 404
    assert QUEUE.empty()


def test_a_sung_melody_is_played_by_an_instrument(client, monkeypatch):
    """A recording with a voice: its tune moves to Ins, so the take is kept and does not
    sing.  The score saved is the one rendered."""
    engine_ready(monkeypatch)
    a_recording(SUNG)
    made = client.post("/api/instrumentals", json={"source_id": "rec1"})
    assert made.status_code == 200, made.text
    row = one("SELECT abc FROM takes WHERE id = ?", (made.json()["id"],))
    assert instrumental.sings(row["abc"]) == 0 and row["abc"] == instrumental.tune_on_instrument(SUNG)
    drain()


def test_the_tune_moves_to_ins_only_where_ins_rests():
    abc = ('X:1\nM:4/4\nL:1/16\nQ:1/4=90\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
           'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:C\n'
           '% intro\nV: Vocal\nZ2|\nV: Ins\nc4e4g4e4|B4d4g4d4|\n'
           '% verse\nV: Vocal\n"Am"A4c4e4-e4|"F"F8z8|\nV: Ins\nZ|g16|\n'
           'V: Vocal\nM:2/4\n"C"c8|\nV: Ins\nM:2/4\nz8|\n')
    played = instrumental.tune_on_instrument(abc)
    verse = played.split("% verse\n")[1]
    assert verse.startswith('V: Vocal\n"Am"z16|"F"z16|\nV: Ins\nA4c4e4-e4|g16|'), \
        "the first bar's tune moves; where Ins already plays, the sung notes give way"
    assert 'V: Vocal\nM:2/4\n"C"z8|\nV: Ins\nM:2/4\nc8|' in verse, "a change of meter stays in both voices"
    assert "c4e4g4e4|B4d4g4d4|" in played, "an Ins voice that plays is left alone"
    assert instrumental.sings(played) == 0
    assert score.estimate(played) == score.estimate(abc), "the same bars, the same length"
    assert played.count('"') == abc.count('"'), "every chord kept"
    assert instrumental.structure_of(played) == instrumental.structure_of(abc)


def test_a_take_from_a_recording_is_not_replanned_and_rerenders_from_its_score(client, monkeypatch):
    """Replanning would write a score of its own over the recording's.  A render after an
    edit to the score takes its sections again."""
    engine_ready(monkeypatch)
    a_recording(RECORDED)
    take = make_take(kind="instrumental", source_id="rec1", lyrics="[intro]\n[verse]\n[bridge]\n[outro]",
                     abc=RECORDED.replace("% interlude", "% chorus"))
    refused = client.post(f"/api/takes/{take['id']}/replan", json={})
    assert refused.status_code == 400 and "no plan to write again" in refused.json()["detail"]
    assert client.post(f"/api/takes/{take['id']}/render", json={}).status_code == 200
    assert one("SELECT lyrics FROM takes WHERE id = ?", (take["id"],))["lyrics"] == "[intro]\n[verse]\n[chorus]\n[outro]"
    drain()
    # A melody typed into its Vocal voice is given to the instrument before the render.
    execute("UPDATE takes SET status = 'done', abc = ? WHERE id = ?", (SUNG, take["id"]))
    assert client.post(f"/api/takes/{take['id']}/render", json={}).status_code == 200
    assert instrumental.sings(one("SELECT abc FROM takes WHERE id = ?", (take["id"],))["abc"]) == 0
    drain()
