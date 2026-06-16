"""Raw .bin measurement data → CIR conversion.

Reads binary frames, parses IQ/GPS fields, and applies the matched-filter
sliding correlation to produce the raw (uncalibrated) CIR.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import torch

# ── Hardware constants ────────────────────────────────────────────────────────

FS_HZ = 100_000_000  # ADC sample rate, Hz
BW_HZ = 50e6         # signal bandwidth, Hz
ATT_B2B_DB = 40.0   # standard B2B attenuator, dB
FRAME_RATE_HZ = 100.0  # frame repetition rate, Hz (10 ms / frame)

# ── Frame layout ──────────────────────────────────────────────────────────────

FRAME_LEN = 4132
U = 1024  # IQ samples / CIR bins

_LON_BYTES = slice(12, 16)
_LAT_BYTES = slice(17, 21)
_ALT_BYTES = slice(22, 24)
_HOUR_IDX = 24
_MIN_IDX = 25
_SEC_IDX = 26
_IQ_START = 32  # 0-indexed byte offset of first IQ sample in frame

# ── LFM matched filter ────────────────────────────────────────────────────────


def _build_matched_filter() -> np.ndarray:
    n = np.arange(U, dtype=np.float64)
    S = np.exp(1j * np.pi * n**2 / U)
    return np.conj(S[::-1]).astype(np.complex64)


_S_MATCHED = _build_matched_filter()

# ── GPU setup ─────────────────────────────────────────────────────────────────

_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_N_FFT = 1 << math.ceil(math.log2(3 * U + U - 1))  # = 4096
_S_MATCHED_F_GPU: torch.Tensor = torch.fft.fft(
    torch.from_numpy(_S_MATCHED).to(_DEVICE), n=_N_FFT
)


# ── Frame I/O ─────────────────────────────────────────────────────────────────


def _load_frames(path: Path, max_frames: Optional[int] = None) -> np.ndarray:
    """Load .bin frames from file or directory → (n_frames, FRAME_LEN) uint8."""
    if path.is_file():
        raw = np.fromfile(path, dtype=np.uint8)
    else:
        chunks = [np.fromfile(f, dtype=np.uint8) for f in sorted(path.glob("*.bin"))]
        if not chunks:
            raise FileNotFoundError(f"No .bin files found in {path}")
        raw = np.concatenate(chunks)

    n_frames = len(raw) // FRAME_LEN
    if n_frames == 0:
        raise ValueError(f"{path}: too small for even one frame (FRAME_LEN={FRAME_LEN})")
    if max_frames is not None and max_frames > 0:
        n_frames = min(n_frames, max_frames)
    return raw[: n_frames * FRAME_LEN].reshape(n_frames, FRAME_LEN)


def _parse_iq(frames: np.ndarray) -> np.ndarray:
    """Extract complex IQ from frames → (n_frames, U) complex64."""
    iq = frames[:, _IQ_START : _IQ_START + 4 * U].reshape(-1, U, 4).astype(np.int32)

    def to_float(hi, lo):
        raw = hi * 256 + lo
        return np.where(raw > 32767, raw - 65536, raw).astype(np.float32) / 32767.0

    I = to_float(iq[:, :, 2], iq[:, :, 3])
    Q = to_float(iq[:, :, 0], iq[:, :, 1])
    return (I + 1j * Q).astype(np.complex64)


def _parse_gps(frames: np.ndarray) -> Dict[str, np.ndarray]:
    """Extract GPS fields from frames → dict with lat/lon/alt/hour/minute/second."""

    def bytes_to_int32(s: slice) -> np.ndarray:
        b = frames[:, s].astype(np.uint32)
        u32 = b[:, 0] << 24 | b[:, 1] << 16 | b[:, 2] << 8 | b[:, 3]
        return u32.view(np.int32).astype(np.float64)

    def ddmm_to_deg(raw: np.ndarray) -> np.ndarray:
        dm = raw * 1e-7
        deg = np.floor(dm)
        return deg + (dm - deg) * 100.0 / 60.0

    alt_b = frames[:, _ALT_BYTES].astype(np.float64)
    return {
        "lat": ddmm_to_deg(bytes_to_int32(_LAT_BYTES)),
        "lon": ddmm_to_deg(bytes_to_int32(_LON_BYTES)),
        "alt": (alt_b[:, 0] * 256 + alt_b[:, 1]) * 0.1,
        "hour": frames[:, _HOUR_IDX].astype(np.uint8),
        "minute": frames[:, _MIN_IDX].astype(np.uint8),
        "second": frames[:, _SEC_IDX].astype(np.uint8),
    }


# ── Signal processing ─────────────────────────────────────────────────────────


def _sliding_correlate(iq: np.ndarray) -> np.ndarray:
    """DC-remove → tile×3 → FFT matched-filter → (n_frames, U) complex64.

    Uses GPU (CUDA) when available; falls back to CPU torch.fft otherwise.
    """
    t = torch.from_numpy(iq).to(_DEVICE)
    t = t - t.mean(dim=1, keepdim=True)          # DC removal
    ext = t.repeat(1, 3)                          # (n_frames, 3U)

    F = torch.fft.fft(ext, n=_N_FFT, dim=1) * _S_MATCHED_F_GPU
    corr = torch.fft.ifft(F, dim=1)

    result = (corr[:, 2 * U - 1 : 3 * U - 1] / U).to(torch.complex64)
    return result.cpu().numpy()


# ── Public API ────────────────────────────────────────────────────────────────


def read_bin_to_cir(
    path: Path,
    max_frames: Optional[int] = None,
) -> tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Read a .bin file (or directory) → (cir_raw, gps).

    Parameters
    ----------
    path       : .bin file or directory containing .bin files
    max_frames : optional frame limit (truncates silently)

    Returns
    -------
    cir_raw : (n_frames, U) complex64 — raw (uncalibrated) CIR
    gps     : dict with keys lat, lon, alt, hour, minute, second
    """
    frames = _load_frames(path, max_frames)
    gps = _parse_gps(frames)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    return cir, gps
