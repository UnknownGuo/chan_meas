"""Frequency-domain (spatial-smoothing) MUSIC for delay estimation.

Single-antenna delay-domain MUSIC, ported from
``matlab_code_reference/Wuhan_3_scenarios/MPC_number.m`` / ``test_use.m``:

1. Coherently average the CIR over the slow-time window, FFT to frequency.
2. Build an ``M``-dimensional covariance with forward-backward spatial
   smoothing over the frequency samples.
3. Eigendecompose; split signal/noise subspaces.  The MATLAB reference fixes
   the model order (``D_estimated``); here it is estimated automatically with
   the MDL criterion (the reference comments acknowledge the fixed value was a
   stand-in for "正确估计了多径数").
4. Scan delay with steering vectors ``a(tau) = exp(-j w tau)`` and evaluate the
   MUSIC pseudospectrum ``1 / (a^H E_n E_n^H a)``; pick peaks.
5. Each peak's **power is read from the actual PDP** (``20 log10|CIR_avg|``) at
   the snapped delay bin — the pseudospectrum height is not a physical power.

The estimator is single-antenna, so it returns delay + power only (no Doppler,
no complex amplitude).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass(frozen=True)
class MusicDelayEstimate:
    delay_bin: int
    delay_ns: float
    power_db: float


def _forward_backward_covariance(hf: np.ndarray, subarray_len: int) -> tuple[np.ndarray, int]:
    """Forward-backward smoothed covariance from a 1-D frequency response.

    Returns the ``M x M`` Hermitian covariance and the effective snapshot count.
    """
    n_freq = hf.size
    m = int(subarray_len)
    n_sub = n_freq - m + 1
    if n_sub < 1:
        raise ValueError(f"subarray_len={m} too large for n_freq={n_freq}")
    # Forward sub-vectors as rows: shape (n_sub, M).
    idx = np.arange(m)[None, :] + np.arange(n_sub)[:, None]
    fwd = hf[idx]
    # Backward: conjugate of the frequency-reversed sub-vector.
    bwd = np.conj(fwd[:, ::-1])
    # R = sum_l x_l x_l^H  ==>  X.T @ conj(X) with rows x_l (matches MATLAB x*x').
    rxx = (fwd.T @ np.conj(fwd) + bwd.T @ np.conj(bwd)) / (2.0 * n_sub)
    return rxx, 2 * n_sub


def _mdl_order(eigenvalues_desc: np.ndarray, n_snapshots: int, max_order: int) -> int:
    """MDL estimate of the number of signal eigenvalues.

    eigenvalues_desc : eigenvalues sorted in descending order.
    """
    m = eigenvalues_desc.size
    lam = np.clip(eigenvalues_desc.astype(np.float64), 1e-30, None)
    log_lam = np.log(lam)
    upper = min(int(max_order), m - 1)
    best_k = 1
    best_mdl = np.inf
    for k in range(0, upper + 1):
        noise = lam[k:]
        p = noise.size  # M - k
        if p <= 0:
            break
        log_geo = float(np.mean(log_lam[k:]))
        log_arith = float(np.log(np.mean(noise)))
        # log(geo/arith) <= 0; first term is the (non-negative) likelihood cost.
        likelihood = -n_snapshots * p * (log_geo - log_arith)
        penalty = 0.5 * k * (2 * m - k) * np.log(max(n_snapshots, 2))
        mdl = likelihood + penalty
        if mdl < best_mdl:
            best_mdl = mdl
            best_k = k
    return max(1, min(best_k, upper))


def estimate_window_delays_music(
    segment: np.ndarray,
    *,
    bandwidth_hz: float,
    subarray_ratio: float = 0.586,
    max_order: int = 40,
    min_delay_bin: int = 0,
    max_delay_bin: int | None = None,
    peak_rel_threshold: float = 0.15,
    max_paths: int = 30,
    n_tau_points: int | None = None,
) -> list[MusicDelayEstimate]:
    """Estimate delay-domain MPCs in one slow-time window via MUSIC.

    Parameters
    ----------
    segment :
        Complex CIR window, shape ``(n_slow, n_delay)``.
    bandwidth_hz :
        Signal bandwidth; the CIR delay-bin spacing is ``1 / bandwidth_hz``.
    subarray_ratio :
        Smoothing sub-array length as a fraction of the frequency points
        (MATLAB used 600/1024 ≈ 0.586).
    min_delay_bin, max_delay_bin :
        Keep only peaks whose delay bin lies in ``[min_delay_bin, max_delay_bin)``
        (the geometric LOS gate in the reference).
    peak_rel_threshold :
        Peak detection floor as a fraction of the pseudospectrum dynamic range
        above its minimum (MATLAB used 0.15).
    """
    if segment.ndim != 2:
        raise ValueError(f"segment must be 2D, got shape={segment.shape}")
    n_slow, n_delay = segment.shape
    if n_slow == 0 or n_delay == 0:
        return []

    cir_avg = np.mean(segment.astype(np.complex128), axis=0)
    hf = np.fft.fft(cir_avg)
    n_freq = hf.size
    m = int(round(float(subarray_ratio) * n_freq))
    m = max(2, min(m, n_freq - 1))

    rxx, n_snap = _forward_backward_covariance(hf, m)
    # Hermitian eigendecomposition (ascending), then take descending order.
    eigenvalues, eigenvectors = np.linalg.eigh(rxx)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    d = _mdl_order(eigenvalues, n_snap, max_order)
    noise_subspace = eigenvectors[:, d:]  # M x (M - d)
    if noise_subspace.shape[1] == 0:
        return []

    # Steering only depends on sub-band frequency spacing; the absolute carrier
    # cancels in |a^H E_n|, so use w = 2*pi * k * df.
    df = float(bandwidth_hz) / float(n_freq - 1)
    w = 2.0 * np.pi * df * np.arange(m, dtype=np.float64)
    max_delay_scan = float(n_freq - 1) / float(bandwidth_hz)
    n_tau = int(n_tau_points or n_freq)
    tau_scan = np.linspace(0.0, max_delay_scan, n_tau)

    steering = np.exp(-1j * np.outer(w, tau_scan))  # (M, n_tau)
    projected = noise_subspace.conj().T @ steering  # (M-d, n_tau)
    denom = np.sum(np.abs(projected) ** 2, axis=0)
    p_music = 1.0 / np.clip(denom, 1e-30, None)
    p_db = 10.0 * np.log10(p_music)

    height = float(np.min(p_db) + peak_rel_threshold * (np.max(p_db) - np.min(p_db)))
    peak_idx, _ = find_peaks(p_db, height=height)
    if peak_idx.size == 0:
        return []

    pdp_db = 20.0 * np.log10(np.abs(cir_avg) + 1e-30)
    hi_bin = int(max_delay_bin) if max_delay_bin is not None else n_delay
    results: list[MusicDelayEstimate] = []
    seen_bins: set[int] = set()
    # Strongest pseudospectrum peaks first.
    for ti in peak_idx[np.argsort(p_db[peak_idx])[::-1]]:
        delay_bin = int(round(tau_scan[ti] * bandwidth_hz))
        if delay_bin < int(min_delay_bin) or delay_bin >= hi_bin:
            continue
        # Snap to the local PDP maximum within +/-1 bin (reference behaviour).
        lo = max(0, delay_bin - 1)
        hi = min(n_delay - 1, delay_bin + 1)
        snapped = lo + int(np.argmax(pdp_db[lo : hi + 1]))
        if snapped in seen_bins:
            continue
        seen_bins.add(snapped)
        results.append(
            MusicDelayEstimate(
                delay_bin=snapped,
                delay_ns=float(snapped / float(bandwidth_hz) * 1e9),
                power_db=float(pdp_db[snapped]),
            )
        )
        if len(results) >= int(max_paths):
            break
    # Report delay-ascending for stable downstream consumption.
    results.sort(key=lambda r: r.delay_bin)
    return results
