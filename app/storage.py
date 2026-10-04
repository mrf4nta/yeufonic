"""What is taking room on disk, and what can be given back.

The Storage window in Settings is built on this.  Two kinds of answer:

* **Areas**: where the space is, all of it, for reading only.
* **Reclaimable items**: files the app made along the way and can make again, each with what it is
  and what removing it costs, so the person decides.  Nothing here is removed until it is asked for by
  name, and a thing that is in use at that moment (a corpus being analysed, exported or trained) is
  listed but refused.

Only files this app made are ever removed, and only inside the folders it owns.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from . import config, loras
from .db import execute, rows
from .library import inside, remove_tree

log = logging.getLogger("yue2.storage")

# A file younger than this may still be being written or read, so it is left alone.
MIN_AGE = 600

# The working copies a corpus song gets while it is analysed (see jobs.py), and nothing else.
WORKING_COPY = re.compile(r"^(engine-copy.*|style-clip\.wav)$")
# What the app uploads to the engine for a corpus song.
UPLOAD = re.compile(r"^identity-[0-9a-f]+-.+$")
# The folder a training run stages its set in, inside the engine's input folder.
STAGED = re.compile(r"^lora-([0-9a-f]{12})$")


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def tree(path: Path | None) -> tuple[int, int]:
    """(bytes, files) under a path, not following links; a path that is not there is nothing."""
    if path is None or not path.exists():
        return 0, 0
    if path.is_file():
        return path.stat().st_size, 1
    total = files = 0
    stack = [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


def _sum(paths: list[Path]) -> tuple[int, int]:
    size = 0
    for path in paths:
        try:
            size += path.stat().st_size
        except OSError:
            pass
    return size, len(paths)


class Busy:
    """What is running right now that a removal must not pull the files out from under."""

    def __init__(self, exporting: set[str] | None = None) -> None:
        self.exporting = set(exporting or ())
        self.training = {r["identity_id"] for r in rows(
            "SELECT identity_id FROM lora_runs WHERE state IN ('queued', 'running')")}
        self.analysing = bool(rows(
            """SELECT 1 FROM identity_songs WHERE score_state IN ('queued', 'running')
               OR style_state IN ('queued', 'running') OR vocals_state IN ('queued', 'running')
               OR lyrics_state IN ('queued', 'running') LIMIT 1"""))

    def corpus(self, identity_id: str) -> str | None:
        if identity_id in self.training:
            return "it is training now"
        if identity_id in self.exporting:
            return "its training set is being written now"
        return None

    def anywhere(self) -> str | None:
        if self.training:
            return "a LoRA is training"
        if self.analysing:
            return "songs are being analysed"
        return None


def _corpus_dir(identity_id: str) -> Path:
    return config.DATA_DIR / "identities" / identity_id


def _working_copy_paths() -> list[Path]:
    found: list[Path] = []
    root = config.DATA_DIR / "identities"
    if not root.is_dir():
        return found
    for identity in root.iterdir():
        songs = identity / "songs"
        if not songs.is_dir():
            continue
        for song in songs.iterdir():
            if not song.is_dir():
                continue
            found.extend(p for p in song.iterdir() if p.is_file() and WORKING_COPY.match(p.name))
    return found


def _old_enough(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime > MIN_AGE
    except OSError:
        return False


def _engine_uploads() -> list[Path]:
    root = config.ENGINE_INPUT_DIR
    if not root or not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_file() and UPLOAD.match(p.name) and _old_enough(p)]


def _staged_training_copies() -> list[Path]:
    """The engine's copies of training sets for runs that have ended."""
    root = config.ENGINE_INPUT_DIR
    if not root or not root.is_dir():
        return []
    ended = {r["id"] for r in rows("SELECT id FROM lora_runs WHERE state NOT IN ('queued', 'running')")}
    found = []
    for p in root.iterdir():
        match = STAGED.match(p.name)
        if p.is_dir() and match and match.group(1) in ended and _old_enough(p):
            found.append(p)
    return found


