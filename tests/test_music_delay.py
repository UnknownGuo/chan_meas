"""Tests for frequency-domain MUSIC delay estimation and Module-B source switch."""
from __future__ import annotations

import numpy as np
import pytest

from src.analysis.module_b import build_module_b_payload
from src.signal.music_delay import estimate_window_delays_music
from src.ui_dataset import compute_music_delay_tracks

BW_HZ = 50e6
# Small frequency size keeps the M~150 eigendecomposition fast for unit tests;
# the three test delays are far enough apart to resolve at this size.
N_FREQ = 256


def _synth_cir(delay_bins: list[int], amps: list[float], n_frames: int = 20, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    df = BW_HZ / (N_FREQ - 1)
    f = np.arange(N_FREQ) * df
    hf = np.zeros(N_FREQ, dtype=complex)
    for b, a in zip(delay_bins, amps, strict=True):
        hf += a * np.exp(-1j * 2 * np.pi * f * (b / BW_HZ))
    cir1 = np.fft.ifft(hf)
    noise = (rng.standard_normal((n_frames, N_FREQ)) + 1j * rng.standard_normal((n_frames, N_FREQ))) * 0.003
    return (np.tile(cir1, (n_frames, 1)) + noise).astype(np.complex64)


def test_music_recovers_three_paths():
    cir = _synth_cir([10, 35, 80], [1.0, 0.5, 0.25])
    est = estimate_window_delays_music(cir, bandwidth_hz=BW_HZ, max_delay_bin=200)
    bins = sorted(e.delay_bin for e in est)
    assert bins == [10, 35, 80]
    by_bin = {e.delay_bin: e.power_db for e in est}
    # Power is read from the PDP, whose sidelobe leakage at this small N_FREQ
    # pulls the weakest path a bit lower; the delays (the MUSIC output) are exact.
    assert by_bin[35] == pytest.approx(by_bin[10] - 6.0, abs=1.5)
    assert by_bin[80] == pytest.approx(by_bin[10] - 12.0, abs=2.5)


def test_music_tracks_structure_module_b_compatible():
    cir = _synth_cir([10, 35, 80], [1.0, 0.5, 0.25])
    tracks = compute_music_delay_tracks(
        cir, bandwidth_hz=BW_HZ, window_size_frames=20, step_frames=100, max_delay_bins=200
    )
    assert tracks["method"] == "delay_music_mdl"
    assert tracks["dopplerAvailable"] is False
    peak = tracks["windowTracks"][0]["peaks"][0]
    # Synthetic amplitude must satisfy |amp|^2 == 10^(P/10) so Module-B power works.
    assert peak["amplitudeImag"] == 0.0
    assert peak["amplitudeReal"] ** 2 == pytest.approx(10 ** (peak["powerDb"] / 10.0), rel=1e-3)
    assert peak["dopplerHz"] == 0.0


def test_module_b_source_switch_uses_music_windows():
    # 220 frames -> windows at starts 0,100,200 (win=20) -> 3 windows.
    cir = _synth_cir([10, 35, 80], [1.0, 0.5, 0.25], n_frames=220)
    music = compute_music_delay_tracks(
        cir, bandwidth_hz=BW_HZ, window_size_frames=20, step_frames=100, max_delay_bins=200
    )
    assert len(music["windowTracks"]) >= 2
    frame_stats = [
        {"frame": w["frame"], "timeSec": w["timeSec"], "distanceM": 50.0 + 25.0 * i}
        for i, w in enumerate(music["windowTracks"])
    ]
    dataset = {
        "meta": {"name": "synth", "frameRateHz": 100.0, "bandwidthHz": BW_HZ},
        "frameStats": frame_stats,
        "sageDelayDoppler": None,
        "musicDelay": music,
    }
    payload = build_module_b_payload(dataset, source="music")
    assert payload["meta"]["source"] == "music"
    assert payload["meta"]["dopplerAvailable"] is False
    # MUSIC has no Doppler -> RMS Doppler samples must be empty.
    assert payload["rmsDopplerSpread"]["samplesHz"] == []
    # Delay spread should be populated (3 resolved paths per window).
    assert len(payload["rmsDelaySpread"]["samplesNs"]) >= 1


def test_module_b_unknown_source_raises():
    with pytest.raises(ValueError):
        build_module_b_payload({"meta": {}, "musicDelay": None}, source="bogus")
