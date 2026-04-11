"""High-level API for sliding-correlator channel sounder data processing.

Orchestrates the three-stage pipeline:
    bin_read      : raw .bin → CIR (IQ parsing + sliding correlation)
    b2b_extract   : B2B .bin → frequency-domain calibration vector
    cali          : CIR + cali_vec → calibrated CIR

Changelog
---------
2026-04-02  Add B2B-.bin calibration, frequency-offset estimation/correction,
            coherent averaging, and process_band() high-level API.
2026-04-02  FIX: Disable freq-offset correction (B2B peak = hardware delay,
            not oscillator offset). Add incoherent averaging, B2B diagnostic,
            max_frames support, and process_all_bands().
2026-04-09  Refactor: split into bin_read / b2b_extract / cali submodules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import numpy as np
import scipy.io

from .bin_read import ATT_B2B_DB, BW_HZ, FS_HZ, U, _load_frames, _parse_gps, _parse_iq, _sliding_correlate
from .b2b_extract import diagnose_b2b_delay, estimate_freq_offset_hz, extract_cali_vec
from .cali import apply_fr_calibration

# Re-export constants for backward compatibility
__all__ = [
    "FS_HZ", "BW_HZ", "ATT_B2B_DB", "U",
    "diagnose_b2b_delay", "estimate_freq_offset_hz",
    "compute_cali_from_b2b",
    "read_bin_folder", "process_band", "process_all_bands",
    "coherent_average_cir", "incoherent_average_pdp", "incoherent_average_cir_mag",
    "apply_freq_offset_correction",
]


# ── Backward-compatibility alias ──────────────────────────────────────────────

def compute_cali_from_b2b(
    b2b_path: Path,
    n_avg: int = 1,
    mag_avg: bool = False,
) -> np.ndarray:
    """Alias for extract_cali_vec() — kept for backward compatibility."""
    return extract_cali_vec(b2b_path, n_avg=n_avg, mag_avg=mag_avg)


# ── Averaging helpers ─────────────────────────────────────────────────────────


def coherent_average_cir(cir: np.ndarray, n_frames: int) -> np.ndarray:
    """Complex-average CIR over n_frames → (1, U) complex64.

    ⚠️  NOT usable with independent TCXO oscillators (phase cancellation).
        Requires shared clock source. Use incoherent_average_pdp() instead.
    """
    n = min(n_frames, len(cir))
    return cir[:n].mean(axis=0, keepdims=True).astype(np.complex64)


def incoherent_average_pdp(cir: np.ndarray) -> np.ndarray:
    """Power-average CIR frames → (U,) float64 power delay profile.

    Safe for independent TCXO systems. SNR gain ≈ 5·log10(N) dB.
    """
    return (np.abs(cir) ** 2).mean(axis=0)


def incoherent_average_cir_mag(cir: np.ndarray) -> np.ndarray:
    """Magnitude-average CIR frames → (U,) float64."""
    return np.mean(np.abs(cir), axis=0)


# ── Frequency-offset correction (experimental, not for B2B-derived offsets) ──


def apply_freq_offset_correction(iq: np.ndarray, delta_f_hz: float) -> np.ndarray:
    """De-rotate IQ by delta_f_hz (external measurement only, NOT B2B-derived).

    ⚠️  Do NOT use with B2B-derived estimates — those reflect hardware delay.
    """
    if delta_f_hz == 0.0:
        return iq
    n = np.arange(iq.shape[1], dtype=np.float64)
    phasor = np.exp(-1j * 2.0 * np.pi * delta_f_hz * n / FS_HZ).astype(np.complex64)
    return (iq * phasor[np.newaxis, :]).astype(np.complex64)


# ── Public API ────────────────────────────────────────────────────────────────


def read_bin_folder(
    folder: Path,
    cali_path: Path,
    fc_hz: float = 0.0,
    att_db: float = 0.0,
    pa_gain_db: Union[float, np.ndarray, None] = None,
    ant_gain_dbi: Union[float, np.ndarray, None] = None,
) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Read all .bin files in folder and return calibrated CIR + GPS.

    Parameters
    ----------
    folder    : directory containing A2A .bin files
    cali_path : FR_cali_save.mat **or** a B2B .bin file (auto-detected)
    fc_hz     : carrier frequency in Hz
    att_db    : attenuation used in B2B calibration (dB, positive)
    pa_gain_db, ant_gain_dbi : see apply_fr_calibration()

    Returns
    -------
    cir_final : (n_frames, U) complex64
    gps       : dict with lat/lon/alt/hour/minute/second
    """
    if cali_path.suffix.lower() == ".bin":
        cali_vec = extract_cali_vec(cali_path)
    else:
        mat = scipy.io.loadmat(str(cali_path))
        key = next(k for k in mat if not k.startswith("_"))
        cali_vec = mat[key].flatten().astype(np.complex128) * 1e3

    frames = _load_frames(folder)
    gps = _parse_gps(frames)
    iq = _parse_iq(frames)
    del frames

    cir_raw = _sliding_correlate(iq)
    del iq

    cir_final = apply_fr_calibration(
        cir_raw, cali_vec, fc_hz=fc_hz, att_db=att_db,
        pa_gain_db=pa_gain_db, ant_gain_dbi=ant_gain_dbi,
    )
    return cir_final, gps