def items(busy: Busy, lora_base: Callable[[dict], str]) -> list[dict]:
    """Everything that could be given back, with what it is and what it costs.  Each carries its
    paths (under "_paths") for the removal; the page never sees those."""
    out: list[dict] = []

    paths = _working_copy_paths()
    size, count = _sum(paths)
    if count:
        out.append({
            "id": "working-copies", "title": "Working copies made while analysing songs",
            "bytes": size, "files": count, "_paths": paths, "blocked": busy.anywhere(),
            "what": "To analyse a song, Yeufonic makes copies for the engine to read: the song with its tags "
                    "stripped, a padded copy for the transcriber, and a short clip for describing its style. "
                    "Nothing reads them again once the analysis has finished.",
            "consequence": "Nothing you will notice. If a song is analysed again, they are made again.",
        })

    paths = _engine_uploads()
    size, count = _sum(paths)
    if count:
        out.append({
            "id": "engine-uploads", "title": "Copies already uploaded to the engine",
            "bytes": size, "files": count, "_paths": paths, "blocked": busy.anywhere(),
            "what": "The engine keeps whatever the app uploads to it in its own input folder. These are the "
                    "corpus song copies it was sent for transcription and style description.",
            "consequence": "Nothing you will notice. The app uploads again whenever it needs to.",
        })

    paths = _staged_training_copies()
    size = sum(tree(p)[0] for p in paths)
    if paths:
        out.append({
            "id": "engine-training-copies", "title": "The engine's copies of training sets",
            "bytes": size, "files": sum(tree(p)[1] for p in paths), "_paths": paths, "blocked": busy.anywhere(),
            "what": "Each training run puts a copy of its training set in the engine's input folder for the "
                    "trainer to read. These belong to runs that have ended.",
            "consequence": "None for a finished run. A run that stopped short can still be finished from what "
                           "it saved, which does not need them.",
        })

    for identity in rows("SELECT id, name FROM identities ORDER BY name"):
        name = identity["name"] or "corpus"
        dataset = _corpus_dir(identity["id"]) / "dataset"
        size, count = tree(dataset)
        if count:
            out.append({
                "id": f"training-set:{identity['id']}", "title": f"Training set: {name}", "corpus": identity["id"],
                "bytes": size, "files": count, "_paths": [dataset], "blocked": busy.corpus(identity["id"]),
                "what": "This corpus's songs as the trainer reads them: each one written again as lossless FLAC "
                        "(larger than the original, whatever the original was), cut where the training limit "
                        "applies, with its lyrics and caption beside it.",
                "consequence": "LoRAs already trained are not affected. Before this corpus can train again you "
                               "press Export to write the set again, which takes a few minutes.",
            })
        root = loras.folder()
        marks = loras.checkpoints(lora_base(identity), root) if root else []
        if marks:
            out.append({
                "id": f"checkpoints:{identity['id']}", "title": f"Training checkpoints: {name}", "corpus": identity["id"],
                "bytes": sum(m["bytes"] for m in marks), "files": len(marks), "_names": [m["name"] for m in marks],
                "blocked": busy.corpus(identity["id"]),
                "what": "A training run saves a checkpoint every 50 steps, each as large as the LoRA itself. They "
                        "sit folded under the LoRA in the Style LoRA list, so an earlier stage can be tried by ear.",
                "consequence": "You can no longer choose an earlier stage of this corpus's training. The finished "
                               "LoRA is kept.",
            })
    return out


def areas() -> list[dict]:
    """Where all the space is, for reading only."""
    data = config.DATA_DIR
    models = Path(config.MODELS_DIR)
    lora_dir = loras.folder()
    mark_bytes = mark_files = 0
    if lora_dir:
        marks = [p for p in lora_dir.glob("*_step*.safetensors") if p.is_file()]
        mark_bytes, mark_files = _sum(marks)
    lora_total, lora_files = tree(lora_dir)
    models_total, models_files = tree(models)
    out = [
        ("Takes", "The audio, score and notes of every take you have made. Delete takes from the main screen.",
         tree(config.TAKES_DIR)),
        ("Corpora", "Each corpus's copy of its songs, their separated vocals, scores, and the training set. "
                    "Delete a corpus, or songs in it, from the Corpora window.", tree(data / "identities")),
        ("Recordings", "Recordings you loaded to cover or transcribe.", tree(config.SOURCES_DIR)),
        ("Stems", "Stems you have separated and kept.", tree(config.STEMS_DIR)),
        ("LoRAs", "Finished LoRAs, and the checkpoints training saved along the way (listed above). Remove "
                  "a LoRA from the Style LoRA list.", (lora_total, lora_files)),
        ("Models", "The models Yeufonic runs on, which it needs: the YuE2 model, Gemma, the transcriber, and the "
                   "rest. Not for removing here.", (max(0, models_total - lora_total), max(0, models_files - lora_files))),
    ]
    inbox, outbox = tree(config.ENGINE_INPUT_DIR), tree(config.ENGINE_OUTPUT_DIR)
    out.append(("The engine's working folders", "What the engine was sent and what it wrote on the way. Mostly "
                "copies the app has taken back.", (inbox[0] + outbox[0], inbox[1] + outbox[1])))
    counted = sum(tree(p)[0] for p in (config.TAKES_DIR, data / "identities", config.SOURCES_DIR, config.STEMS_DIR))
    whole = tree(data)
    out.append(("Everything else here", "The database, logs and temporary files.",
                (max(0, whole[0] - counted), max(0, whole[1]))))
    result = [{"name": n, "note": note, "bytes": b, "files": f} for n, note, (b, f) in out]
    result[4]["checkpoint_bytes"] = mark_bytes
    return result


