"""Telling a usable score from a broken one, and what the app does with a broken one."""
import asyncio

from app import jobs, score
from app.db import execute, one

from conftest import make_take

# The plan Plan variety "wild" wrote for "test1": garbled voice headers, no vocal part.
BROKEN = ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=97\nV Vocal cle"treble name="Vocal Melody" snm="Vocal"\n'
          'Vocal=treble name="Ins Melody" snm="Inst."\nK:F#\n% intro\n'
          'V: Insus2"A6A6F8z8E,2F,2|"Bmaj7/D#"C6D,8-D,,2-"G#dim"G,,16-|\n% verse\n')
GOOD = ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=97\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
        'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:Dm\n% intro\nV: Vocal\n'
        'z24z4"Dm"z4|"Dm"z32|"Dm"z32|"Bbmaj7"z32|\nV: Ins\nZ|D2F2E2F2|D,4D,4|B,,4A,4|\n'
        'V: Vocal\n"Gm"z32|"Bm7b5"z32|"C7/Bb"z16"Bm7"z16|"Bm7"z32|\n')
NO_CHORDS = GOOD.replace('"Dm"', '').replace('"Bbmaj7"', '').replace('"Gm"', '').replace('"Bm7b5"', '') \
                .replace('"C7/Bb"', '').replace('"Bm7"', '')


def test_problems():
    assert score.problems(GOOD) == []
    assert score.problems(BROKEN) == ["no vocal part"]
    assert score.problems(NO_CHORDS) == ["no chord symbols"]
    assert score.problems(NO_CHORDS, need_chords=False) == []
    assert score.problems('X:1\nV: Vocal\n"C"z8|\n') == ["no key", "only 1 bar"]
    assert "repetitive token collapse" in score.problems("Q:1::::::::::::::::::::::\nK:C\n")
    assert len(score.vocal_bars(GOOD)) == 8   # header voice lines are not bars


class PlanEngine:
    def __init__(self, abc):
        self.abc = abc
        self.last_contact = __import__("time").time()

    async def submit(self, graph):
        return "pid"

    async def history(self, pid):
        return {"status": {"status_str": "success", "completed": True},
                "prompt": [0, "pid", {"3": {"class_type": "PreviewAny"}}], "outputs": {"3": {"text": [self.abc]}}}

    def has_started(self, pid):
        return True

    async def cancel(self, pid):
        pass

    def forget(self, pid):
        pass


def plan_twice(take_id):
    """Write the plan, and then the second try an unreadable first plan asks for."""
    asyncio.run(jobs.run_job("plan", take_id))
    first = one("SELECT status, seed FROM takes WHERE id = ?", (take_id,))
    if first["status"] == "queued":
        assert jobs.QUEUE.get_nowait() == {"kind": "plan", "id": take_id}
        asyncio.run(jobs.run_job("plan", take_id))
    return first


