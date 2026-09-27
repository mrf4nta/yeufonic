"""Same tune, new words: a copy of a take with its score and seed, singing other words."""
import time

from app.db import execute, one

ABC = "X:1\nM:4/4\nL:1/16\nK:C\nV: Vocal\n" + "|".join(['"C"c4d4e4f4'] * 8) + "|\n"


def a_take(**extra):
    row = {"id": "orig1", "kind": "song", "title": "good1", "style": "pop", "lyrics": "[verse]\nla la",
           "abc": ABC, "mode": "full", "seed": 1747519420, "checkpoint": "x", "status": "done",
           "created_at": time.time(), "max_duration": 120, "interpretation": "tight", "variety": "calm",
           "style_lora": "harbour_lights_lora.safetensors", "style_lora_model": 0.7, "style_lora_clip": 0.7,
           "favourite": 1, "audio_path": "/data/takes/x.flac", "loudness": -15.0, "sound_seed": 999}
    row.update(extra)
    cols = list(row)
    execute(f"INSERT INTO takes({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [row[c] for c in cols])
    return row


def test_new_words_sing_the_same_score_with_the_same_seed(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take()
    made = client.post("/api/takes/orig1/words", json={"lyrics": "[verse]\r\nda da", "title": "good1"})
    assert made.status_code == 200, made.text
    copy = one("SELECT * FROM takes WHERE id = ?", (made.json()["id"],))
    assert copy["title"] == "good1 · new words", "an unchanged title is marked"
    assert copy["lyrics"] == "[verse]\nda da"
    assert copy["abc"] == ABC, "the same score"
    assert copy["seed"] == 1747519420 and copy["sound_seed"] == 999, "the same seeds"
    assert copy["interpretation"] == "tight" and copy["style_lora_clip"] == 0.7 and copy["max_duration"] == 120
    assert copy["status"] == "queued" and copy["audio_path"] is None and not copy["favourite"]
    original = one("SELECT * FROM takes WHERE id = 'orig1'")
    assert original["lyrics"] == "[verse]\nla la" and original["status"] == "done", "the original is untouched"


def test_new_words_take_a_new_title_and_the_edited_score(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take()
    edited = ABC.replace('"C"', '"F"')
    made = client.post("/api/takes/orig1/words", json={"lyrics": "[verse]\nda", "title": " good2 ",
                                                        "abc": edited, "interpretation": "loose"})
    copy = one("SELECT * FROM takes WHERE id = ?", (made.json()["id"],))
    assert copy["title"] == "good2" and copy["abc"] == edited and copy["interpretation"] == "loose"
    assert one("SELECT abc FROM takes WHERE id = 'orig1'")["abc"] == ABC


def test_a_new_seed_lets_the_sound_follow_it(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take()
    made = client.post("/api/takes/orig1/words", json={"lyrics": "[verse]\nda", "seed": 5})
    copy = one("SELECT * FROM takes WHERE id = ?", (made.json()["id"],))
    assert copy["seed"] == 5 and copy["sound_seed"] is None


def test_new_words_need_words_a_score_and_a_song(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_checkpoint", lambda: "x")
    a_take()
    assert client.post("/api/takes/orig1/words", json={"lyrics": "  \n"}).status_code == 400
    execute("UPDATE takes SET abc = '' WHERE id = 'orig1'")
    assert client.post("/api/takes/orig1/words", json={"lyrics": "la"}).status_code == 400
    execute("UPDATE takes SET abc = ?, kind = 'instrumental' WHERE id = 'orig1'", (ABC,))
    assert client.post("/api/takes/orig1/words", json={"lyrics": "la"}).status_code == 400
    assert client.post("/api/takes/nope/words", json={"lyrics": "la"}).status_code == 404
