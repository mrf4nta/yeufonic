"""The Storage window: what it measures, what it offers to remove, what it refuses, and the two
automatic tidyings."""
import os
import time

import pytest

from app import config, jobs, storage
from app.db import execute, one, set_setting


def _file(path, size=1000, age=3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    past = time.time() - age
    os.utime(path, (past, past))
    return path


@pytest.fixture
def library(client, tmp_path, monkeypatch):
    """A corpus with its originals, working copies and a training set, an engine input folder, and LoRA files."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "ENGINE_INPUT_DIR", tmp_path / "engine-input")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    (tmp_path / "models" / "loras").mkdir(parents=True)
    (tmp_path / "engine-input").mkdir()
    execute("DELETE FROM identities")
    execute("""INSERT INTO identities(id, name, trigger_word, description, voice, folder, consent, created_at)
               VALUES('c1', 'Invented Corpus', 'inv', '', '', '', 1, 0)""")
    song = tmp_path / "data" / "identities" / "c1" / "songs" / "song-a"
    _file(song / "original.mp3", 9000)
    _file(song / "vocals.wav", 5000)
    _file(song / "engine-copy.mp3", 8000)
    _file(song / "engine-copy-ended.flac", 6000)
    _file(song / "style-clip.wav", 700)
    _file(song / "score.abc", 50)
    _file(tmp_path / "data" / "identities" / "c1" / "dataset" / "a.flac", 40000)
    _file(tmp_path / "data" / "identities" / "c1" / "dataset" / "a.txt", 20)
    _file(tmp_path / "engine-input" / "identity-abc123-engine-copy-ended.flac", 3000)
    _file(tmp_path / "engine-input" / "someones-own-file.wav", 2000)                     # not ours
    _file(tmp_path / "models" / "loras" / "invented_corpus_lora.safetensors", 7000)
    _file(tmp_path / "models" / "loras" / "invented_corpus_lora_step50.safetensors", 7000)
    _file(tmp_path / "models" / "loras" / "invented_corpus_lora_step100.safetensors", 7000)
    return tmp_path


def base(identity):
    return "invented_corpus_lora"


def by_id(report):
    return {i["id"]: i for i in report["items"]}


def test_it_lists_what_can_be_given_back_with_what_it_costs(library):
    report = storage.scan(storage.Busy(), base)
    found = by_id(report)
    assert found["working-copies"]["bytes"] == 8000 + 6000 + 700 and found["working-copies"]["files"] == 3
    assert found["engine-uploads"]["bytes"] == 3000                                      # only ours
    assert found["training-set:c1"]["bytes"] == 40020
    assert found["checkpoints:c1"]["bytes"] == 14000 and found["checkpoints:c1"]["files"] == 2
    for item in found.values():
        assert item["what"] and item["consequence"] and item["blocked"] is None
    assert report["reclaimable"] == 14700 + 3000 + 40020 + 14000 + 5000 // 2          # the vocals count as half


def test_the_originals_the_vocals_the_scores_and_the_finished_lora_are_never_offered(library):
    for item in storage.items(storage.Busy(), base):
        if item.get("kind") == "compress":
            continue                                # offered for conversion, never for removal
        for path in item.get("_paths", []):
            assert path.name not in ("original.mp3", "vocals.wav", "score.abc")
        assert "invented_corpus_lora.safetensors" not in item.get("_names", [])


def test_removing_an_item_removes_those_files_and_only_those(library):
    result = storage.reclaim(["working-copies", "engine-uploads"], storage.Busy(), base)
    assert result["freed"] == 14700 + 3000 and not result["skipped"]
    song = library / "data" / "identities" / "c1" / "songs" / "song-a"
    assert (song / "original.mp3").exists() and (song / "vocals.wav").exists() and (song / "score.abc").exists()
    assert not (song / "engine-copy.mp3").exists() and not (song / "style-clip.wav").exists()
    assert (library / "engine-input" / "someones-own-file.wav").exists()                # not ours: untouched
    assert (library / "data" / "identities" / "c1" / "dataset" / "a.flac").exists()


def test_removing_a_training_set_says_the_corpus_has_none_written(library):
    execute("UPDATE identities SET exported_at = 5, export_dir = 'x' WHERE id = 'c1'")
    storage.reclaim(["training-set:c1"], storage.Busy(), base)
    assert not (library / "data" / "identities" / "c1" / "dataset").exists()
    row = one("SELECT exported_at, export_dir FROM identities WHERE id = 'c1'")
    assert row["exported_at"] is None and row["export_dir"] is None


def test_checkpoints_go_but_the_finished_lora_stays(library):
    storage.reclaim(["checkpoints:c1"], storage.Busy(), base)
    loras = library / "models" / "loras"
    assert (loras / "invented_corpus_lora.safetensors").exists()
    assert not list(loras.glob("*_step*.safetensors"))


def test_a_corpus_in_use_is_listed_but_refused(library):
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state)
               VALUES('r1', 'c1', 'invented_corpus_lora', 100, 8, 'running')""")
    busy = storage.Busy()
    found = by_id(storage.scan(busy, base))
    assert "training" in found["training-set:c1"]["blocked"] and "training" in found["checkpoints:c1"]["blocked"]
    result = storage.reclaim(["training-set:c1", "working-copies"], busy, base)
    assert result["freed"] == 0 and len(result["skipped"]) == 2
    assert (library / "data" / "identities" / "c1" / "dataset" / "a.flac").exists()


