"""
Signal processing and CFO estimation for Luoyang channel measurements.

Responsibilities (SRP):
  - LFM matched-filter construction
  - IQ coherent averaging
  - CIR generation (sliding correlation via FFT)
  - CFO estimation from CIR phase trajectories
  - Summary statistics

Depends only on NumPy; no file I/O.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

# ------------------------------------------------------------------
# Physical constants (system-level, not file-format)
# ------------------------------------------------------------------

T_FRAME: float = 0.010  # frame period [s], 10 ms


# ------------------------------------------------------------------
# Signal processing helpers
# ------------------------------------------------------------------


def build_lfm_matched_filter(length: int) -> np.ndarray:
    """
    Construct the frequency-domain matched filter for an LFM sequence.

    The reference LFM is a linear chirp of *length* samples occupying the
    full normalised bandwidth (-0.5 … +0.5).  The matched filter is its
    conjugate spectrum, used for FFT-based sliding correlation.

    Parameters
    ----------
    length : int
        Number of samples in the LFM sequence (U).

    Returns
    -------
    np.ndarray
        Complex64 matched-filter array of shape (3*length,) in the
        frequency domain, ready for element-wise multiplication with
        FFT of the tiled IQ signal.
    """
    u = length
    t = np.arange(u, dtype=np.float32)
    phase = np.pi * (t / u - 0.5) * t          # linear chirp phase
    lfm = np.exp(1j * phase).astype(np.complex64)

    # Tile × 3 so that circular correlation gives a linear one
    lfm_tiled = np.tile(lfm, 3)
    return np.conj(np.fft.fft(lfm_tiled)).astype(np.complex64)


def coherent_average(iq_sequences: np.ndarray, axis: int = 1) -> np.ndarray:
    """
    Compute the complex coherent average along the specified axis.

    Parameters
    ----------
    iq_sequences : np.ndarray
        Array of complex IQ data.  For intra-frame averaging the expected
        shape is (..., N_seqs, U).
    axis : int
        Axis along which to average (default 1 = sequence axis).

    Returns
    -------
    np.ndarray
        Averaged array with the specified axis removed, same dtype as input.
    """
    return iq_sequences.mean(axis=axis)


def generate_cir_from_iq(
    iq: np.ndarray,
    matched_filter: np.ndarray,
) -> np.ndarray:
    """
    Generate the channel impulse response (CIR) from a single IQ vector
    via FFT-based sliding correlation.

    Processing steps:
      1. Remove DC offset.
      2. Tile the sequence × 3 to avoid circular aliasing.
      3. Compute FFT, multiply by matched filter, IFFT.
      4. Extract the central window of length U.

    Parameters
    ----------
    iq : np.ndarray
        Complex IQ sequence of shape (U,).
    matched_filter : np.ndarray
        Frequency-domain matched filter of shape (3*U,) from
        :func:`build_lfm_matched_filter`.

    Returns
    -------
    np.ndarray
        Complex64 CIR of shape (U,).
    """
    u = len(iq)
    iq_dc = iq - iq.mean()                      # DC removal
    iq_tiled = np.tile(iq_dc.astype(np.complex64), 3)

    corr_full = np.fft.ifft(np.fft.fft(iq_tiled) * matched_filter)

    # Extract centre window [U : 2U]
    return corr_full[u : 2 * u].astype(np.complex64)


# ------------------------------------------------------------------
# CFO estimation
# ------------------------------------------------------------------


class CFOEstimator:
    """
    Estimate Carrier Frequency Offset (CFO) from a sequence of per-frame CIRs.

    Both estimation methods operate on the complex value at the dominant
    multipath peak across all frames.

    Parameters
    ----------
    cir : np.ndarray
        Per-frame CIR of shape (n_frames, U), dtype complex.
    frame_period_s : float
        Frame repetition period in seconds (e.g. 0.010 for 10 ms).
    """

    def __init__(self, cir: np.ndarray, frame_period_s: float = T_FRAME) -> None:
        if cir.ndim != 2:
            raise ValueError(f"cir must be 2-D (n_frames, U), got shape {cir.shape}")
        self._cir = cir
        self._t_frame = frame_period_s
        self._peak_bin: int = int(np.argmax(np.abs(cir).mean(axis=0)))

    @property
    def peak_bin(self) -> int:
        """Bin index of the dominant multipath component."""
        return self._peak_bin

    def estimate_by_adjacent_frames(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Estimate CFO from consecutive-frame phase differences.

        CFO_k = angle(CIR_{k+1}[peak] · conj(CIR_k[peak])) / (2π · T_frame)

        Observable range: ±1/(2·T_frame) [Hz].  Phase wrapping occurs outside
        this range; use :meth:`estimate_by_cumulative_phase` in that case.

        Returns
        -------
        cfo_hz : np.ndarray, shape (n_frames-1,)
            Per-pair CFO estimate in Hz.
        dphi : np.ndarray, shape (n_frames-1,)
            Raw phase differences in radians (diagnostic).
        """
        peak = self._cir[:, self._peak_bin]
        cross = peak[1:] * np.conj(peak[:-1])
        dphi = np.angle(cross)
        cfo_hz = dphi / (2.0 * np.pi * self._t_frame)
        return cfo_hz, dphi

    def estimate_by_cumulative_phase(
        self,
    ) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Estimate CFO from the unwrapped cumulative phase relative to frame 0.

        φ_k = angle(CIR_k[peak] · conj(CIR_0[peak]))  → unwrap → linear fit.
        The slope of the linear fit gives a robust global CFO estimate that
        tolerates phase wrapping and per-frame noise.

        Returns
        -------
        phi_unwrap : np.ndarray, shape (n_frames,)
            Unwrapped accumulated phase in radians.
        cfo_per_frame : np.ndarray, shape (n_frames,)
            Instantaneous cumulative CFO per frame (Hz); frame 0 is NaN.
        cfo_slope_hz : float
            Global CFO from linear regression of phi_unwrap vs. time (Hz).
        """
        peak = self._cir[:, self._peak_bin]
        phi_raw = np.angle(peak * np.conj(peak[0]))
        phi_unwrap = np.unwrap(phi_raw)

        k = np.arange(len(self._cir), dtype=np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            cfo_per_frame = np.where(
                k > 0,
                phi_unwrap / (2.0 * np.pi * k * self._t_frame),
                np.nan,
            )

        k_fit = k[1:]
        slope, _ = np.polyfit(k_fit * self._t_frame, phi_unwrap[1:], 1)
        cfo_slope_hz = slope / (2.0 * np.pi)

        return phi_unwrap, cfo_per_frame, cfo_slope_hz


# ------------------------------------------------------------------
# Statistics
# ------------------------------------------------------------------


def calculate_cfo_statistics(cfo_hz: np.ndarray) -> dict[str, float]:
    """
    Summarise a CFO array with basic statistics.

    Parameters
    ----------
    cfo_hz : np.ndarray
        CFO values in Hz (e.g. output of
        :meth:`CFOEstimator.estimate_by_adjacent_frames`).

    Returns
    -------
    dict
        Keys: ``mean_hz``, ``std_hz``, ``min_hz``, ``max_hz``.
    """
    return {
        "mean_hz": float(np.mean(cfo_hz)),
        "std_hz":  float(np.std(cfo_hz)),
        "min_hz":  float(np.min(cfo_hz)),
        "max_hz":  float(np.max(cfo_hz)),
    }