def test_an_unreadable_plan_fails_instead_of_landing(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine(BROKEN))
    while not jobs.QUEUE.empty():   # left over from API tests
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued")
    execute("UPDATE takes SET variety = 'wild', auto_render = 1 WHERE id = ?", (take["id"],))
    first = plan_twice(take["id"])
    assert first["status"] == "queued" and first["seed"] != take["seed"]   # tried once more, new seed
    row = one("SELECT status, error, abc FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and not row["abc"]
    assert "unreadable twice (no vocal part)" in row["error"] and "calmer Plan variety" in row["error"]
    assert jobs.QUEUE.empty()   # auto-render did not queue a render
    assert take["id"] not in jobs.RETRIED_PLANS


def test_a_second_try_that_reads_well_lands(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    engine = PlanEngine(BROKEN)
    monkeypatch.setattr(jobs, "ENGINE", engine)
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued")
    asyncio.run(jobs.run_job("plan", take["id"]))
    assert jobs.QUEUE.get_nowait() == {"kind": "plan", "id": take["id"]}
    engine.abc = GOOD
    asyncio.run(jobs.run_job("plan", take["id"]))
    row = one("SELECT status, error, abc FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "planned" and row["abc"] == GOOD and not row["error"]


# A plan that reads as a score but has lost its thread: the vocal line leaps across
# six octaves and the metre lurches through bars of 1/8, and its chords are spelled
# with double sharps.
HEAD = ('X:1\nM:4/4\nL:1/8\nQ:1/4=100\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
        'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:C\n% verse\n')
SINGABLE = HEAD + 'V: Vocal\n' + '"C"c2d2e2g2|"Am"a2g2e2c2|"F"F4A4|"G"G8|' * 3 + '\nV: Ins\n' + 'C,,8|c\'\'8|' * 6 + '\n'
RUNAWAY = (HEAD + 'V: Vocal\n' + '"C"C,,2c\'\'\'2C,,2c\'\'\'2|[M:1/8]"F##dim"c|[M:9/8]"G##7"d9|[M:4/4]' * 4 +
           '"C##"c8|' * 12 + '\n')


def test_a_runaway_plan_is_caught():
    assert score.runaway(SINGABLE) == []   # a wide instrument part is not the vocal line
    assert score.problems(RUNAWAY) == []   # it reads as a score
    assert score.runaway(RUNAWAY) == ["a vocal line 6 octaves wide", "the metre changing 12 times",
                                      "20 chords with double sharps or flats"]
    # A metre that changes for a bar or two and back, as songs do, is fine.
    assert score.meter_changes(HEAD + 'V: Vocal\nc8|[M:3/4]c6|[M:4/4]c8|\n') == 2
    # An instrumental's melody is its Ins part.
    assert score.runaway(SINGABLE, instrumental=True) == ["a melody 5 octaves wide"]


def test_a_runaway_plan_is_written_once_more(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine(RUNAWAY))
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued")
    execute("UPDATE takes SET variety = 'bold' WHERE id = ?", (take["id"],))
    assert plan_twice(take["id"])["status"] == "queued"
    row = one("SELECT status, error FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and "a vocal line 6 octaves wide" in row["error"]
    assert "calmer Plan variety" in row["error"]


def test_a_broken_score_is_not_rendered(client):
    take = make_take(status="done", abc=BROKEN)
    refused = client.post(f"/api/takes/{take['id']}/render")
    assert refused.status_code == 400 and "no vocal part" in refused.json()["detail"]
    fine = make_take(status="done", abc=GOOD)
    assert client.post(f"/api/takes/{fine['id']}/render").status_code == 200


def test_instrumental_collapse_advice(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine("Q:1::::::::::::::::::::::\n"))
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued", kind="instrumental")
    execute("UPDATE takes SET style_lora_clip = 1.0, harmony = 1 WHERE id = ?", (take["id"],))
    plan_twice(take["id"])
    row = one("SELECT status, error, abc FROM takes WHERE id = ?", (take["id"],))
    assert row["status"] == "failed" and not row["abc"]
    assert "repetitive token collapse" in row["error"]
    assert "no instrument part" in row["error"]
    assert "lower style LoRA Planner strength" in row["error"]
    assert "set Harmony to Familiar" in row["error"]


def test_a_score_lasts_its_bars_in_quarter_notes():
    """The tempo counts quarter notes, so a 6/8 bar lasts three of them, not six. Read as
    six, a transcription in 6/8 described twice the music its recording held, and the
    page said its tempo was probably wrong when it was right."""
    head = 'X:1\nL:1/16\nQ:1/4=90\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:C\n'
    in_four = score.estimate(head.replace("L:", "M:4/4\nL:") + "V: Vocal\n" + "c4d4e4f4|" * 30 + "\n")
    in_six_eight = score.estimate(head.replace("L:", "M:6/8\nL:") + "V: Vocal\n" + "c4d4e4|" * 40 + "\n")
    assert in_four == {"bars": 30, "bpm": 90, "seconds": 80.0}
    assert in_six_eight == {"bars": 40, "bpm": 90, "seconds": 80.0}


def test_multi_bar_rests_and_meter_changes_count():
    """Z4 is four bars of rest, and a voice can change meter for a bar or two, as the
    transcriber writes them."""
    abc = ('X:1\nM:6/8\nL:1/32\nQ:1/4=60\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
           'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:F\n% intro\n'
           'V: Vocal\nZ4|\nV: Ins\nZ2|z24|Z|\n'
           'V: Vocal\nM:5/8\nZ|\nV: Ins\nM:5/8\nZ|\n'
           'V: Vocal\nM:6/8\n"F"z24|[M:1/8]z4|\nV: Ins\nM:6/8\nz16|[M:1/8]z4|\n')
    # Vocal: four 6/8 bars (12 quarters), one 5/8 (2.5), one 6/8 (3), one 1/8 (0.5); Ins is
    # two, one, one of 6/8, then the same, so both last 18 quarters.
    assert score.estimate(abc) == {"bars": 7, "bpm": 60, "seconds": 18.0}