def test_a_set_being_written_is_refused(library):
    result = storage.reclaim(["training-set:c1"], storage.Busy(exporting={"c1"}), base)
    assert result["freed"] == 0 and "written" in result["skipped"][0]["reason"]


def test_a_file_that_may_still_be_in_use_is_left_alone(library):
    fresh = _file(library / "engine-input" / "identity-fff-engine-copy-ended.flac", 500, age=5)
    storage.reclaim(["engine-uploads"], storage.Busy(), base)
    assert fresh.exists()


def test_unknown_and_vanished_items_are_reported_not_errors(library):
    result = storage.reclaim(["no-such-thing", "training-set:nope"], storage.Busy(), base)
    assert result["freed"] == 0 and len(result["skipped"]) == 2


def test_the_page_can_ask_and_remove(client, library):
    report = client.get("/api/storage").json()
    assert report["items"] and report["areas"] and report["corpora"][0]["name"] == "Invented Corpus"
    reply = client.post("/api/storage/reclaim", json={"ids": ["working-copies"]}).json()
    assert reply["freed"] == 14700


def test_the_working_copies_are_dropped_after_a_job_unless_kept(library):
    song = library / "data" / "identities" / "c1" / "songs" / "song-a"
    _file(library / "engine-input" / "identity-sg1-style.wav", 400)
    assert storage.drop_working_copies(song, "sg1") == 8000 + 6000 + 700 + 400
    assert (song / "original.mp3").exists() and not (song / "engine-copy.mp3").exists()
    assert (library / "engine-input" / "someones-own-file.wav").exists()


def test_the_training_set_and_the_engines_copy_go_when_asked(library):
    staged = _file(library / "engine-input" / "lora-0123456789ab" / "a.flac", 900)
    storage.drop_training_set("c1", "0123456789ab")
    assert not (library / "data" / "identities" / "c1" / "dataset").exists() and not staged.exists()


def test_the_new_settings_have_the_defaults_that_were_chosen(client):
    from app.main import setting_value
    assert setting_value("storage.working_copies") == "remove"        # nothing reads them again
    assert setting_value("storage.training_set") == "keep"            # removing one costs an Export
    assert setting_value("training.checkpoints") == "keep"


# ------------------------------------------------------------------ vocals: WAV to FLAC
import subprocess

from app import identities


def _tone(path, seconds=1.0, freq=440):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}",
                    "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def test_a_song_vocal_is_found_whether_it_is_flac_or_the_older_wav(tmp_path):
    assert identities.vocals_file(tmp_path) is None
    _file(tmp_path / "vocals.wav", 10)
    assert identities.vocals_file(tmp_path).name == "vocals.wav"
    _file(tmp_path / "vocals.flac", 10)
    assert identities.vocals_file(tmp_path).name == "vocals.flac"          # the newer wins


