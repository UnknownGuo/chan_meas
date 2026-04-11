"""B2B .bin → frequency-domain calibration vector.

Reads a back-to-back (B2B) .bin file, converts it to CIR via sliding
correlation (same pipeline as bin_read), then transforms to frequency domain
to produce the system frequency response vector H_sys × H_att.

Key constraint: use single-frame or magnitude-averaged FFT.
With independent TCXO oscillators, coherent averaging across frames causes
phase cancellation (per-frame phase drift ~440 rad/frame at 7 kHz offset).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .bin_read import BW_HZ, _load_frames, _parse_iq, _sliding_correlate


# ── B2B diagnostic ────────────────────────────────────────────────────────────


def diagnose_b2b_delay(cir_b2b: np.ndarray) -> dict:
    """Report B2B correlation peak position (hardware delay, NOT freq offset).

    ⚠️  DO NOT use peak position to estimate frequency offset.
        TCXO offset is ±2.5 ppm (±3.5 kHz @ 1.4 GHz); hardware delay is ~1300 ns.

    Parameters
    ----------
    cir_b2b : (n_frames, U) complex array from B2B sliding correlator

    Returns
    -------
    dict: peak_bin, peak_delay_ns, peak_power_db, note
    """
    power = np.abs(cir_b2b.mean(axis=0)) ** 2
    peak_bin = int(np.argmax(power))
    delay_ns = peak_bin * (1e9 / BW_HZ)
    noise_floor = np.percentile(power, 10)
    peak_db = 10 * np.log10(power[peak_bin] / max(noise_floor, 1e-30))

    return {
        "peak_bin": peak_bin,
        "peak_delay_ns": delay_ns,
        "peak_power_db": peak_db,
        "note": (
            "Peak position reflects hardware processing delay, "
            "NOT frequency offset. Do NOT use for freq correction."
        ),
    }


# ── Calibration vector extraction ─────────────────────────────────────────────


def extract_cali_vec(
    b2b_path: Path,
    n_avg: int = 1,
    mag_avg: bool = False,
) -> np.ndarray:
    """B2B .bin → cali_vec (frequency-domain H_sys × H_att).

    Processing pipeline
    -------------------
    B2B .bin → _load_frames → _parse_iq → _sliding_correlate → FFT → cali_vec

    Averaging strategy
    ------------------
    n_avg=1 (default):
        Single frame FFT → unbiased but noisy.
    mag_avg=True, n_avg=N:
        Average |FFT(CIR)| across N frames, then combine with phase of frame 0.
        Stable magnitude estimate immune to inter-frame TCXO phase drift.
        Recommended for n_avg > 1 with independent-TCXO systems.

    Parameters
    ----------
    b2b_path : path to a B2B .bin file (e.g. 1400_B2B.bin)
    n_avg    : number of frames to use (default 1)
    mag_avg  : if True, magnitude-average across n_avg frames (see above)

    Returns
    -------
    cali_vec : (U,) complex128 — frequency-domain calibration vector H_sys × H_att
    """
    frames = _load_frames(b2b_path)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq

    n = min(n_avg, len(cir))

    if mag_avg and n > 1:
        H_frames = np.fft.fft(cir[:n].astype(np.complex128), axis=1)  # (n, U)
        H_mag_avg = np.abs(H_frames).mean(axis=0)                      # (U,)
        H_phase_0 = np.angle(H_frames[0])                              # (U,)
        return (H_mag_avg * np.exp(1j * H_phase_0)).astype(np.complex128)

    if n > 10:
        import warnings
        warnings.warn(
            f"n_avg={n} with mag_avg=False causes phase cancellation with "
            f"independent oscillators. Use mag_avg=True for n_avg > 1.",
            UserWarning,
            stacklevel=2,
        )

    cir_avg = cir[:n].mean(axis=0)
    return np.fft.fft(cir_avg.astype(np.complex128))  # (U,) complex128


# ── Deprecated alias ──────────────────────────────────────────────────────────


def estimate_freq_offset_hz(cir_b2b: np.ndarray) -> float:
    """[DEPRECATED] Use diagnose_b2b_delay() instead. Returns 0.0 Hz."""
    import warnings
    warnings.warn(
        "estimate_freq_offset_hz() is deprecated. B2B peak = hardware delay, "
        "not freq offset. Use diagnose_b2b_delay() for diagnostics. Returns 0.0 Hz.",
        DeprecationWarning,
        stacklevel=2,
    )
    return 0.0
