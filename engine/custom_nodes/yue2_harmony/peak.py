"""A lookahead peak limiter, on floating point audio.

The decoder can overshoot full scale by a few dB, and saving to 16-bit then flattens every
peak past it.  Turning a whole render down to fix a few peaks costs its level everywhere, so
this turns down only around the peaks: the gain each sample needs to sit under the ceiling
is taken as the smallest need within a short window either side, and then averaged over the
same window.  The average of values that are each at most the need at the centre is at most
that need, so no sample can end above the ceiling; and where nothing peaks the gain is 1
and the audio is untouched."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def limit(wave: torch.Tensor, ceiling: float, window: int) -> torch.Tensor:
    """`wave` is (batch, channels, samples).  Channels are limited together, so the stereo
    image does not move."""
    peak = wave.abs().amax(dim=1)                                   # (batch, samples)
    need = (ceiling / peak.clamp_min(1e-9)).clamp(max=1.0)          # the gain each sample can take
    if bool((need >= 1.0).all()):
        return wave
    width = max(3, window | 1)                                      # odd, so it centres
    pad = width // 2
    need = need.unsqueeze(1)                                        # (batch, 1, samples)
    lowest = -F.max_pool1d(-need, width, stride=1, padding=pad)     # the smallest within reach
    gain = F.avg_pool1d(lowest, width, stride=1, padding=pad, count_include_pad=False)
    return wave * gain