def process_band(
    a2a_path: Path,
    b2b_path: Path,
    fc_hz: float,
    att_db: float = ATT_B2B_DB,
    correct_freq_offset: bool = False,
    pa_gain_db: Union[float, np.ndarray, None] = None,
    ant_gain_dbi: Union[float, np.ndarray, None] = None,
) -> Tuple[np.ndarray, Dict[str, np.ndarray], dict]:
    """Full pipeline for one band: A2A + B2B .bin pair → calibrated CIR.

    Steps
    -----
    1. B2B .bin → CIR → diagnose delay → extract cali_vec (single frame)
    2. A2A .bin → GPS + IQ → sliding correlate
    3. apply_fr_calibration(cir_raw, cali_vec, ...)

    Returns
    -------
    cir_final : (n_frames, U) complex64
    gps       : dict with lat/lon/alt/hour/minute/second
    b2b_diag  : dict with peak_bin/peak_delay_ns/peak_power_db/note
    """
    # ── B2B ──────────────────────────────────────────────────────────────────
    b2b_frames = _load_frames(b2b_path)
    b2b_iq = _parse_iq(b2b_frames)
    del b2b_frames
    b2b_cir = _sliding_correlate(b2b_iq)
    del b2b_iq

    b2b_diag = diagnose_b2b_delay(b2b_cir)
    cali_vec = np.fft.fft(b2b_cir[0].astype(np.complex128))  # single frame
    del b2b_cir

    if correct_freq_offset:
        import warnings
        warnings.warn(
            "freq_offset_correction is disabled: B2B peak = hardware delay (~1300 ns), "
            "not oscillator offset. TCXO: ±2.5 ppm → ±3.5 kHz @ 1.4 GHz. "
            "Processing WITHOUT frequency correction.",
            UserWarning,
            stacklevel=2,
        )

    # ── A2A ──────────────────────────────────────────────────────────────────
    a2a_frames = _load_frames(a2a_path)
    gps = _parse_gps(a2a_frames)
    a2a_iq = _parse_iq(a2a_frames)
    del a2a_frames

    cir_raw = _sliding_correlate(a2a_iq)
    del a2a_iq

    cir_final = apply_fr_calibration(
        cir_raw, cali_vec, fc_hz=fc_hz, att_db=att_db,
        pa_gain_db=pa_gain_db, ant_gain_dbi=ant_gain_dbi,
    )
    return cir_final, gps, b2b_diag


def process_all_bands(
    data_dir: Path,
    bands: Optional[Dict[str, float]] = None,
    att_db: float = ATT_B2B_DB,
    pa_gain_db: Union[float, np.ndarray, None] = None,
    ant_gain_dbi: Union[float, np.ndarray, None] = None,
) -> Dict[str, dict]:
    """Process all frequency bands in a directory.

    Parameters
    ----------
    data_dir : contains {band}_A2A.bin and {band}_B2B.bin files
    bands    : {band_name: fc_hz}. Default: 1400M/3600M/4900M
    att_db, pa_gain_db, ant_gain_dbi : see process_band()

    Returns
    -------
    dict mapping band_name → {cir, gps, b2b_diag, error}
    """
    if bands is None:
        bands = {"1400M": 1.4e9, "3600M": 3.6e9, "4900M": 4.9e9}

    results: Dict[str, dict] = {}
    for band_name, fc_hz in bands.items():
        a2a_path = data_dir / f"{band_name}_A2A.bin"
        b2b_path = data_dir / f"{band_name}_B2B.bin"

        if not a2a_path.exists() or not b2b_path.exists():
            results[band_name] = {
                "cir": None, "gps": None, "b2b_diag": None,
                "error": f"Missing: A2A={a2a_path.exists()}, B2B={b2b_path.exists()}",
            }
            continue

        try:
            print(f"Processing {band_name} ({fc_hz / 1e9:.1f} GHz)...")
            cir, gps, b2b_diag = process_band(
                a2a_path=a2a_path, b2b_path=b2b_path, fc_hz=fc_hz,
                att_db=att_db, pa_gain_db=pa_gain_db, ant_gain_dbi=ant_gain_dbi,
            )
            results[band_name] = {"cir": cir, "gps": gps, "b2b_diag": b2b_diag, "error": None}
            print(
                f"  B2B peak: bin {b2b_diag['peak_bin']}, "
                f"delay {b2b_diag['peak_delay_ns']:.0f} ns, "
                f"power {b2b_diag['peak_power_db']:.1f} dB  |  CIR {cir.shape}"
            )
        except Exception as e:
            print(f"  ERROR {band_name}: {e}")
            results[band_name] = {"cir": None, "gps": None, "b2b_diag": None, "error": str(e)}

    return results
