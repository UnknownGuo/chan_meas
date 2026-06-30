from __future__ import annotations

import numpy as np


def regularized_frequency_calibrate(
    measured_cir: np.ndarray,
    b2b_cir: np.ndarray,
    *,
    regularization: float = 1e-3,
    axis: int = -1,
    attenuation_db: float = 0.0,
) -> np.ndarray:
    """Remove B2B system response with regularized frequency-domain division.

    This implements a Wiener/Tikhonov-style stable inverse:

        H_cal = H_meas * conj(H_b2b) / (|H_b2b|^2 + lambda)

    where lambda is interpreted relative to max(|H_b2b|^2) when
    ``regularization < 1``.  The function works for a single CIR vector or a
    stack of CIRs; B2B response is broadcast along non-delay dimensions.

    ``attenuation_db`` compensates for a fixed attenuator that was inserted
    only while recording the B2B reference (e.g. to avoid receiver
    saturation on a direct cable connection) and is absent from the real
    measurement chain. The B2B reference amplitude is scaled up by this
    amount before the division, so the result reflects the true
    (un-attenuated) system gain instead of inheriting the attenuator's loss
    as spurious output gain.
    """
    measured = np.asarray(measured_cir)
    b2b = np.asarray(b2b_cir, dtype=np.complex128)
    if attenuation_db:
        b2b = b2b * (10.0 ** (float(attenuation_db) / 20.0))
    if measured.shape[axis] != b2b.shape[-1]:
        raise ValueError(
            f"delay dimension mismatch: measured axis {axis} has {measured.shape[axis]} bins, "
            f"b2b has {b2b.shape[-1]} bins"
        )
    # B2B 参考的频域响应只需计算一次（小），measured 才是大头。
    h_b2b = np.fft.fft(b2b, axis=-1)
    power = np.abs(h_b2b) ** 2
    lam = float(regularization)
    if lam < 0:
        raise ValueError("regularization must be non-negative")
    if lam < 1.0:
        lam = lam * float(np.max(power) + 1e-30)
    denom = power + lam + 1e-30

    # 单条 CIR：直接处理。
    if measured.ndim == 1:
        h_meas = np.fft.fft(measured.astype(np.complex128), axis=axis)
        h_cal = h_meas * np.conj(h_b2b) / denom
        return np.fft.ifft(h_cal, axis=axis).astype(np.complex64)

    # 堆叠 CIR（n_frames, n_delay）：沿帧轴分块、原地写回 complex64，
    # 避免一次性分配整段 complex128 副本（大数据集会 OOM，见报告）。每帧校准相互独立。
    shape = [1] * measured.ndim
    shape[axis] = h_b2b.shape[-1]
    h_b2b_b = np.conj(h_b2b).reshape(shape)
    denom_b = denom.reshape(shape)
    out = measured if measured.dtype == np.complex64 else measured.astype(np.complex64)
    chunk = 4096
    for lo in range(0, measured.shape[0], chunk):
        hi = min(lo + chunk, measured.shape[0])
        m = measured[lo:hi].astype(np.complex128)
        h_meas = np.fft.fft(m, axis=axis)
        h_cal = h_meas * h_b2b_b / denom_b
        out[lo:hi] = np.fft.ifft(h_cal, axis=axis).astype(np.complex64)
    return out


def normalize_pulse_kernel(kernel: np.ndarray) -> np.ndarray:
    """Normalize a complex pulse kernel so the strongest tap has unit magnitude."""
    arr = np.asarray(kernel, dtype=np.complex128)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("kernel must be a non-empty 1D array")
    peak = int(np.argmax(np.abs(arr)))
    ref = arr[peak]
    if abs(ref) <= 1e-30:
        raise ValueError("kernel peak is zero")
    return (arr / ref).astype(np.complex128)