def corpora(lora_base: Callable[[dict], str]) -> list[dict]:
    """Per corpus: where its space is, so the biggest can be seen at a glance."""
    out = []
    root = loras.folder()
    for identity in rows("SELECT id, name FROM identities ORDER BY name"):
        base = _corpus_dir(identity["id"])
        songs = tree(base / "songs")
        working = _sum([p for p in _working_copy_paths() if base in p.parents]) if songs[1] else (0, 0)
        marks = loras.checkpoints(lora_base(identity), root) if root else []
        out.append({"id": identity["id"], "name": identity["name"] or "corpus",
                    "songs": songs[0] - working[0], "working_copies": working[0],
                    "training_set": tree(base / "dataset")[0],
                    "checkpoints": sum(m["bytes"] for m in marks)})
    out.sort(key=lambda c: c["songs"] + c["working_copies"] + c["training_set"] + c["checkpoints"], reverse=True)
    return out


def scan(busy: Busy, lora_base: Callable[[dict], str]) -> dict:
    found = items(busy, lora_base)
    try:
        disk = shutil.disk_usage(config.DATA_DIR)
        free = {"free": disk.free, "total": disk.total}
    except OSError:
        free = {"free": None, "total": None}
    return {
        "measured_at": time.time(),
        "disk": free,
        "areas": areas(),
        "corpora": corpora(lora_base),
        "items": [{k: v for k, v in item.items() if not k.startswith("_")} for item in found],
        "reclaimable": sum(i["bytes"] for i in found if not i["blocked"]),
    }


def _remove_item(item: dict) -> int:
    """Remove one item's files; return the bytes freed."""
    freed = 0
    if "_names" in item:
        root = loras.folder()
        if not root:
            return 0
        for name in item["_names"]:
            try:
                size = (root / name).stat().st_size
                loras.remove(name, root)
                freed += size
            except (OSError, ValueError) as exc:
                log.warning("could not remove checkpoint %s: %s", name, exc)
        return freed
    for path in item["_paths"]:
        allowed = [config.DATA_DIR] + ([config.ENGINE_INPUT_DIR] if config.ENGINE_INPUT_DIR else [])
        if not any(inside(path, root) for root in allowed):
            log.warning("refusing to remove %s: not in a folder this app owns", path)
            continue
        size = tree(path)[0]
        remove_tree(path)
        freed += size
    return freed


def reclaim(ids: list[str], busy: Busy, lora_base: Callable[[dict], str]) -> dict:
    """Remove the named items.  One that is unknown, in use or already gone is reported, not an error."""
    by_id = {item["id"]: item for item in items(busy, lora_base)}
    freed, removed, skipped = 0, [], []
    for item_id in dict.fromkeys(ids):
        item = by_id.get(item_id)
        if not item:
            skipped.append({"id": item_id, "reason": "nothing there to remove"})
            continue
        if item["blocked"]:
            skipped.append({"id": item_id, "reason": f"{item['blocked']}, so it was left alone"})
            continue
        got = _remove_item(item)
        freed += got
        removed.append({"id": item_id, "bytes": got})
        if item_id.startswith("training-set:"):
            # The corpus no longer has a set written: the window says so, and Export is offered.
            execute("UPDATE identities SET exported_at = NULL, export_dir = NULL WHERE id = ?", (item["corpus"],))
        log.info("Storage: removed %s (%s)", item["title"], human(got))
    return {"freed": freed, "removed": removed, "skipped": skipped}


# ------------------------------------------------------------------- automatic tidying
# Called by the jobs, which decide from Settings whether to.

def drop_working_copies(song_folder: Path | None, song_id: str) -> int:
    """Remove a corpus song's working copies and what was uploaded for it, once its job has ended."""
    freed = 0
    paths: list[Path] = []
    if song_folder and song_folder.is_dir():
        paths += [p for p in song_folder.iterdir() if p.is_file() and WORKING_COPY.match(p.name)]
    if config.ENGINE_INPUT_DIR and config.ENGINE_INPUT_DIR.is_dir():
        paths += [p for p in config.ENGINE_INPUT_DIR.glob(f"identity-{song_id}-*") if p.is_file()]
    for path in paths:
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            pass
    return freed


def drop_training_set(identity_id: str, run_id: str) -> int:
    """Remove a corpus's training set, and the engine's copy of it for this run, once training has ended."""
    freed = 0
    dataset = _corpus_dir(identity_id) / "dataset"
    freed += tree(dataset)[0]
    remove_tree(dataset)
    execute("UPDATE identities SET exported_at = NULL, export_dir = NULL WHERE id = ?", (identity_id,))
    if config.ENGINE_INPUT_DIR:
        staged = config.ENGINE_INPUT_DIR / f"lora-{run_id}"
        if staged.is_dir() and inside(staged, config.ENGINE_INPUT_DIR):
            freed += tree(staged)[0]
            remove_tree(staged)
    return freed
