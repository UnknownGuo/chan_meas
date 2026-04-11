"""Frequency-response calibration: raw CIR + cali_vec → calibrated CIR.

Applies B2B frequency-response removal and system gain compensation
(attenuator, PA, antenna) in the frequency domain.

Calibration formula:
    H_corrected(f) = FFT(CIR) / cali_vec × 10^((-att_db - PA(f) - 2×G_ant(f)) / 20)
                          ↓                         ↓
                   remove B2B FR              compensate system gain
"""

from __future__ import annotations

from typing import Union

import numpy as np

from .bin_read import BW_HZ, U

# ── PA datasheet: ZHL-2W-63-S+ (measured at 28 V) ───────────────────────────

_PA_FREQ_MHZ = np.array(
    [600, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000],
    dtype=np.float64,
)
_PA_GAIN_DB = np.array(
    [40.54, 40.13, 41.89, 40.55, 44.65, 42.50,
     43.90, 41.57, 42.31, 40.48, 40.76, 40.39],
    dtype=np.float64,
)


def _interp_pa_gain(freqs_hz: np.ndarray) -> np.ndarray:
    """Per-bin PA gain (dB) from ZHL-2W-63-S+ datasheet."""
    return np.interp(freqs_hz / 1e6, _PA_FREQ_MHZ, _PA_GAIN_DB)


# ── Antenna datasheet: MA802P omnidirectional ─────────────────────────────────

_ANT_FREQ_MHZ = np.array(
    [30, 60, 100, 140, 180, 220, 260, 300, 500, 700, 1400, 3800, 8000],
    dtype=np.float64,
)
_ANT_GAIN_DBI = np.array(
    [-27, -25, -20, -15, -10, -5, -3, -1, 0, 0, 0, 0, 0],
    dtype=np.float64,
)


def _interp_ant_gain(freqs_hz: np.ndarray) -> np.ndarray:
    """Per-bin MA802P antenna gain (dBi) from datasheet."""
    return np.interp(freqs_hz / 1e6, _ANT_FREQ_MHZ, _ANT_GAIN_DBI)


# ── Core calibration ──────────────────────────────────────────────────────────


def apply_fr_calibration(
    cir: np.ndarray,
    cali_vec: np.ndarray,
    fc_hz: float = 0.0,
    att_db: float = 0.0,
    pa_gain_db: Union[float, np.ndarray, None] = None,
    ant_gain_dbi: Union[float, np.ndarray, None] = None,
) -> np.ndarray:
    """Apply B2B frequency-response calibration and system gain compensation.

    The B2B calibration captures H_sys × H_att (no PA, no antenna).
    After dividing by cali_vec and applying corrections:
        CIR ∝ H_channel  (PA, antenna, attenuator effects removed)

    Parameters
    ----------
    cir          : (n_frames, U) complex array from sliding correlator (A2A data)
    cali_vec     : (U,) complex128 — output of extract_cali_vec() from b2b_extract
    fc_hz        : carrier frequency in Hz (required for datasheet gain lookups)
    att_db       : attenuation in dB (positive) used during B2B calibration
    pa_gain_db   : PA gain in dB — scalar, per-bin array, or None (→ ZHL-2W-63-S+ datasheet)
    ant_gain_dbi : antenna gain in dBi (TX + RX, same model assumed, applied ×2) —
                   scalar, per-bin array, None (→ MA802P datasheet), or 0.0 to skip

    Returns
    -------
    cir_cal : (n_frames, U) complex64 — calibrated CIR in time domain
    """
    CIR_f = np.fft.fft(cir, axis=1) / cali_vec.astype(np.complex128)  # (n_frames, U)

    if att_db != 0.0 or pa_gain_db is not None or ant_gain_dbi is not None:
        freqs = np.fft.fftfreq(U, d=1.0 / BW_HZ) + fc_hz  # (U,) per-bin frequencies

        # PA gain (scalar / array / datasheet)
        if pa_gain_db is None:
            pa = _interp_pa_gain(freqs)
        elif np.isscalar(pa_gain_db):
            pa = np.full(U, float(pa_gain_db))
        else:
            pa = np.asarray(pa_gain_db, dtype=np.float64)

        # Antenna gain — applied twice (TX + RX, same model)
        if ant_gain_dbi is None:
            ant = _interp_ant_gain(freqs) * 2.0
        elif np.isscalar(ant_gain_dbi):
            ant = np.full(U, float(ant_gain_dbi) * 2.0)
        else:
            ant = np.asarray(ant_gain_dbi, dtype=np.float64) * 2.0

        # Amplitude correction: compensate for attenuator, PA, and antenna
        correction = 10.0 ** ((-att_db - pa - ant) / 20.0)
        CIR_f *= correction[np.newaxis, :]

    return np.fft.ifft(CIR_f, axis=1).astype(np.complex64)
