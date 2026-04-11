"""
Reader for Luoyang 10ms frame format .bin files.

This module provides a class to read and parse the specific binary format,
extracting raw IQ data without performing any signal processing.

Frame Format (61476 B/frame, p=15):
  - bytes 0-1  : Frame header identifier (unused)
  - bytes 5-6  : Frame length (uint16, big-endian), used for validation
  - byte 32+   : IQ data, p*U*4 bytes, [Q_hi, Q_lo, I_hi, I_lo] per sample
  - p=15, U=1024 -> 15*1024*4 = 61440 bytes of IQ data.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np


class LuoyangBinReader:
    """
    Reads and parses Luoyang 10ms .bin files into IQ data sequences.

    Single responsibility: file I/O and byte-level parsing only.
    Returns structured NumPy arrays of complex IQ samples ready for
    downstream signal processing.
    """

    _U: int = 1024                  # samples per LFM sequence
    _P_SEQS: int = 15               # LFM repetitions per frame
    _IQ_START_OFFSET: int = 32      # byte offset where IQ data starts
    _NOMINAL_FRAME_LEN: int = 61476 # nominal frame length in bytes
    _BYTES_PER_SAMPLE: int = 4      # bytes per IQ sample (int16 I + int16 Q)

    def read_iq_sequences(
        self,
        path: Path,
        max_frames: Optional[int] = None,
    ) -> np.ndarray:
        """
        Load a Luoyang .bin file and return per-sequence IQ data.

        Parameters
        ----------
        path : Path
            Path to the .bin file.
        max_frames : Optional[int]
            Maximum number of frames to load. None loads all frames.

        Returns
        -------
        np.ndarray
            Complex IQ data of shape (n_frames, P_SEQS, U), dtype complex64.

        Raises
        ------
        ValueError
            If the file is too small or contains no complete frames.
        """
        raw_bytes = np.fromfile(path, dtype=np.uint8)
        raw_frames = self._reshape_into_frames(path, raw_bytes, max_frames)
        return self._parse_iq(raw_frames)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reshape_into_frames(
        self,
        path: Path,
        raw_bytes: np.ndarray,
        max_frames: Optional[int],
    ) -> np.ndarray:
        """Reshape the flat byte array into (n_frames, frame_len)."""
        if len(raw_bytes) < self._NOMINAL_FRAME_LEN:
            raise ValueError(
                f"File {path} is too small (requires >= {self._NOMINAL_FRAME_LEN} bytes)."
            )

        frame_len = self._parse_frame_len(raw_bytes)
        n_frames = len(raw_bytes) // frame_len

        if n_frames == 0:
            raise ValueError(
                f"File {path} contains no complete frames (frame_len={frame_len})."
            )

        if max_frames is not None and max_frames > 0:
            n_frames = min(n_frames, max_frames)

        return raw_bytes[: n_frames * frame_len].reshape(n_frames, frame_len)

    def _parse_frame_len(self, raw_bytes: np.ndarray) -> int:
        """Parse frame length from bytes 5-6 of the first frame (big-endian)."""
        frame_len = int(raw_bytes[5]) * 256 + int(raw_bytes[6])

        if frame_len == 0:
            return self._NOMINAL_FRAME_LEN  # header field zeroed; use nominal

        if frame_len != self._NOMINAL_FRAME_LEN:
            warnings.warn(
                f"Parsed frame_len={frame_len} B differs from nominal "
                f"{self._NOMINAL_FRAME_LEN} B. Proceeding with parsed value.",
                UserWarning,
                stacklevel=4,
            )
        return frame_len

    def _parse_iq(self, frames: np.ndarray) -> np.ndarray:
        """
        Decode IQ bytes from frames into complex64 samples.

        Byte layout per sample: [Q_hi, Q_lo, I_hi, I_lo] (big-endian, Q first).

        Returns
        -------
        np.ndarray
            Shape (n_frames, P_SEQS, U), dtype complex64.
        """
        n_frames = frames.shape[0]
        byte_count = self._P_SEQS * self._U * self._BYTES_PER_SAMPLE

        iq_bytes = frames[:, self._IQ_START_OFFSET : self._IQ_START_OFFSET + byte_count]
        iq = iq_bytes.reshape(n_frames, self._P_SEQS * self._U, self._BYTES_PER_SAMPLE).astype(np.int32)

        def _decode_int16(hi: np.ndarray, lo: np.ndarray) -> np.ndarray:
            raw = hi * 256 + lo
            return np.where(raw > 32767, raw - 65536, raw).astype(np.float32) / 32767.0

        i_ch = _decode_int16(iq[:, :, 2], iq[:, :, 3])  # bytes 2,3
        q_ch = _decode_int16(iq[:, :, 0], iq[:, :, 1])  # bytes 0,1

        return (i_ch + 1j * q_ch).astype(np.complex64).reshape(n_frames, self._P_SEQS, self._U)
