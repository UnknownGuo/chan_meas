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
    measured = np.asarray(measured_cir, dtype=np.complex128)
    b2b = np.asarray(b2b_cir, dtype=np.complex128)
    if attenuation_db:
        b2b = b2b * (10.0 ** (float(attenuation_db) / 20.0))
    if measured.shape[axis] != b2b.shape[-1]:
        raise ValueError(
            f"delay dimension mismatch: measured axis {axis} has {measured.shape[axis]} bins, "
            f"b2b has {b2b.shape[-1]} bins"
        )
    h_meas = np.fft.fft(measured, axis=axis)
    h_b2b = np.fft.fft(b2b, axis=-1)
    power = np.abs(h_b2b) ** 2
    lam = float(regularization)
    if lam < 0:
        raise ValueError("regularization must be non-negative")
    if lam < 1.0:
        lam = lam * float(np.max(power) + 1e-30)
    denom = power + lam + 1e-30
    # reshape b2b frequency response for broadcasting if measured is stacked
    if measured.ndim > 1:
        shape = [1] * measured.ndim
        shape[axis] = h_b2b.shape[-1]
        h_b2b_b = h_b2b.reshape(shape)
        denom_b = denom.reshape(shape)
    else:
        h_b2b_b = h_b2b
        denom_b = denom
    h_cal = h_meas * np.conj(h_b2b_b) / denom_b
    return np.fft.ifft(h_cal, axis=axis).astype(np.complex128)


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