def test_the_vocal_is_served_in_either_format(client, library):
    song = library / "data" / "identities" / "c1" / "songs" / "song-a"
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, vocals_state, stored_path, position)
               VALUES('s1', 'c1', 'a.mp3', 'A', 'x', 30, 1, 'done', ?, 0)""", (str(song / "original.mp3"),))
    assert client.get("/api/identities/c1/songs/s1/audio?which=vocals").status_code == 200        # the WAV
    (song / "vocals.wav").unlink()
    assert client.get("/api/identities/c1/songs/s1/audio?which=vocals").status_code == 404
    _file(song / "vocals.flac", 40)
    assert client.get("/api/identities/c1/songs/s1/audio?which=vocals").status_code == 200        # the FLAC


def test_the_wavs_are_offered_for_conversion_not_for_plain_removal(library):
    found = by_id(storage.scan(storage.Busy(), base))
    assert found["vocals-flac"]["kind"] == "compress" and found["vocals-flac"]["files"] == 1
    result = storage.reclaim(["vocals-flac"], storage.Busy(), base)
    assert result["freed"] == 0 and "own button" in result["skipped"][0]["reason"]
    assert (library / "data" / "identities" / "c1" / "songs" / "song-a" / "vocals.wav").exists()


def test_a_wav_becomes_a_flac_that_decodes_to_the_same_audio(tmp_path):
    wav = _tone(tmp_path / "vocals.wav", 2.0)
    before = wav.stat().st_size
    saved = storage._convert_vocal(wav)
    assert saved is not None and saved > 0
    flac = tmp_path / "vocals.flac"
    assert flac.exists() and not wav.exists() and not (tmp_path / "vocals.flac.part").exists()
    assert flac.stat().st_size < before
    assert storage._decoded_md5(flac) is not None


def test_a_conversion_that_does_not_check_out_keeps_the_wav(tmp_path, monkeypatch):
    wav = _tone(tmp_path / "vocals.wav")
    monkeypatch.setattr(storage, "_decoded_md5", lambda p: "a" * 32 if p.suffix == ".wav" else "b" * 32)
    assert storage._convert_vocal(wav) is None
    assert wav.exists() and not (tmp_path / "vocals.flac").exists() and not (tmp_path / "vocals.flac.part").exists()


def test_an_existing_flac_that_differs_is_not_trusted(tmp_path):
    wav = _tone(tmp_path / "vocals.wav", 1.0, 440)
    _tone(tmp_path / "other.wav", 1.0, 880)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp_path / "other.wav"), str(tmp_path / "vocals.flac")], check=True)
    assert storage._convert_vocal(wav) is None and wav.exists()


def test_converting_all_of_them_reports_progress_and_can_stop(library):
    songs = library / "data" / "identities" / "c1" / "songs"
    for name in ("song-a", "song-b", "song-c"):
        (songs / name).mkdir(exist_ok=True)
        _tone(songs / name / "vocals.wav", 0.5)
    assert storage.begin_compress() and not storage.begin_compress()                  # only one at a time
    storage.compress_vocals()
    state = storage.compress_state()
    assert state["state"] == "done" and state["done"] == 3 and state["kept"] == 0 and state["saved"] > 0
    assert not list(songs.glob("*/vocals.wav")) and len(list(songs.glob("*/vocals.flac"))) == 3
    assert storage.begin_compress()                                                    # a second run has nothing to do
    storage.stop_compress()
    storage.compress_vocals()
    assert storage.compress_state()["state"] in ("stopped", "done")


def test_the_route_refuses_while_songs_are_being_analysed(client, library):
    execute("""INSERT INTO identity_songs(id, identity_id, file, title, sha256, duration, include, score_state, position)
               VALUES('s9', 'c1', 'b.mp3', 'B', 'x', 30, 1, 'running', 1)""")
    assert client.post("/api/storage/compress-vocals").status_code == 409
    assert client.get("/api/storage/compress-vocals").json()["state"] in ("idle", "done", "stopped", "failed")
