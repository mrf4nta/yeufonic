"""The audio library versions Whisper needs. A newer PyAV once removed an option faster-whisper uses, so
lyric hearing broke on any fresh install that let PyAV choose its own version."""
import re
import struct
import wave
from pathlib import Path

import pytest


def test_pyav_is_pinned():
    text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^av==\d+\.\d+\.\d+\s*$", text, re.M), "PyAV must be pinned: see the comment in requirements.txt"


def test_whisper_can_decode_audio_with_the_pyav_that_is_installed(tmp_path):
    """faster-whisper's own decoder, on a real file: this is the call that failed."""
    audio = pytest.importorskip("faster_whisper.audio")
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(struct.pack("<h", 3000 if (i // 20) % 2 else -3000) for i in range(16000)))
    samples = audio.decode_audio(str(path))
    assert len(samples) == 16000
