"""A corpus's training checkpoints, listed run by run in its Edit form, and deleted
there: only its own step files, never a finished LoRA or another corpus's."""
import time

from app import loras, main
from app.db import execute


def a_corpus(name="tidewater"):
    execute("""INSERT INTO identities(id, name, trigger_word, folder, consent, created_at)
               VALUES('c1', ?, 'tide', '/x', 1, 0)""", (name,))


def lay_out(root, names, size=10):
    for name in names:
        (root / name).write_bytes(b"x" * size)
        (root / name.replace(".safetensors", ".txt")).write_text("note\n")


RUN = ["tidewater_lora.safetensors", "tidewater_lora_step50.safetensors", "tidewater_lora_step100.safetensors",
       "tidewater_lora_step1000.safetensors"]
PREVIOUS = ["tidewater_lora_20260920.safetensors", "tidewater_lora_20260920_step50.safetensors",
            "tidewater_lora_20260918_1402_step50.safetensors"]
OTHERS = ["tidewater_lora_extra_step50.safetensors", "harbour_lora_step50.safetensors"]


def test_the_checkpoints_come_run_by_run_this_one_first(client, monkeypatch, tmp_path):
    a_corpus()
    lay_out(tmp_path, RUN + PREVIOUS + OTHERS)
    monkeypatch.setattr(loras, "folder", lambda: tmp_path)
    got = client.get("/api/identities/c1/checkpoints").json()
    runs = [(run["run"], [c["step"] for c in run["checkpoints"]]) for run in got["runs"]]
    assert runs == [("", [50, 100, 1000]), ("20260920", [50]), ("20260918_1402", [50])]
    assert got["runs"][0]["label"].startswith("This run · trained ")
    assert got["runs"][1]["label"] == "Previous run · 20 Sep 2026"
    assert got["runs"][0]["checkpoints"][0]["bytes"] == 10


def test_deleting_removes_the_steps_and_their_notes_and_nothing_else(client, monkeypatch, tmp_path):
    a_corpus()
    lay_out(tmp_path, RUN + PREVIOUS + OTHERS)
    monkeypatch.setattr(loras, "folder", lambda: tmp_path)

    async def refreshed():
        return None
    monkeypatch.setattr(main.ENGINE, "refresh_options", refreshed)
    got = client.post("/api/identities/c1/checkpoints/delete",
                      json={"names": ["tidewater_lora_step50.safetensors", "tidewater_lora_20260920_step50.safetensors"]})
    assert got.status_code == 200, got.text
    assert got.json() == {"deleted": 2, "bytes": 20}
    left = sorted(path.name for path in tmp_path.glob("*.safetensors"))
    assert "tidewater_lora_step50.safetensors" not in left and "tidewater_lora_20260920_step50.safetensors" not in left
    assert not (tmp_path / "tidewater_lora_step50.txt").exists()
    assert {"tidewater_lora.safetensors", "tidewater_lora_20260920.safetensors", *OTHERS} <= set(left)


def test_a_finished_lora_or_another_corpuss_file_is_refused(client, monkeypatch, tmp_path):
    a_corpus()
    lay_out(tmp_path, RUN + OTHERS)
    monkeypatch.setattr(loras, "folder", lambda: tmp_path)
    for name in ("tidewater_lora.safetensors", "harbour_lora_step50.safetensors",
                 "tidewater_lora_extra_step50.safetensors", "../tidewater_lora_step50.safetensors"):
        got = client.post("/api/identities/c1/checkpoints/delete", json={"names": [name]})
        assert got.status_code == 400, name
    assert len(list(tmp_path.glob("*.safetensors"))) == len(RUN + OTHERS)


def test_a_corpus_that_is_training_keeps_its_checkpoints(client, monkeypatch, tmp_path):
    a_corpus()
    lay_out(tmp_path, RUN)
    monkeypatch.setattr(loras, "folder", lambda: tmp_path)
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state, started_at)
               VALUES('r1', 'c1', 'tidewater_lora', 500, 64, 'running', ?)""", (time.time(),))
    got = client.post("/api/identities/c1/checkpoints/delete", json={"names": ["tidewater_lora_step50.safetensors"]})
    assert got.status_code == 409
    assert (tmp_path / "tidewater_lora_step50.safetensors").exists()
