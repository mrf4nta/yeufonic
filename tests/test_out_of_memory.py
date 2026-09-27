"""Running out of GPU memory is said in plain words: when the engine reports it, when
it logged it and then lost the job, and a lost job says the engine stopped."""
import asyncio
import time

import pytest

from app import jobs
from app.db import one
from app.engine import Engine

from conftest import make_take
from test_jobs import PLAN_GRAPH, REAL_SLEEP, FakeEngine, done, use


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda _s: REAL_SLEEP(0))
    jobs.CANCELLED.clear()
    jobs.CURRENT.clear()


def oom_report(graph):
    job = done({}, graph, status="error")
    job["status"]["messages"] = [["execution_error", {
        "node_type": "YuE2GenerateABC", "exception_type": "torch.AcceleratorError",
        "exception_message": "CUDA error: out of memory\nSearch for `cudaErrorMemoryAllocation'"}]]
    return job


def test_an_out_of_memory_report_is_said_plainly(monkeypatch):
    take = make_take(status="queued")
    use(monkeypatch, FakeEngine([oom_report(PLAN_GRAPH)]))
    asyncio.run(jobs.run_job("plan", take["id"]))
    error = one("SELECT error FROM takes WHERE id = ?", (take["id"],))["error"]
    assert error.startswith("the GPU ran out of memory.") and "length cap" in error


def test_other_engine_errors_keep_their_detail(monkeypatch):
    take = make_take(status="queued")
    use(monkeypatch, FakeEngine([done({}, PLAN_GRAPH, status="error")]))
    asyncio.run(jobs.run_job("plan", take["id"]))
    assert "engine reported error" in one("SELECT error FROM takes WHERE id = ?", (take["id"],))["error"]


def test_a_job_lost_after_the_engine_logged_running_out_says_so(monkeypatch):
    take = make_take(status="queued")
    engine = use(monkeypatch, FakeEngine([], started=True, state="gone"))
    engine.oom_at, engine.offline_at = time.time() + 1, time.time() + 1
    asyncio.run(jobs.run_job("plan", take["id"]))
    assert one("SELECT error FROM takes WHERE id = ?", (take["id"],))["error"].startswith("the GPU ran out of memory.")


def test_a_job_lost_when_the_engine_stopped_says_so(monkeypatch):
    take = make_take(status="queued")
    engine = use(monkeypatch, FakeEngine([], started=True, state="gone"))
    engine.oom_at, engine.offline_at = time.time() - 60, time.time() + 1
    asyncio.run(jobs.run_job("plan", take["id"]))
    assert "the engine stopped during this job" in one("SELECT error FROM takes WHERE id = ?", (take["id"],))["error"]


def test_training_lost_to_running_out_gets_the_training_hint(monkeypatch):
    engine = use(monkeypatch, FakeEngine([], started=True, state="gone"))
    engine.oom_at = time.time() + 1
    with pytest.raises(RuntimeError, match="ran out of memory.*longest songs"):
        asyncio.run(jobs._run_graph("train", "run1", {}))


def test_the_engine_notes_running_out_but_not_a_retry_it_recovers_from():
    engine = Engine("http://127.0.0.1:1")
    engine._ingest_engine_entries([{"t": "1", "m": "Warning: Ran out of memory when regular VAE encoding, "
                                                  "retrying with tiled VAE encoding."}])
    assert engine.oom_at == 0
    engine._ingest_engine_entries([{"t": "2", "m": "!!! Exception during processing !!! CUDA error: out of memory"}])
    assert engine.oom_at > 0
