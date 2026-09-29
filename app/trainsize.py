"""How much of each song a LoRA trains on, worked out from the card.

The Planner learns each song whole, as one sequence of audio codes (25 a second) after
its style and lyrics, and leaves out a song whose sequence is longer than `max_tokens`.
So songs are cut at some number of minutes.  What limits that number is not the
context, which costs nothing in itself, but preparing the set: the dataset builder
encodes each song whole on the GPU, and the memory it needs grows with the song.

    tokens  = 25 x seconds + the style and lyrics, rounded up to whole 512s
    minutes = (memory the engine could have - the builder's base - a margin) / per minute

`BUILDER_*` are provisional: one measurement (a build of songs up to 5:54 used about
13.9 GB of a 16 GB card, the engine at rest holding 8.6 GB) fitted to a straight line.
Two builds at different cuts would replace them.  Nothing here starts a build.
"""
from __future__ import annotations

import math

TOKENS_PER_SECOND = 25
PREFIX_TOKENS = 1536         # style and lyrics: at most 3,840 characters in the sets seen
TOKEN_STEP = 512
MIN_TOKENS = 8192            # never less than the default: the context costs nothing itself
MAX_TOKENS = 16384           # what the trainer's node allows

FLOOR_MINUTES = 3.5          # never less than the default, which is what ships today
CEILING_MINUTES = 6.0        # the builder encodes a song whole: past this it needs chunked encoding
BUILDER_BASE_GB = 8.6        # provisional: the engine's weights at rest
BUILDER_GB_PER_MINUTE = 0.9  # provisional: (13.9 - 8.6) / 5.9
MARGIN_GB = 1.0              # kept spare: a build that runs out of memory wedges the engine

GB = 1024 ** 3


def _half_minutes_down(minutes: float) -> float:
    return math.floor(minutes * 2 + 1e-9) / 2


def _half_minutes_up(minutes: float) -> float:
    return math.ceil(minutes * 2 - 1e-9) / 2


def clock(minutes: float) -> str:
    whole, seconds = divmod(round(minutes * 60), 60)
    return f"{whole}:{seconds:02d}"


def tokens_for(seconds: float) -> int:
    """The context a sequence of this many seconds needs, in whole steps of 512."""
    return math.ceil((TOKENS_PER_SECOND * seconds + PREFIX_TOKENS) / TOKEN_STEP) * TOKEN_STEP


def minutes_from_memory(available_gb: float) -> float:
    """How many minutes of a song the builder can hold, with the margin spare."""
    return (available_gb - BUILDER_BASE_GB - MARGIN_GB) / BUILDER_GB_PER_MINUTE


def available_gb(gpu: dict | None) -> float | None:
    """What the engine could have once it lets go of what it holds: the free memory
    plus its own.  Memory that other programs hold is not counted."""
    if not gpu or gpu.get("vram_free") is None:
        return None
    return ((gpu.get("vram_free") or 0) + (gpu.get("engine_vram") or 0)) / GB


def choose(gpu: dict | None, durations: list[float]) -> dict:
    """The cut and the context for songs of these lengths (seconds) on this card.

    Never below the default cut, so it cannot do worse than not asking; never above
    what the builder can encode whole, nor above the longest song; and a context that
    holds the longest sequence that results."""
    free = available_gb(gpu)
    longest = max((d for d in durations if d), default=0.0) / 60
    if free is None:
        raw, note = None, "the card's memory could not be read"
    else:
        raw = minutes_from_memory(free)
        note = (f"{free:.1f} GB available; the builder needs about {BUILDER_BASE_GB:g} GB "
                f"and {BUILDER_GB_PER_MINUTE:g} GB a minute, with {MARGIN_GB:g} GB spare")
    memory_limit = FLOOR_MINUTES if raw is None else _half_minutes_down(min(raw, CEILING_MINUTES))
    minutes = max(FLOOR_MINUTES, memory_limit)
    # Not more than the songs have; and with none yet, the default.
    minutes = min(minutes, max(FLOOR_MINUTES, _half_minutes_up(longest))) if longest else FLOOR_MINUTES
    tokens = min(MAX_TOKENS, max(MIN_TOKENS, tokens_for(min(longest, minutes) * 60)))
    whole = sum(1 for d in durations if d and d <= minutes * 60 + 1)
    return {
        "minutes": minutes, "tokens": tokens, "whole": whole, "songs": len([d for d in durations if d]),
        "tight": raw is not None and raw < FLOOR_MINUTES,
        "reason": f"up to {clock(minutes)} of each song, {tokens:,} tokens: {note}",
    }
