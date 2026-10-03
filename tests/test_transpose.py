"""A written plan moved to another key.  The planner ignores a key in the style, so the key
lock moves the finished plan.  The music below was checked by hand, and the same move was
checked against abcjs on every plan in a library (350,000 notes, all but three plans' ties)."""
import asyncio

from app import jobs, transpose
from app.db import execute, one

from conftest import make_take
from test_score import GOOD, PlanEngine


def lines(abc, starting):
    return [line for line in abc.split("\n") if line.startswith(starting)]


def test_a_plan_in_d_minor_becomes_the_same_music_in_f_minor():
    moved = transpose.to_key(GOOD, "Fm")
    assert lines(moved, "K:") == ["K:Fm"]
    # up three semitones: the melody (d f a), the second voice, and the chord symbols, slash chords too
    assert '"Fm"f8a8c\'8z8|' in moved                        # A flat and C, under the new signature
    assert "Z|F2A2G2A2|F,4F,4|D,4C4|" in moved               # B flat two octaves down became D flat
    assert '"Dbmaj7"' in moved and '"Bbm"' in moved and '"Dm7b5"' in moved and '"Eb7/Db"' in moved
    assert '"Dm"' not in moved


def test_a_move_changes_only_notes_chords_and_the_key():
    moved = transpose.to_key(GOOD, "Fm")
    before, after = GOOD.split("\n"), moved.split("\n")
    assert len(before) == len(after)
    for a, b in zip(before, after):
        if a.startswith(("K:", "V: Vocal\n")) or '"' in a or a[:2] in ("Z|", "z2", "V:"):
            continue
        assert a == b                                          # headers, voices, comments: untouched
    assert lines(moved, "Q:") == lines(GOOD, "Q:") and lines(moved, "M:") == lines(GOOD, "M:")


def test_the_plans_mode_is_kept_and_only_the_tonic_moves():
    assert lines(transpose.to_key(GOOD, "F"), "K:") == ["K:Fm"]           # a minor plan asked for F stays minor
    major = GOOD.replace("K:Dm", "K:D")
    assert lines(transpose.to_key(major, "Fm"), "K:") == ["K:F"]           # and a major one stays major


def test_the_shortest_way_and_the_lighter_signature():
    assert transpose.to_key(GOOD, "Dm") == GOOD                              # already there: untouched
    up = transpose.to_key(GOOD.replace("K:Dm", "K:Am"), "Em")                # a fifth up or a fourth down: the fourth
    assert '"Em"' not in up and lines(up, "K:") == ["K:Em"]
    # G# minor has five sharps where Ab minor has seven, so the lighter one is written
    assert lines(transpose.to_key(GOOD, "Abm"), "K:") == ["K:G#m"]
    assert lines(transpose.to_key(GOOD, "Bbm"), "K:") == ["K:Bbm"]
    assert lines(transpose.to_key(GOOD, "F#m"), "K:") == ["K:F#m"]
    assert lines(transpose.to_key(GOOD, "Gbm"), "K:") == ["K:F#m"]           # a tie (six either way): the same


def test_keys_are_read_as_the_page_writes_them_and_as_abc_does():
    assert transpose.read_key("F#m") == (6, True) and transpose.read_key("Bb") == (10, False)
    assert transpose.read_key("C#min") == (1, True) and transpose.read_key("Gmajor") == (7, False)
    assert transpose.read_key("D dor") is None and transpose.read_key("H") is None
    assert transpose.plan_key("K:Bb clef=treble\n") == (10, False, -2)
    assert transpose.plan_key("K:D min\n") == (2, True, -1)
    assert transpose.plan_key("K:C#\n") == (1, False, 7) and transpose.plan_key("K:Db\n") == (1, False, -5)


def test_a_score_it_cannot_be_sure_of_is_left_alone():
    assert transpose.to_key(GOOD.replace("K:Dm", "K:D dor"), "Fm") is None                  # a mode
    assert transpose.to_key(GOOD + "K:G\n", "Fm") is None                                   # a second key
    assert transpose.to_key(GOOD.replace("L:1/32", "L:1/32\n[K:G]"), "Fm") is None          # a change inside the music
    assert transpose.to_key("X:1\nL:1/8\nV: Vocal\n|c8|\n", "Fm") is None                   # no key at all
    assert transpose.to_key(GOOD, "") is None and transpose.to_key(GOOD, "nonsense") is None


