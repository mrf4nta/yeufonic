"""An analysed corpus song as a recording: listed for the cover picker, and made a
recording in one step, with its score and words and nothing run again."""
import json
import os
import subprocess

from app import config, main
from app.db import execute, one

ABC = ('X:1\nM:4/4\nL:1/16\nQ:1/4=100\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:C\n'
       '% verse\nV: Vocal\n' + '"C"c4d4e4f4|' * 16 + '\n% chorus\nV: Vocal\n' + '"G"g4a4b4c4|' * 16 + '\n')
HEARD = [{"start": 2.0, "end": 4.0, "text": "first line here"}, {"start": 45.0, "end": 47.0, "text": "a chorus line"}]


def a_song(tmp_path, *, checked=0, lyrics="[Verse]\ndrafted words", abc=ABC, heard=True, vocals=True):
    folder = tmp_path / "identities" / "c1" / "songs" / "harbour-s1"
    folder.mkdir(parents=True)
    stored = folder / "original.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=2", str(stored)], check=True)
    (folder / "score.abc").write_text(abc)
    if heard:
        (folder / "whisper.json").write_text(json.dumps(HEARD))
    if vocals:
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", str(folder / "vocals.wav")], check=True)
    execute("INSERT INTO identities(id, name, trigger_word, folder, consent, created_at) VALUES('c1', 'Tidewater', 'tide', '/x', 1, 0)")
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, position, stored_path,
                                          vocals_state, score_state, lyrics_state, style_state, key, tempo, lyrics, lyrics_checked)
               VALUES('s1', 'c1', '/x/Harbour Lights.flac', 'Harbour Lights', 'orig', 76.8, 1, 0, ?,
                      'done', 'done', 'done', 'done', 'C major', 100, ?, ?)""", (str(stored), lyrics, checked))
    return stored


def test_analysed_songs_are_listed_by_corpus(client, tmp_path):
    a_song(tmp_path)
    got = client.get("/api/corpus-songs").json()
    assert [g["name"] for g in got] == ["Tidewater"]
    song = got[0]["songs"][0]
    assert (song["id"], song["title"], song["key"], song["tempo"], song["caveat"], song["source_id"]) == \
        ("s1", "Harbour Lights", "C major", 100, None, None)


def test_a_fallback_score_is_marked(client, tmp_path):
    a_song(tmp_path, abc=ABC.replace('"C"', '').replace('"G"', ''))
    assert client.get("/api/corpus-songs").json()[0]["songs"][0]["caveat"] == "melody only"


def test_a_song_becomes_a_recording_with_its_score_words_and_vocal(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    stored = a_song(tmp_path)
    made = client.post("/api/sources/from-corpus/s1")
    assert made.status_code == 200, made.text
    source = one("SELECT * FROM sources WHERE id = ?", (made.json()["id"],))
    assert source["title"] == "Harbour Lights" and source["abc"] == ABC and source["transcribe_state"] == "done"
    assert source["lyrics_state"] == "done" and source["lyrics_method"] == "Whisper, in the corpus analysis"
    assert source["lyrics"].startswith("[Verse]\nfirst line here") and "[Chorus]\na chorus line" in source["lyrics"], \
        "the heard lines laid under the score's own sections"
    kept = os.stat(source["stored_path"])
    assert kept.st_ino == os.stat(stored).st_ino, "linked, not copied"
    assert (tmp_path / "sources" / (os.path.basename(source["stored_path"]).rsplit(".", 1)[0] + ".vocals.flac")).is_file()
    listed = client.get("/api/corpus-songs").json()[0]["songs"][0]
    assert listed["source_id"] == source["id"]


def test_checked_words_are_kept_as_they_are(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    a_song(tmp_path, checked=1, lyrics="[Verse]\nwords someone checked")
    source = one("SELECT * FROM sources WHERE id = ?", (client.post("/api/sources/from-corpus/s1").json()["id"],))
    assert source["lyrics"] == "[Verse]\nwords someone checked" and source["lyrics_method"] == "the corpus, as checked there"


def test_the_same_song_twice_is_the_same_recording(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    a_song(tmp_path)
    first = client.post("/api/sources/from-corpus/s1").json()
    again = client.post("/api/sources/from-corpus/s1").json()
    assert again["duplicate"] and again["id"] == first["id"]
    assert one("SELECT COUNT(*) AS n FROM sources")["n"] == 1


def test_deleting_the_recording_leaves_the_corpus_song(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    stored = a_song(tmp_path)
    made = client.post("/api/sources/from-corpus/s1").json()
    assert client.delete(f"/api/sources/{made['id']}").status_code == 200
    assert stored.is_file() and (stored.parent / "score.abc").is_file()


def test_an_unanalysed_song_is_refused(client, tmp_path):
    a_song(tmp_path)
    execute("UPDATE identity_songs SET score_state = 'none'")
    assert client.post("/api/sources/from-corpus/s1").status_code == 400
    assert client.get("/api/corpus-songs").json() == []


def test_a_copied_file_is_still_known_as_added(client, tmp_path, monkeypatch):
    """When the file cannot be linked (another drive) it is copied, and the list must
    still know the song has become a recording."""
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    a_song(tmp_path)

    def no_link(src, dst):
        raise OSError("cross-device link")
    monkeypatch.setattr(main.os, "link", no_link)
    made = client.post("/api/sources/from-corpus/s1").json()
    assert os.stat(made["stored_path"]).st_nlink == 1, "a copy"
    assert client.get("/api/corpus-songs").json()[0]["songs"][0]["source_id"] == made["id"]
    assert client.post("/api/sources/from-corpus/s1").json()["id"] == made["id"]
