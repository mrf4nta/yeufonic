"""A render that overshoots full scale is turned down around its peaks before it is saved."""
import importlib.util
from pathlib import Path

import pytest

from app import config, jobs

torch = pytest.importorskip("torch")
SPEC = importlib.util.spec_from_file_location(
    "peak", Path(__file__).resolve().parents[1] / "engine" / "custom_nodes" / "yue2_harmony" / "peak.py")
peak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(peak)

RATE = 48000
CEILING = 10 ** (-0.5 / 20)


def tone(seconds=1.0, level=0.5, channels=2):
    t = torch.arange(int(RATE * seconds)) / RATE
    return (level * torch.sin(2 * torch.pi * 220 * t)).repeat(channels, 1).unsqueeze(0)     # (batch, channels, samples)


def test_a_render_under_the_ceiling_is_left_exactly_alone():
    wave = tone(level=0.8)
    assert torch.equal(peak.limit(wave, CEILING, 384), wave)


def test_no_sample_ends_over_the_ceiling_however_far_it_overshot():
    wave = tone(level=0.6)
    wave[0, :, 20000] = 1.9          # a lone spike, 5.6 dB over
    wave[0, :, 30000:30040] *= 3.0   # and a short burst of them
    limited = peak.limit(wave, CEILING, 384)
    assert float(limited.abs().max()) <= CEILING + 1e-4


def test_only_the_neighbourhood_of_a_peak_is_turned_down():
    wave = tone(level=0.6)
    wave[0, :, 24000] = 1.5
    limited = peak.limit(wave, CEILING, 384)
    far = torch.equal(limited[..., :23000], wave[..., :23000]) and torch.equal(limited[..., 25000:], wave[..., 25000:])
    assert far                                        # a window either side, nothing beyond it
    assert float(limited[..., 24000].abs().max()) <= CEILING + 1e-4
    # so the level of the whole is hardly touched
    drop = 20 * torch.log10(limited.pow(2).mean().sqrt() / wave.pow(2).mean().sqrt())
    assert float(drop) > -0.05


def test_the_channels_are_turned_down_together():
    wave = tone(level=0.5)
    wave[0, 0, 12000] = 1.8          # only the left goes over
    limited = peak.limit(wave, CEILING, 384)
    gain_left = limited[0, 0, 12000] / wave[0, 0, 12000]
    gain_right = limited[0, 1, 12000] / wave[0, 1, 12000]
    assert torch.isclose(gain_left, gain_right, atol=1e-4)      # the stereo image does not move


def test_the_guard_is_in_the_render_only_when_the_engine_has_it(monkeypatch):
    take = {"id": "t1", "style": "pop", "lyrics": "[Verse]\nla", "abc": "X:1\nK:C\n", "seed": 1, "mode": "full",
            "max_duration": 60, "kind": "song"}
    monkeypatch.setattr(jobs.ENGINE, "options", {"peak_guard": False}, raising=False)
    plain = jobs.build_render_graph(take)
    assert plain["16"]["inputs"]["audio"] == ["15", 0] and "30" not in plain
    monkeypatch.setattr(jobs.ENGINE, "options", {"peak_guard": True}, raising=False)
    guarded = jobs.build_render_graph(take)
    assert guarded["30"]["class_type"] == "Yue2PeakGuard"
    assert guarded["30"]["inputs"]["audio"] == ["15", 0] and guarded["16"]["inputs"]["audio"] == ["30", 0]
    assert guarded["30"]["inputs"]["ceiling_db"] == config.PEAK_CEILING_DB
    monkeypatch.setattr(config, "PEAK_GUARD", False)
    assert "30" not in jobs.build_render_graph(take)