def test_accidentals_follow_the_bar_and_are_spelled_for_the_new_key():
    plan = "X:1\nL:1/8\nM:4/4\nK:Dm\nV: Vocal\n\"Dm\"D2 F2 A2 ^c2|\"Gm/Bb\"B,2 =B2 c'2 _e2|\"A7\"E2 ^G2 c2 ^c2|\nw: la la la\n% a note\n"
    up = transpose.to_key(plan, "Fm")
    assert up.split("\n")[5] == "\"Fm\"F2 A2 c2 =e2|\"Bbm/Db\"D2 =d2 e'2 _g2|\"C7\"G2 =B2 e2 =e2|"
    assert "w: la la la" in up and "% a note" in up                                         # words and comments are not notes
    down = transpose.to_key(plan, "Am")                                                     # a fourth down: no signature at all
    assert down.split("\n")[5] == "\"Am\"A,2 C2 E2 ^G2|\"Dm/F\"F,2 ^F2 g2 ^A2|\"E7\"B,2 ^D2 G2 ^G2|"


def test_a_tie_across_a_barline_is_read_the_way_abcjs_reads_it():
    """abcjs drops the accidental of a note that continues a tie across a barline, so the notes
    after it in that bar take the key signature.  Checked against abcjs: the original sounds
    D natural then D sharp (74, 75) and the move sounds B natural then C (71, 72)."""
    moved = transpose.to_key("X:1\nL:1/8\nM:4/4\nK:E\n=d2-|=d6 d2|", "Db")
    assert moved == "X:1\nL:1/8\nM:4/4\nK:Db\n=B2-|=B6 c2|"


def test_a_plan_job_stores_the_plan_in_the_locked_key(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: real_sleep(0))
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine(GOOD))                     # the planner wrote D minor
    while not jobs.QUEUE.empty():
        jobs.QUEUE.get_nowait()
    take = make_take(status="queued")
    execute("UPDATE takes SET target_key = 'Fm', target_bpm = 80 WHERE id = ?", (take["id"],))
    asyncio.run(jobs.run_job("plan", take["id"]))
    stored = one("SELECT status, abc FROM takes WHERE id = ?", (take["id"],))
    assert stored["status"] == "planned" and "K:Fm" in stored["abc"] and "Q:1/4=80" in stored["abc"]
    assert '"Fm"' in stored["abc"] and '"Dm"' not in stored["abc"]
    # a key it cannot move leaves the planner's own, and the take still lands
    monkeypatch.setattr(jobs, "ENGINE", PlanEngine(GOOD.replace("K:Dm", "K:D dor")))
    other = make_take(status="queued")
    execute("UPDATE takes SET target_key = 'Fm' WHERE id = ?", (other["id"],))
    asyncio.run(jobs.run_job("plan", other["id"]))
    kept = one("SELECT status, abc FROM takes WHERE id = ?", (other["id"],))
    assert kept["status"] == "planned" and "K:D dor" in kept["abc"]


def test_rendering_a_plan_moves_the_score_you_see_to_the_locks(client):
    made = client.post("/api/songs", json={"title": "K", "style": "rock", "lyrics": "[Verse]\nla"}).json()
    execute("UPDATE takes SET status = 'planned', abc = ? WHERE id = ?", (GOOD, made["id"]))
    reply = client.post(f"/api/takes/{made['id']}/render", json={"target_key": "F#m", "target_bpm": 70})
    assert reply.status_code == 200, reply.text
    stored = one("SELECT abc FROM takes WHERE id = ?", (made["id"],))["abc"]
    assert "K:F#m" in stored and "Q:1/4=70" in stored and '"F#m"' in stored
    execute("UPDATE takes SET status = 'planned' WHERE id = ?", (made["id"],))
    client.post(f"/api/takes/{made['id']}/render", json={"seed": 5})                     # said nothing: the lock stays
    assert "K:F#m" in one("SELECT abc FROM takes WHERE id = ?", (made["id"],))["abc"]


def test_a_cover_is_stored_at_the_locked_tempo_and_key(client):
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc)
               VALUES('src-lock', 'S', 's.mid', '/nowhere', 'x', 0, ?)""", (GOOD,))
    made = client.post("/api/takes", json={"source_id": "src-lock", "target_bpm": 74, "target_key": "Fm"})
    assert made.status_code == 200, made.text
    stored = one("SELECT abc FROM takes WHERE id = ?", (made.json()["id"],))["abc"]
    assert "Q:1/4=74" in stored and "K:Fm" in stored and '"Dm"' not in stored
    plain = client.post("/api/takes", json={"source_id": "src-lock"}).json()
    assert one("SELECT abc FROM takes WHERE id = ?", (plain["id"],))["abc"] == GOOD
