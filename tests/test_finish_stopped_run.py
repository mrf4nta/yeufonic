"""A training run that stopped short, by Stop, a crash or a limit, finished from what
it saved, as a finished run would: its best copy becomes the LoRA, with its
checkpoints under it, and no GPU time."""
import time

import pytest

from app import jobs, loras, main
from app.db import execute, one


@pytest.fixture
def folder(tmp_path, monkeypatch):
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)

    async def refreshed():
        return None
    monkeypatch.setattr(jobs.ENGINE, "refresh_options", refreshed)
    return root


def a_stopped_run(root, *, best=True, steps=(50, 100), state="failed", error="timed out"):
    execute("INSERT INTO identities(id, name, trigger_word, folder, consent, created_at) VALUES('c1', 'Tidewater', 'tide', '/x', 1, 0)")
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state, error, started_at, finished_at)
               VALUES('r1', 'c1', 'tidewater_lora', 1400, 64, ?, ?, ?, ?)""", (state, error, time.time() - 9000, time.time()))
    if best:
        (root / "tidewater_lora_best.safetensors").write_bytes(b"best")
    for step in steps:
        (root / f"tidewater_lora_step{step}.safetensors").write_bytes(f"step{step}".encode())


def test_the_corpus_view_says_how_the_run_ended_and_what_it_saved(client, folder):
    a_stopped_run(folder)
    run = client.get("/api/identities/c1").json()["last_run"]
    assert (run["state"], run["error"], run["steps"]) == ("failed", "timed out", 1400)
    assert run["saved"] == {"best": True, "last_step": 100, "finishable": True}


def test_finishing_makes_the_best_copy_the_lora_with_its_checkpoints_under_it(client, folder):
    a_stopped_run(folder)
    got = client.post("/api/lora-runs/r1/finish")
    assert got.status_code == 200, got.text
    assert got.json() == {"lora": "tidewater_lora.safetensors", "last_step": 100}
    assert (folder / "tidewater_lora.safetensors").read_bytes() == b"best"
    assert not (folder / "tidewater_lora_best.safetensors").exists()
    assert (folder / "tidewater_lora.txt").read_text().startswith("Tidewater")
    assert (folder / "tidewater_lora_step100.txt").read_text().startswith("Tidewater · step 100")
    assert one("SELECT lora FROM identities WHERE id = 'c1'")["lora"] == "tidewater_lora.safetensors"
    run = one("SELECT * FROM lora_runs WHERE id = 'r1'")
    assert run["state"] == "done" and run["stage"] == "finished from what it saved, after step 100 of 1400"
    assert client.get("/api/identities/c1").json()["last_run"]["stage"].startswith("finished from")


def test_without_a_best_copy_the_last_checkpoint_is_used_and_kept(client, folder):
    a_stopped_run(folder, best=False, state="cancelled", error="cancelled")
    assert client.post("/api/lora-runs/r1/finish").status_code == 200
    assert (folder / "tidewater_lora.safetensors").read_bytes() == b"step100"
    assert (folder / "tidewater_lora_step100.safetensors").is_file()


def test_nothing_saved_or_already_finished_is_refused(client, folder):
    a_stopped_run(folder, best=False, steps=())
    assert client.post("/api/lora-runs/r1/finish").status_code == 400
    execute("DELETE FROM lora_runs")
    execute("DELETE FROM identities")
    a_stopped_run(folder)
    (folder / "tidewater_lora.safetensors").write_bytes(b"a newer run")
    assert client.post("/api/lora-runs/r1/finish").status_code == 400
    assert (folder / "tidewater_lora.safetensors").read_bytes() == b"a newer run"


def test_a_finished_run_or_one_while_training_is_refused(client, folder):
    a_stopped_run(folder, state="done", error=None)
    assert client.post("/api/lora-runs/r1/finish").status_code == 409
    execute("UPDATE lora_runs SET state = 'failed'")
    execute("""INSERT INTO lora_runs(id, identity_id, lora_name, steps, rank, state, started_at)
               VALUES('r2', 'c9', 'other_lora', 500, 64, 'running', ?)""", (time.time(),))
    assert client.post("/api/lora-runs/r1/finish").status_code == 409


def test_run_all_ends_with_the_training_it_handed_over_to(client, folder):
    a_stopped_run(folder)
    main.RUN_ALL["c1"] = {"stage": "training", "since": time.time() - 10000, "left_out": [], "error": None}
    try:
        assert client.get("/api/identities/c1").json()["run_all"]["stage"] == "ended"
    finally:
        main.RUN_ALL.clear()
