"""A corpus song keeps both versions of its words, and which is in use can be switched."""
import json

from app import jobs, llm
from app.db import execute, one

WHISPER = [{"start": 5.0, "end": 8.0, "text": "fire eating the larder"}, {"start": 9.0, "end": 12.0, "text": "la la la la"}]
MODEL = [{"start": 5.0, "end": 8.0, "text": "the fiery tangle in the order"}, {"start": 9.0, "end": 12.0, "text": "na na na na"}]


def a_song(tmp_path):
    folder = tmp_path / "song"
    folder.mkdir()
    (folder / "original.flac").write_bytes(b"x")
    execute("INSERT INTO identities(id, name, trigger_word, folder, consent, created_at) VALUES('c1', 'Band', 'b', '/x', 1, 0)")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, position, stored_path,
                                          vocals_state, score_state, lyrics_state, style_state)
               VALUES('s1', 'c1', 'a.flac', 'A', 'h', 30, 1, 0, ?, 'done', 'done', 'done', 'done')""", (str(folder / "original.flac"),))
    return folder


def test_both_versions_are_kept_with_the_models_in_use(tmp_path):
    folder = a_song(tmp_path)
    found = {"lines": MODEL, "method": "gemini, timed by Whisper", "whisper": WHISPER, "llm": MODEL, "model": "gemini-3.8-flash"}
    jobs.keep_lyric_versions("s1", folder, found)
    assert json.loads((folder / "lyrics-whisper.json").read_text()) == WHISPER
    assert json.loads((folder / "lyrics-llm.json").read_text()) == MODEL
    versions = json.loads(one("SELECT lyrics_versions FROM identity_songs WHERE id = 's1'")["lyrics_versions"])
    assert versions == {"active": "llm", "whisper": {"words": 8}, "llm": {"model": "gemini-3.8-flash", "words": 10}}
    # Whisper alone keeps one file, removes any old LLM file, and says it is the one in use.
    jobs.keep_lyric_versions("s1", folder, {"lines": WHISPER, "whisper": WHISPER, "llm": None, "model": "x"})
    assert not (folder / "lyrics-llm.json").exists()
    assert json.loads(one("SELECT lyrics_versions FROM identity_songs WHERE id = 's1'")["lyrics_versions"]) == {
        "active": "whisper", "whisper": {"words": 8}}


def test_the_song_in_the_corpus_view_carries_its_versions(client, tmp_path):
    folder = a_song(tmp_path)
    jobs.keep_lyric_versions("s1", folder, {"lines": MODEL, "whisper": WHISPER, "llm": MODEL, "model": "gemini-3.8-flash"})
    song = client.get("/api/identities/c1").json()["songs"][0]
    assert song["lyrics_versions"]["active"] == "llm" and song["lyrics_versions"]["llm"]["words"] == 10


def test_switching_puts_the_other_version_in_use_and_drafts_its_words(client, tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "is_external_enabled", lambda: False)
    folder = a_song(tmp_path)
    (folder / "whisper.json").write_text(json.dumps(MODEL))
    jobs.keep_lyric_versions("s1", folder, {"lines": MODEL, "whisper": WHISPER, "llm": MODEL, "model": "gemini-3.8-flash"})
    execute("UPDATE identity_songs SET lyrics = 'my own words', lyrics_checked = 1 WHERE id = 's1'")
    url = "/api/identities/c1/songs/s1/lyrics/source"
    reply = client.post(url, json={"source": "whisper"})
    assert reply.status_code == 200 and reply.json()["active"] == "whisper"
    row = one("SELECT lyrics, lyrics_checked, lyrics_versions FROM identity_songs WHERE id = 's1'")
    assert "fire eating the larder" in row["lyrics"] and "fiery tangle" not in row["lyrics"] and row["lyrics_checked"] == 0
    assert json.loads(row["lyrics_versions"])["active"] == "whisper"
    assert json.loads((folder / "whisper.json").read_text()) == WHISPER          # the lines in use
    assert client.post(url, json={"source": "llm"}).status_code == 200
    assert "fiery tangle" in one("SELECT lyrics FROM identity_songs WHERE id = 's1'")["lyrics"]


def test_switching_says_why_it_cannot(client, tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "is_external_enabled", lambda: False)
    folder = a_song(tmp_path)
    jobs.keep_lyric_versions("s1", folder, {"lines": WHISPER, "whisper": WHISPER, "llm": None, "model": "x"})
    url = "/api/identities/c1/songs/s1/lyrics/source"
    assert client.post(url, json={"source": "llm"}).status_code == 400            # that version was not kept
    assert client.post(url, json={"source": "gemini"}).status_code == 422
    assert client.post("/api/identities/c1/songs/nope/lyrics/source", json={"source": "whisper"}).status_code == 404
    execute("UPDATE identity_songs SET lyrics_state = 'running' WHERE id = 's1'")
    assert client.post(url, json={"source": "whisper"}).status_code == 409
    execute("UPDATE identity_songs SET stored_path = NULL, lyrics_state = 'done' WHERE id = 's1'")
    assert client.post(url, json={"source": "whisper"}).status_code == 400


def test_recording_made_from_corpus_song_names_the_active_model(tmp_path):
    from app import main
    folder = a_song(tmp_path)
    (folder / "whisper.json").write_text(json.dumps(MODEL))
    jobs.keep_lyric_versions("s1", folder, {"lines": MODEL, "whisper": WHISPER, "llm": MODEL, "model": "gemini-3.8-flash"})
    song = one("SELECT * FROM identity_songs WHERE id = 's1'")
    text, method = main._corpus_song_lyrics(song, folder, "X:1\nK:C\n", 30.0)
    assert method == "gemini-3.8-flash, in the corpus analysis"

