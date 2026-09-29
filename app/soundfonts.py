"""The note samples the score preview plays with.

abcjs plays a score by loading one small MP3 per note it needs, from
`<url>/<instrument>-mp3/<note>.mp3`.  The samples are not in the repository: they are
fetched from their upstream home when the person asks for them, and kept in
`data/models/soundfonts`, from where the app serves them to its own page."""
from __future__ import annotations

import logging
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("yue2.soundfonts")

# paulrosen/midi-js-soundfonts, the set abcjs uses by default.
UPSTREAM = "https://raw.githubusercontent.com/paulrosen/midi-js-soundfonts/gh-pages/abcjs/"
SETS = {"acoustic_grand_piano": "Piano"}

_FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# The 88 keys of a piano, A0 to C8, as the files are named (flats, never sharps).
NOTES = [f"{_FLATS[m % 12]}{m // 12 - 1}" for m in range(21, 109)]
NOTE = re.compile(r"[A-G]b?[0-8]")
INSTRUMENT = re.compile(r"[a-z0-9_]+")


def folder() -> Path:
    return config.DATA_DIR / "models" / "soundfonts"


def sample(instrument: str, note: str) -> Path | None:
    """The file for one note, or None when the names are not ones we serve or it is not there."""
    if instrument not in SETS or not NOTE.fullmatch(note):
        return None
    path = folder() / f"{instrument}-mp3" / f"{note}.mp3"
    return path if path.is_file() else None


def installed() -> list[str]:
    return [name for name in SETS if all((folder() / f"{name}-mp3" / f"{n}.mp3").is_file() for n in NOTES)]


def download(instrument: str) -> int:
    """Fetch every note of an instrument that is not here yet.  Returns how many were fetched.
    Each file is written whole or not at all."""
    if instrument not in SETS:
        raise ValueError(f"no such instrument: {instrument}")
    target = folder() / f"{instrument}-mp3"
    target.mkdir(parents=True, exist_ok=True)
    missing = [n for n in NOTES if not (target / f"{n}.mp3").is_file()]

    def fetch(note: str) -> None:
        url = f"{UPSTREAM}{instrument}-mp3/{note}.mp3"
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=target, delete=False, suffix=".part") as handle:
            handle.write(response.content)
        Path(handle.name).replace(target / f"{note}.mp3")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, missing))
    log.info("Fetched %d note samples for %s", len(missing), instrument)
    return len(missing)
