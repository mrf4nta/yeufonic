"""The note samples the score preview plays with.

abcjs plays a score by loading one small MP3 per note it needs, from
`<url>/<instrument>-mp3/<note>.mp3`.  The samples are not in the repository: they are
fetched from their upstream home when the person asks for them, and kept in
`data/models/soundfonts`, from where the app serves them to its own page.

The sets are not all the same size, and that is not an error: a piano runs A0 to C8
(88 notes), a clean guitar reaches G7 (89), a voice stops at Gb6 (76) and a bass at
Gb5 (64), because a bass cannot play higher than that.  So a download keeps whatever
the publisher has, a note the set never had is skipped rather than failing the whole
set, and what arrived is written to a small JSON beside it.  That record is what says
the set is here, and how far it can play — the preview shifts a score by whole octaves
to fit inside it, since one missing sample stops a whole playback."""
from __future__ import annotations

import json
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
# The sets the score preview can play.  A score names no instruments, so the preview
# reads the style and picks one per voice; these are the ones it can choose between.
# Each is fetched from upstream only when a preview asks for it, so a library with a
# few styles on disk holds a few of them.  The keys are the upstream folder names and
# the numbers are General MIDI programs (see PREVIEW_INSTRUMENTS in app.js).
SETS = {
    "acoustic_grand_piano": "Piano",
    "electric_piano_1": "Electric piano",
    "drawbar_organ": "Organ",
    "marimba": "Marimba",
    "vibraphone": "Vibraphone",
    "acoustic_guitar_nylon": "Nylon guitar",
    "acoustic_guitar_steel": "Steel guitar",
    "electric_guitar_clean": "Clean guitar",
    "overdriven_guitar": "Overdriven guitar",
    "distortion_guitar": "Distorted guitar",
    "banjo": "Banjo",
    "acoustic_bass": "Upright bass",
    "electric_bass_finger": "Finger bass",
    "electric_bass_pick": "Pick bass",
    "slap_bass_1": "Slap bass",
    "synth_bass_1": "Synth bass",
    "violin": "Violin",
    "cello": "Cello",
    "string_ensemble_1": "Strings",
    "choir_aahs": "Choir",
    "voice_oohs": "Voice",
    "brass_section": "Brass",
    "alto_sax": "Saxophone",
    "flute": "Flute",
    "lead_2_sawtooth": "Sawtooth lead",
    "pad_2_warm": "Warm pad",
}

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


# The semitones of each note letter, and the note a MIDI number's name is built from.
_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi_of(note: str) -> int:
    """Middle C is 60: A0 is 21 and C8 is 108, the ends of a piano."""
    letter, rest = note[0], note[1:]
    shift = -1 if rest[:1] == "b" else 1 if rest[:1] == "#" else 0
    octave = rest[1:] if shift else rest
    return 12 * (int(octave) + 1) + _SEMITONES[letter] + shift


def _marker(instrument: str) -> Path:
    return folder() / f"{instrument}.json"


def notes_of(instrument: str) -> list[str]:
    """The notes this set has.  A set fetched before this record existed is recognised
    by holding the whole piano, which is what the first version of this fetched."""
    path = _marker(instrument)
    if path.is_file():
        try:
            return list(json.loads(path.read_text(encoding="utf-8")).get("notes") or [])
        except (OSError, ValueError):
            return []
    directory = folder() / f"{instrument}-mp3"
    return NOTES if all((directory / f"{note}.mp3").is_file() for note in NOTES) else []


def installed() -> list[str]:
    return [name for name in SETS if notes_of(name)]


def range_of(instrument: str) -> list[int] | None:
    """The lowest and highest note this set can play, as MIDI numbers."""
    notes = notes_of(instrument)
    if not notes:
        return None
    pitches = sorted(midi_of(note) for note in notes)
    return [pitches[0], pitches[-1]]


def download(instrument: str) -> int:
    """Fetch every note of an instrument that is not here yet, and record what arrived.
    Returns how many were fetched.  Each file is written whole or not at all; a note the
    publisher does not have is left out rather than failing the set."""
    if instrument not in SETS:
        raise ValueError(f"no such instrument: {instrument}")
    target = folder() / f"{instrument}-mp3"
    target.mkdir(parents=True, exist_ok=True)
    known = set(notes_of(instrument))
    missing = [n for n in NOTES if n not in known and not (target / f"{n}.mp3").is_file()]
    absent: list[str] = []

    def fetch(note: str) -> None:
        url = f"{UPSTREAM}{instrument}-mp3/{note}.mp3"
        try:
            response = httpx.get(url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                absent.append(note)          # this set never had this note
                return
            raise
        with tempfile.NamedTemporaryFile(dir=target, delete=False, suffix=".part") as handle:
            handle.write(response.content)
        Path(handle.name).replace(target / f"{note}.mp3")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, missing))
    here = [note for note in NOTES if (target / f"{note}.mp3").is_file()]
    _marker(instrument).write_text(json.dumps({"notes": here}), encoding="utf-8")
    log.info("Fetched %d note samples for %s: %d notes from %s to %s, %d the set does not have",
             len(missing) - len(absent), instrument, len(here),
             here[0] if here else "-", here[-1] if here else "-", len(absent))
    return len(missing) - len(absent)
