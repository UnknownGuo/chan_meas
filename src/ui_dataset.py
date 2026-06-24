"""Frontend/UI data export helpers for channel measurement analysis.

This module intentionally contains no HTML/UI code.  It converts existing
measurement-processing outputs (GPS + CIR) into a compact JSON-friendly contract
that an HTML dashboard, notebook, FastAPI endpoint, or Electron/PyWebView shell
can consume later.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.io.bin_read import BW_HZ, FRAME_RATE_HZ, U, _load_frames, _parse_gps, _parse_iq, _sliding_correlate
from src.signal.delay_doppler_sage import estimate_window_paths
from src.signal.music_delay import estimate_window_delays_music
from src.signal.sage_adaptive import estimate_window_paths_adaptive
from src.calibration.b2b_frequency import regularized_frequency_calibrate


@dataclass(frozen=True)
class TxGps:
    """Static transmitter GPS point used by the UI data contract."""

    lat: float
    lon: float
    alt: float = 0.0
    accuracy: float | None = None
    source: str | None = None


DEFAULT_ZJK_TX_GPS = TxGps(
    lat=40.303232,
    lon=115.771857,
    alt=561.41,
    accuracy=3.79,
    source="/mnt/win_data/data_mea/zjk_mea/TX_GPS",
)


def _finite_float(value: Any, default: float = 0.0, digits: int | None = None) -> float:
    """Return a JSON-safe finite float, replacing NaN/inf with default."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    if not math.isfinite(out):
        out = default
    if digits is not None:
        out = round(out, digits)
    return out


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle horizontal distance in meters."""
    radius_m = 6_371_000.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * radius_m * math.asin(math.sqrt(a))


def distance_3d_m(tx: TxGps, rx_lat: float, rx_lon: float, rx_alt: float | None = None) -> float:
    """Approximate 3D Tx-Rx distance in meters using haversine + altitude delta."""
    horizontal = haversine_m(tx.lat, tx.lon, rx_lat, rx_lon)
    if rx_alt is None:
        return horizontal
    dz = float(rx_alt) - float(tx.alt)
    return math.sqrt(horizontal * horizontal + dz * dz)


def load_tx_gps(path: str | Path | None = None) -> TxGps:
    """Load static Tx GPS.

    Supported machine-readable format is JSON with `lat`, `lon`, and optional
    `alt`/`accuracy`.  The current zjk_mea `TX_GPS` artifact is a JPEG screenshot,
    so image-like/binary files fall back to the manually verified coordinate from
    that screenshot.
    """
    if path is None:
        return DEFAULT_ZJK_TX_GPS

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Tx GPS file not found: {p}")

    raw = p.read_bytes()
    is_jsonish = p.suffix.lower() == ".json" or raw[:1] in (b"{", b"[")
    if is_jsonish:
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, list):
            if not payload:
                raise ValueError(f"Tx GPS JSON list is empty: {p}")
            payload = payload[0]
        return TxGps(
            lat=_finite_float(payload["lat"]),
            lon=_finite_float(payload.get("lon", payload.get("lng"))),
            alt=_finite_float(payload.get("alt", payload.get("altitude", 0.0))),
            accuracy=None if payload.get("accuracy") is None else _finite_float(payload.get("accuracy")),
            source=str(p),
        )

    # Known current artifact: a GPS-toolbox JPEG screenshot under zjk_mea/TX_GPS.
    return TxGps(
        lat=DEFAULT_ZJK_TX_GPS.lat,
        lon=DEFAULT_ZJK_TX_GPS.lon,
        alt=DEFAULT_ZJK_TX_GPS.alt,
        accuracy=DEFAULT_ZJK_TX_GPS.accuracy,
        source=str(p),
    )


def compute_frame_stats(
    cir: np.ndarray,
    gps: Mapping[str, np.ndarray],
    tx_gps: TxGps,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    path_threshold_db: float = -60.0,
) -> list[dict[str, Any]]:
    """Compute per-frame UI statistics from CIR and GPS arrays."""
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")

    power = np.abs(cir).astype(np.float64) ** 2
    power_db = 10.0 * np.log10(power + 1e-30)
    peak_bins = np.argmax(power, axis=1)
    delay_ns = np.arange(cir.shape[1], dtype=np.float64) / float(bandwidth_hz) * 1e9

    stats: list[dict[str, Any]] = []
    for frame_idx in range(cir.shape[0]):
        p = power[frame_idx]
        p_db = power_db[frame_idx]
        peak_bin = int(peak_bins[frame_idx])
        total_power = float(np.sum(p))
        if total_power > 0.0:
            mean_delay = float(np.sum(delay_ns * p) / total_power)
            rms_delay = float(np.sqrt(np.sum(((delay_ns - mean_delay) ** 2) * p) / total_power))
        else:
            rms_delay = 0.0

        rx_lat = _finite_float(gps["lat"][frame_idx])
        rx_lon = _finite_float(gps["lon"][frame_idx])
        rx_alt = _finite_float(gps.get("alt", np.zeros(cir.shape[0]))[frame_idx])
        distance_m = distance_3d_m(tx_gps, rx_lat, rx_lon, rx_alt)
        peak_power_db = _finite_float(p_db[peak_bin], digits=6)

        stats.append(
            {
                "frame": frame_idx,
                "timeSec": _finite_float(frame_idx / float(frame_rate_hz), digits=6),
                "distanceM": _finite_float(distance_m, digits=3),
                "peakPowerDb": peak_power_db,
                "peakDelayNs": _finite_float(delay_ns[peak_bin], digits=3),
                "meanPowerDb": _finite_float(10.0 * np.log10(float(np.mean(p)) + 1e-30), digits=6),
                "rmsDelayNs": _finite_float(rms_delay, digits=3),
                "pathCount": int(np.count_nonzero(p_db >= peak_power_db + float(path_threshold_db))),
            }
        )
    return stats


def downsample_cir_power_db(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    max_delay_bins: int = 256,
    relative_to_frame_peak: bool = False,
    time_step_frames: int | None = None,
) -> tuple[list[float], list[list[float]]]:
    """Return delay axis and compact power-dB matrix for frontend heatmaps.

    If ``time_step_frames`` is set, temporally decimate the CIR so the waterfall
    shows one row every ``time_step_frames`` frames (e.g. 100 for 1 frame/second
    at 100 Hz).
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    n_frames, n_delay = cir.shape
    if max_delay_bins <= 0:
        raise ValueError("max_delay_bins must be positive")
    step = max(1, int(math.ceil(n_delay / max_delay_bins)))
    idx = np.arange(0, n_delay, step, dtype=np.int64)[:max_delay_bins]
    # temporal decimation
    if time_step_frames is not None and time_step_frames > 1:
        t_idx = np.arange(0, n_frames, int(time_step_frames), dtype=np.int64)
        cir_ds = cir[t_idx, :]
    else:
        cir_ds = cir
    power_db = 10.0 * np.log10(np.abs(cir_ds[:, idx]).astype(np.float64) ** 2 + 1e-30)
    if relative_to_frame_peak:
        full_power_db = 10.0 * np.log10(np.abs(cir_ds).astype(np.float64) ** 2 + 1e-30)
        power_db = power_db - np.max(full_power_db, axis=1, keepdims=True)
    delay_ns = (idx.astype(np.float64) / float(bandwidth_hz) * 1e9).round(3).tolist()
    return delay_ns, np.round(power_db, 3).tolist()


def _rx_gps_records(gps: Mapping[str, np.ndarray], frame_rate_hz: float) -> list[dict[str, Any]]:
    n_frames = len(gps["lat"])
    return [_rx_gps_record(gps, frame_idx, frame_rate_hz) for frame_idx in range(n_frames)]


def _rx_gps_record(gps: Mapping[str, np.ndarray], frame_idx: int, frame_rate_hz: float) -> dict[str, Any]:
    n_frames = len(gps["lat"])
    return {
        "frame": frame_idx,
        "timeSec": _finite_float(frame_idx / frame_rate_hz, digits=6),
        "lat": _finite_float(gps["lat"][frame_idx], digits=9),
        "lon": _finite_float(gps["lon"][frame_idx], digits=9),
        "alt": _finite_float(gps.get("alt", np.zeros(n_frames))[frame_idx], digits=3),
        "hour": int(gps.get("hour", np.zeros(n_frames, dtype=np.uint8))[frame_idx]),
        "minute": int(gps.get("minute", np.zeros(n_frames, dtype=np.uint8))[frame_idx]),
        "second": int(gps.get("second", np.zeros(n_frames, dtype=np.uint8))[frame_idx]),
    }


def compute_pdp_curve(
    cir: np.ndarray,
    *,
    frame_index: int,
    bandwidth_hz: float = BW_HZ,
    max_delay_bins: int = 512,
    relative: bool = False,
) -> dict[str, Any]:
    """Build the current-frame PDP curve payload for a line chart."""
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if not 0 <= frame_index < cir.shape[0]:
        raise IndexError(f"frame_index out of range: {frame_index}")
    delay_ns, matrix_db = downsample_cir_power_db(
        cir[frame_index : frame_index + 1],
        bandwidth_hz=bandwidth_hz,
        max_delay_bins=max_delay_bins,
        relative_to_frame_peak=relative,
    )
    full_power = np.abs(cir[frame_index]).astype(np.float64) ** 2
    full_power_db = 10.0 * np.log10(full_power + 1e-30)
    peak_bin = int(np.argmax(full_power))
    return {
        "frame": frame_index,
        "delayNs": delay_ns,
        "powerDb": matrix_db[0],
        "peakDelayNs": _finite_float(peak_bin / float(bandwidth_hz) * 1e9, digits=3),
        "peakPowerDb": _finite_float(full_power_db[peak_bin], digits=6),
        "relative": bool(relative),
    }


def compute_power_distribution(
    power_db: np.ndarray,
    *,
    relative_to_peak: bool = False,
) -> list[dict[str, Any]]:
    """Summarize a frame's power values into fixed dB bins for bar charts."""
    vals = np.asarray(power_db, dtype=np.float64).ravel()
    if vals.size == 0:
        vals = np.array([-300.0], dtype=np.float64)
    if relative_to_peak:
        vals = vals - float(np.nanmax(vals))
    vals = np.nan_to_num(vals, nan=-300.0, posinf=300.0, neginf=-300.0)
    specs = [
        (">-20", vals > -20.0),
        ("-20~-40", (vals <= -20.0) & (vals > -40.0)),
        ("-40~-60", (vals <= -40.0) & (vals > -60.0)),
        ("-60~-80", (vals <= -60.0) & (vals > -80.0)),
        ("<-80", vals <= -80.0),
    ]
    total = int(vals.size)
    out = []
    for label, mask in specs:
        count = int(np.count_nonzero(mask))
        out.append({"label": label, "count": count, "percent": round(count * 100.0 / total, 3)})
    return out


def compute_doppler_delay(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    max_delay_bins: int = 128,
    n_doppler_bins: int = 128,
    relative_to_peak: bool = False,
) -> dict[str, Any]:
    """Compute a compact Doppler-Delay power map using slow-time FFT.

    Rows are Doppler bins and columns are delay bins.  This is a direct DPSD-like
    diagnostic, not a SAGE/MUSIC estimator.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if max_delay_bins <= 0 or n_doppler_bins <= 0:
        raise ValueError("max_delay_bins and n_doppler_bins must be positive")
    n_frames, n_delay = cir.shape
    delay_step = max(1, int(math.ceil(n_delay / max_delay_bins)))
    delay_idx = np.arange(0, n_delay, delay_step, dtype=np.int64)[:max_delay_bins]
    n_fft = max(int(n_doppler_bins), n_frames)
    selected = cir[:, delay_idx]
    window = np.hanning(n_frames).astype(np.float64) if n_frames > 1 else np.ones(1, dtype=np.float64)
    spectrum = np.fft.fftshift(np.fft.fft(selected * window[:, None], n=n_fft, axis=0), axes=0)
    doppler_hz_full = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / float(frame_rate_hz)))
    if n_fft > n_doppler_bins:
        take = np.linspace(0, n_fft - 1, n_doppler_bins).round().astype(np.int64)
        spectrum = spectrum[take]
        doppler_hz = doppler_hz_full[take]
    else:
        doppler_hz = doppler_hz_full
    power_db = 20.0 * np.log10(np.abs(spectrum).astype(np.float64) + 1e-30)
    if relative_to_peak:
        power_db = power_db - float(np.max(power_db))
    return {
        "mock": False,
        "method": "slow_time_fft",
        "dopplerHz": np.round(doppler_hz, 3).tolist(),
        "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
        "powerDb": np.round(power_db, 3).tolist(),
    }

def compute_doppler_time_waterfall(
    cir: np.ndarray,
    *,
    frame_rate_hz: float = FRAME_RATE_HZ,
    window_size_frames: int | None = None,
    step_frames: int | None = None,
    max_delay_bins: int = 300,
    n_doppler_bins: int = 64,
    relative_to_peak: bool = False,
    use_hann_window: bool = False,
) -> dict[str, Any]:
    """Build a Doppler-Time waterfall by delay-averaging each DPSD window.

    This matches the requested MATLAB-style flow: compute Doppler-Delay Spectrum
    for each slow-time window, average over the delay domain, and stack each
    window's Doppler spectrum along time.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if max_delay_bins <= 0 or n_doppler_bins <= 0:
        raise ValueError("max_delay_bins and n_doppler_bins must be positive")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")
    win = int(round(frame_rate_hz)) if window_size_frames is None else int(window_size_frames)
    win = max(2, min(win, n_frames))
    step = win if step_frames is None else int(step_frames)
    step = max(1, int(step))
    starts = np.arange(0, n_frames - win + 1, step, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)
    delay_idx = np.arange(0, min(n_delay, int(max_delay_bins)), dtype=np.int64)
    spectra: list[np.ndarray] = []
    time_sec: list[float] = []
    for start_raw in starts:
        start = int(start_raw)
        end = min(start + win, n_frames)
        segment = cir[start:end, :][:, delay_idx]
        if segment.shape[0] < win:
            pad = np.zeros((win - segment.shape[0], segment.shape[1]), dtype=segment.dtype)
            segment = np.vstack([segment, pad])
        if use_hann_window:
            segment = segment * np.hanning(win).astype(np.float64)[:, None]
        spectrum = np.fft.fftshift(np.fft.fft(segment, n=int(n_doppler_bins), axis=0), axes=0)
        delay_avg = np.mean(np.abs(spectrum).astype(np.float64), axis=1)
        spectra.append(20.0 * np.log10(delay_avg + 1e-30))
        time_sec.append(round((start + win / 2.0) / float(frame_rate_hz), 6))
    power_db = np.stack(spectra, axis=1)
    if relative_to_peak:
        power_db = power_db - float(np.max(power_db))
    return {
        "mock": False,
        "method": "delay_averaged_doppler_time_fft",
        "windowSizeFrames": int(win),
        "stepFrames": int(step),
        "timeSec": time_sec,
        "dopplerHz": np.round(np.linspace(-float(frame_rate_hz) / 2.0, float(frame_rate_hz) / 2.0, int(n_doppler_bins)), 3).tolist(),
        "powerDb": np.round(power_db, 3).tolist(),
    }


def compute_doppler_delay_frame(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    frame_index: int | None = None,
    window_size_frames: int = 64,
    max_delay_bins: int = 300,
    n_doppler_bins: int = 64,
    relative_to_peak: bool = False,
    use_hann_window: bool = False,
) -> dict[str, Any]:
    """MATLAB-reference Doppler-Delay FFT map for one slow-time window.

    Mirrors the reference MATLAB pattern under ``matlab_code_reference/doppler_spectrum``:
    select a slow-time CIR block, run ``fft(..., [], slow_time_axis)`` for every
    delay bin, ``fftshift`` along Doppler, then draw ``imagesc(delay, doppler, DPSD)``.
    Frequency labels intentionally use ``linspace(-fs/2, fs/2, N)`` to match the
    MATLAB scripts' plotting convention.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if max_delay_bins <= 0 or n_doppler_bins <= 0 or window_size_frames <= 1:
        raise ValueError("max_delay_bins, n_doppler_bins, and window_size_frames must be positive")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")
    win = max(2, min(int(window_size_frames), n_frames))
    center = n_frames // 2 if frame_index is None else int(frame_index)
    center = max(0, min(center, n_frames - 1))
    start = max(0, center - win // 2)
    end = min(n_frames, start + win)
    start = max(0, end - win)
    delay_idx = np.arange(0, min(n_delay, int(max_delay_bins)), dtype=np.int64)
    segment = cir[start:end, :][:, delay_idx]
    if segment.shape[0] < win:
        pad = np.zeros((win - segment.shape[0], segment.shape[1]), dtype=segment.dtype)
        segment = np.vstack([segment, pad])
    if use_hann_window:
        segment = segment * np.hanning(win).astype(np.float64)[:, None]
    spectrum = np.fft.fftshift(np.fft.fft(segment, n=int(n_doppler_bins), axis=0), axes=0)
    power_db = 20.0 * np.log10(np.abs(spectrum).astype(np.float64) + 1e-30)
    if relative_to_peak:
        power_db = power_db - float(np.max(power_db))
    return {
        "mock": False,
        "method": "matlab_style_doppler_delay_fft",
        "frame": center,
        "windowStart": int(start),
        "windowEnd": int(end),
        "delayAxis": "delay_bin",
        "delayBins": delay_idx.astype(int).tolist(),
        "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
        "dopplerHz": np.round(np.linspace(-float(frame_rate_hz) / 2.0, float(frame_rate_hz) / 2.0, int(n_doppler_bins)), 3).tolist(),
        "powerDb": np.round(power_db, 3).tolist(),
    }



def _music_spectrum_1d(
    x: np.ndarray,
    *,
    frame_rate_hz: float,
    doppler_grid: np.ndarray,
    subspace_dim: int,
    signal_count: int,
) -> np.ndarray:
    """Estimate 1D temporal MUSIC pseudo-spectrum for one delay-bin series."""
    series = np.asarray(x, dtype=np.complex128).ravel()
    n = series.size
    m = int(max(2, min(subspace_dim, n // 2)))
    k = n - m + 1
    if k <= 1:
        return np.zeros_like(doppler_grid, dtype=np.float64)
    hankel = np.stack([series[i : i + m] for i in range(k)], axis=1)
    cov = hankel @ hankel.conj().T / float(k)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvecs = eigvecs[:, order]
    n_signal = int(max(1, min(signal_count, m - 1)))
    noise = eigvecs[:, n_signal:]
    samples = np.arange(m, dtype=np.float64)
    steering = np.exp(1j * 2.0 * np.pi * doppler_grid[:, None] * samples[None, :] / float(frame_rate_hz))
    denom = np.sum(np.abs(steering.conj() @ noise) ** 2, axis=1)
    return 1.0 / np.maximum(denom, 1e-30)


def compute_music_mpc(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    frame_index: int | None = None,
    window_size: int = 64,
    max_delay_bins: int = 128,
    doppler_min_hz: float = -50.0,
    doppler_max_hz: float = 50.0,
    n_doppler_bins: int = 201,
    num_paths: int = 8,
    subspace_dim: int = 16,
    signal_count: int = 1,
    min_separation_delay_bins: int = 1,
    min_separation_doppler_bins: int = 2,
    min_peak_relative_db: float = 20.0,
    relative_to_peak: bool = False,
) -> dict[str, Any]:
    """Lightweight MUSIC MPC estimator.

    This estimates Doppler via 1D MUSIC independently on selected delay bins.
    Delay remains on the CIR delay-bin grid.  It is a practical first MUSIC layer
    for the UI, not the full MATLAB SAGE plane-wave estimator.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    n_frames, n_delay = cir.shape
    if n_frames < 4:
        raise ValueError("MUSIC requires at least 4 frames")
    if max_delay_bins <= 0 or n_doppler_bins <= 0 or num_paths <= 0:
        raise ValueError("max_delay_bins, n_doppler_bins, and num_paths must be positive")

    center = n_frames // 2 if frame_index is None else int(frame_index)
    center = max(0, min(center, n_frames - 1))
    win = max(4, min(int(window_size), n_frames))
    start = max(0, center - win // 2)
    end = min(n_frames, start + win)
    start = max(0, end - win)
    segment = cir[start:end]

    delay_step = max(1, int(math.ceil(n_delay / max_delay_bins)))
    delay_idx = np.arange(0, n_delay, delay_step, dtype=np.int64)[:max_delay_bins]
    doppler_grid = np.linspace(float(doppler_min_hz), float(doppler_max_hz), int(n_doppler_bins))

    spectrum = np.zeros((doppler_grid.size, delay_idx.size), dtype=np.float64)
    mean_power = np.mean(np.abs(segment[:, delay_idx]) ** 2, axis=0)
    active_order = np.argsort(mean_power)[::-1]
    # Limit expensive eigendecompositions to bins that can plausibly hold paths.
    active_count = min(delay_idx.size, max(num_paths * 4, 16))
    active_cols = set(int(i) for i in active_order[:active_count])
    for col, d_idx in enumerate(delay_idx):
        if col not in active_cols or mean_power[col] <= 0.0:
            continue
        spectrum[:, col] = _music_spectrum_1d(
            segment[:, d_idx],
            frame_rate_hz=frame_rate_hz,
            doppler_grid=doppler_grid,
            subspace_dim=subspace_dim,
            signal_count=signal_count,
        )
        spectrum[:, col] *= float(mean_power[col])

    raw_db = 10.0 * np.log10(spectrum + 1e-30)
    mean_power_db = 10.0 * np.log10(mean_power + 1e-30)
    col_max = np.max(raw_db, axis=0, keepdims=True)
    # Use MUSIC to localize Doppler within a delay bin, but rank paths by both
    # MUSIC score and actual delay-bin power so weak pure tones do not outrank
    # physically stronger paths just because their grid frequency lands exactly.
    spectrum_db = (raw_db - col_max) + mean_power_db[None, :]
    if relative_to_peak:
        spectrum_db -= float(np.max(spectrum_db))

    candidates: list[tuple[float, int, int]] = []
    for dop_idx in range(spectrum_db.shape[0]):
        for delay_col in range(spectrum_db.shape[1]):
            candidates.append((float(spectrum_db[dop_idx, delay_col]), dop_idx, delay_col))
    candidates.sort(reverse=True, key=lambda item: item[0])

    chosen: list[tuple[float, int, int]] = []
    for score_db, dop_idx, delay_col in candidates:
        if len(chosen) >= num_paths:
            break
        if not np.isfinite(score_db):
            continue
        too_close = any(
            abs(delay_col - old_delay) <= min_separation_delay_bins
            and abs(dop_idx - old_dop) <= min_separation_doppler_bins
            for _, old_dop, old_delay in chosen
        )
        if too_close:
            continue
        chosen.append((score_db, dop_idx, delay_col))

    peaks = []
    for path_id, (score_db, dop_idx, delay_col) in enumerate(chosen, start=1):
        d_idx = int(delay_idx[delay_col])
        frame_power = np.abs(cir[center, d_idx]) ** 2
        peaks.append(
            {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "delayNs": _finite_float(d_idx / float(bandwidth_hz) * 1e9, digits=3),
                "dopplerHz": _finite_float(doppler_grid[dop_idx], digits=3),
                "musicScoreDb": _finite_float(score_db, digits=3),
                "powerDb": _finite_float(10.0 * np.log10(frame_power + 1e-30), digits=6),
                "pathId": path_id,
                "mock": False,
            }
        )

    return {
        "mock": False,
        "method": "music_doppler_per_delay",
        "frame": center,
        "windowStart": start,
        "windowEnd": end,
        "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
        "dopplerHz": np.round(doppler_grid, 3).tolist(),
        "spectrumDb": np.round(spectrum_db, 3).tolist(),
        "peaks": peaks,
    }


def distance_to_delay_ns(distance_m: float) -> float:
    """Convert one-way propagation distance in meters to delay in nanoseconds."""
    return _finite_float(float(distance_m) / 299_792_458.0 * 1e9, digits=6)


def _select_joint_peaks(
    power_db: np.ndarray,
    *,
    max_peaks: int,
    min_separation_delay_bins: int = 1,
    min_separation_doppler_bins: int = 2,
) -> list[tuple[float, int, int]]:
    """Greedy 2D peak selection on a Doppler-delay power map.

    Returns tuples of (score_db, doppler_idx, delay_col).
    """
    if max_peaks <= 0:
        return []
    flat_order = np.argsort(power_db.ravel())[::-1]
    chosen: list[tuple[float, int, int]] = []
    for flat_idx in flat_order:
        dop_idx, delay_col = np.unravel_index(int(flat_idx), power_db.shape)
        score_db = float(power_db[dop_idx, delay_col])
        if not np.isfinite(score_db):
            continue
        too_close = any(
            abs(delay_col - old_delay) <= min_separation_delay_bins
            and abs(dop_idx - old_dop) <= min_separation_doppler_bins
            for _, old_dop, old_delay in chosen
        )
        if too_close:
            continue
        chosen.append((score_db, int(dop_idx), int(delay_col)))
        if len(chosen) >= max_peaks:
            break
    return chosen


def compute_joint_delay_doppler_tracks(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    window_size_frames: int | None = None,
    step_frames: int | None = None,
    delay_gate_distance_m: float = 2000.0,
    max_delay_bins: int = 256,
    n_doppler_bins: int | None = None,
    max_paths: int = 15,
    relative_to_peak: bool = False,
    use_hann_window: bool = True,
    min_separation_delay_bins: int = 1,
    min_separation_doppler_bins: int = 2,
    min_peak_relative_db: float = 20.0,
) -> dict[str, Any]:
    """Jointly estimate delay and Doppler per time window using a 2D FFT map.

    The delay axis is restricted by a physical one-way distance gate (default 2000 m,
    converted to propagation delay), and each analysis window is typically one second
    long. For each window we keep the strongest local peaks on the Doppler-delay map.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if max_delay_bins <= 0 or max_paths <= 0:
        raise ValueError("max_delay_bins and max_paths must be positive")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")

    win = int(round(frame_rate_hz)) if window_size_frames is None else int(window_size_frames)
    win = max(4, min(win, n_frames))
    step = win if step_frames is None else int(step_frames)
    step = max(1, step)
    n_fft = max(int(n_doppler_bins) if n_doppler_bins is not None else win, win)

    gate_ns_max = distance_to_delay_ns(delay_gate_distance_m)
    delay_axis_ns = np.arange(n_delay, dtype=np.float64) / float(bandwidth_hz) * 1e9
    delay_mask = (delay_axis_ns >= 0.0) & (delay_axis_ns <= gate_ns_max)
    delay_idx_full = np.flatnonzero(delay_mask)
    if delay_idx_full.size == 0:
        raise ValueError(f"delay gate 0..{gate_ns_max:.3f} ns selects no delay bins")

    delay_step = max(1, int(math.ceil(delay_idx_full.size / max_delay_bins)))
    delay_idx = delay_idx_full[::delay_step][:max_delay_bins]
    if delay_idx.size == 0:
        raise ValueError("delay gate subsampling selected no bins")

    window_starts = np.arange(0, n_frames - win + 1, step, dtype=np.int64)
    if window_starts.size == 0:
        window_starts = np.array([0], dtype=np.int64)

    time_window = np.hanning(win).astype(np.float64) if use_hann_window and win > 1 else np.ones(win, dtype=np.float64)
    doppler_hz = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / float(frame_rate_hz)))

    window_tracks: list[dict[str, Any]] = []
    flat_tracks: list[dict[str, Any]] = []

    for start in window_starts:
        end = int(min(start + win, n_frames))
        start = int(max(0, end - win))
        center = start + (end - start) // 2
        segment = cir[start:end, :][:, delay_idx]
        if segment.shape[0] < win:
            pad = np.zeros((win - segment.shape[0], segment.shape[1]), dtype=segment.dtype)
            segment = np.vstack([segment, pad])
        spectrum = np.fft.fftshift(np.fft.fft(segment * time_window[:, None], n=n_fft, axis=0), axes=0)
        power_db = 20.0 * np.log10(np.abs(spectrum).astype(np.float64) + 1e-30)
        if relative_to_peak:
            power_db = power_db - float(np.max(power_db))

        column_candidates: list[tuple[float, int, int]] = []
        col_power = np.mean(np.abs(segment) ** 2, axis=0)
        col_power_db = 10.0 * np.log10(col_power + 1e-30)
        max_col_db = float(np.max(col_power_db))
        for delay_col in range(power_db.shape[1]):
            if col_power[delay_col] <= 1e-30:
                continue
            if col_power_db[delay_col] < max_col_db - float(min_peak_relative_db):
                continue
            is_local_max = True
            if delay_col > 0:
                is_local_max &= col_power[delay_col] >= col_power[delay_col - 1]
            if delay_col + 1 < col_power.size:
                is_local_max &= col_power[delay_col] >= col_power[delay_col + 1]
            if not is_local_max:
                continue
            dop_idx = int(np.argmax(power_db[:, delay_col]))
            score_db = float(power_db[dop_idx, delay_col])
            column_candidates.append((score_db, dop_idx, delay_col))
        column_candidates.sort(reverse=True, key=lambda item: item[0])

        chosen: list[tuple[float, int, int]] = []
        for score_db, dop_idx, delay_col in column_candidates:
            too_close = any(
                abs(delay_col - old_delay) <= min_separation_delay_bins
                for _, _, old_delay in chosen
            )
            if too_close:
                continue
            chosen.append((score_db, dop_idx, delay_col))
            if len(chosen) >= max_paths:
                break

        peaks: list[dict[str, Any]] = []
        for path_id, (score_db, dop_idx, delay_col) in enumerate(chosen, start=1):
            abs_delay_bin = int(delay_idx[delay_col])
            delay_ns = abs_delay_bin / float(bandwidth_hz) * 1e9
            peak_power_db = float(power_db[dop_idx, delay_col])
            series = np.asarray(segment[:, delay_col], dtype=np.complex128)
            if np.allclose(series, 0):
                doppler_est_hz = 0.0
            else:
                phase = np.unwrap(np.angle(series))
                time_axis = np.arange(series.size, dtype=np.float64) / float(frame_rate_hz)
                slope = np.polyfit(time_axis, phase, 1)[0]
                doppler_est_hz = float(slope / (2.0 * np.pi))
            peak = {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayBin": abs_delay_bin,
                "delayNs": _finite_float(delay_ns, digits=3),
                "dopplerHz": _finite_float(doppler_est_hz, digits=3),
                "powerDb": _finite_float(peak_power_db, digits=6),
                "jointScoreDb": _finite_float(score_db, digits=3),
                "pathId": path_id,
                "mock": False,
            }
            peaks.append(peak)
            flat_tracks.append(peak)

        window_tracks.append(
            {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
                "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
                "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
                "dopplerHz": np.round(doppler_hz, 3).tolist(),
                "peaks": peaks,
            }
        )

    return {
        "mock": False,
        "method": "joint_delay_doppler_fft",
        "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
        "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
        "windowSizeFrames": win,
        "stepFrames": step,
        "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
        "dopplerHz": np.round(doppler_hz, 3).tolist(),
        "windowTracks": window_tracks,
        "tracks": flat_tracks,
    }


def compute_sage_delay_doppler_tracks(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    window_size_frames: int | None = None,
    step_frames: int | None = None,
    delay_gate_distance_m: float = 2000.0,
    max_delay_bins: int = 256,
    n_doppler_bins: int | None = None,
    max_paths: int = 8,
    max_iter: int = 3,
    min_peak_relative_db: float = 18.0,
    min_separation_delay_bins: int = 1,
    min_separation_doppler_bins: int = 2,
    use_hann_window: bool = True,
    use_gpu: bool = False,
) -> dict[str, Any]:
    """Functional single-antenna delay-Doppler SAGE with local refinement.

    This keeps the same windowed contract shape as joint_delay_doppler_fft, but
    uses FFT peaks only for initialization and then locally refines delay/Doppler
    plus LS amplitude updates per path.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D (n_frames, delay_bins), got shape={cir.shape}")
    if max_delay_bins <= 0 or max_paths <= 0:
        raise ValueError("max_delay_bins and max_paths must be positive")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")

    win = int(round(frame_rate_hz)) if window_size_frames is None else int(window_size_frames)
    win = max(4, min(win, n_frames))
    step = win if step_frames is None else int(step_frames)
    step = max(1, step)
    n_fft = max(int(n_doppler_bins) if n_doppler_bins is not None else win, win)

    gate_ns_max = distance_to_delay_ns(delay_gate_distance_m)
    delay_axis_ns = np.arange(n_delay, dtype=np.float64) / float(bandwidth_hz) * 1e9
    delay_mask = (delay_axis_ns >= 0.0) & (delay_axis_ns <= gate_ns_max)
    delay_idx_full = np.flatnonzero(delay_mask)
    if delay_idx_full.size == 0:
        raise ValueError(f"delay gate 0..{gate_ns_max:.3f} ns selects no delay bins")
    delay_step = max(1, int(math.ceil(delay_idx_full.size / max_delay_bins)))
    delay_idx = delay_idx_full[::delay_step][:max_delay_bins]
    if delay_idx.size == 0:
        raise ValueError("delay gate subsampling selected no bins")

    window_starts = np.arange(0, n_frames - win + 1, step, dtype=np.int64)
    if window_starts.size == 0:
        window_starts = np.array([0], dtype=np.int64)

    doppler_hz = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / float(frame_rate_hz)))
    window_tracks: list[dict[str, Any]] = []
    flat_tracks: list[dict[str, Any]] = []

    for start_raw in window_starts:
        end = int(min(int(start_raw) + win, n_frames))
        start = int(max(0, end - win))
        center = start + (end - start) // 2
        segment = cir[start:end, :][:, delay_idx]
        if segment.shape[0] < win:
            pad = np.zeros((win - segment.shape[0], segment.shape[1]), dtype=segment.dtype)
            segment = np.vstack([segment, pad])
        estimates = estimate_window_paths(
            segment,
            delay_bins=delay_idx,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            max_paths=max_paths,
            n_doppler_bins=n_fft,
            max_iter=max_iter,
            min_peak_relative_db=min_peak_relative_db,
            min_delay_separation_bins=min_separation_delay_bins,
            min_doppler_separation_bins=min_separation_doppler_bins,
            use_hann_window=use_hann_window,
            use_gpu=use_gpu,
        )
        peaks: list[dict[str, Any]] = []
        for estimate in estimates:
            peak = {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayBin": int(estimate.delay_bin),
                "delayNs": _finite_float(estimate.delay_ns, digits=3),
                "dopplerHz": _finite_float(estimate.doppler_hz, digits=3),
                "powerDb": _finite_float(estimate.power_db, digits=6),
                "jointScoreDb": _finite_float(estimate.score_db, digits=3),
                "pathId": int(estimate.path_id),
                "amplitudeReal": _finite_float(estimate.amplitude.real, digits=6),
                "amplitudeImag": _finite_float(estimate.amplitude.imag, digits=6),
                "mock": False,
            }
            peaks.append(peak)
            flat_tracks.append(peak)
        window_tracks.append(
            {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
                "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
                "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
                "dopplerHz": np.round(doppler_hz, 3).tolist(),
                "peaks": peaks,
            }
        )

    return {
        "mock": False,
        "method": "delay_doppler_sage",
        "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
        "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
        "windowSizeFrames": win,
        "stepFrames": step,
        "delayNs": np.round(delay_idx.astype(np.float64) / float(bandwidth_hz) * 1e9, 3).tolist(),
        "dopplerHz": np.round(doppler_hz, 3).tolist(),
        "windowTracks": window_tracks,
        "tracks": flat_tracks,
        "gpuEnabled": bool(use_gpu and flat_tracks is not None),
    }


def compute_adaptive_sage_tracks(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    window_size_frames: int = 20,
    step_frames: int = 100,
    delay_gate_distance_m: float = 2000.0,
    max_delay_bins: int = 300,
    coverage_target: float = 0.95,
    min_coverage_gain: float = 0.005,
    max_paths_hard: int = 30,
    use_hann_window: bool = True,
    enable_weak_nonprominent_prune: bool = True,
) -> dict[str, Any]:
    """Adaptive SAGE with B2B-calibrated CIR and coverage-based termination.

    Uses 20-frame windows and 100-frame (1-second) steps by default.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D, got shape={cir.shape}")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")
    win = max(4, min(int(window_size_frames), n_frames))
    step = max(1, int(step_frames))
    gate_ns_max = distance_to_delay_ns(delay_gate_distance_m)
    delay_axis_ns = np.arange(n_delay, dtype=np.float64) / float(bandwidth_hz) * 1e9
    delay_mask = (delay_axis_ns >= 0.0) & (delay_axis_ns <= gate_ns_max)
    delay_idx_full = np.flatnonzero(delay_mask)
    if delay_idx_full.size == 0:
        raise ValueError(f"delay gate selects no bins")
    delay_step = max(1, int(math.ceil(delay_idx_full.size / max_delay_bins)))
    delay_idx = delay_idx_full[::delay_step][:max_delay_bins]
    window_starts = np.arange(0, n_frames - win + 1, step, dtype=np.int64)
    if window_starts.size == 0:
        window_starts = np.array([0], dtype=np.int64)
    flat_tracks: list[dict[str, Any]] = []
    window_tracks: list[dict[str, Any]] = []
    for start_raw in window_starts:
        end = int(min(int(start_raw) + win, n_frames))
        start = int(max(0, end - win))
        center = start + (end - start) // 2
        segment = cir[start:end, :][:, delay_idx]
        if segment.shape[0] < win:
            pad = np.zeros((win - segment.shape[0], segment.shape[1]), dtype=segment.dtype)
            segment = np.vstack([segment, pad])
        detailed = estimate_window_paths_adaptive(
            segment,
            delay_bins=delay_idx,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            coverage_target=coverage_target,
            min_coverage_gain=min_coverage_gain,
            max_paths_hard=max_paths_hard,
            use_hann_window=use_hann_window,
            enable_weak_nonprominent_prune=enable_weak_nonprominent_prune,
        )
        peaks: list[dict[str, Any]] = []
        for p in detailed.final_paths:
            peak = {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayBin": int(p.delay_bin),
                "delayNs": _finite_float(p.delay_ns, digits=3),
                "dopplerHz": _finite_float(p.doppler_hz, digits=3),
                "powerDb": _finite_float(p.power_db, digits=6),
                "jointScoreDb": _finite_float(p.score_db, digits=3),
                "pathId": int(p.path_id),
                "amplitudeReal": _finite_float(p.amplitude.real, digits=6),
                "amplitudeImag": _finite_float(p.amplitude.imag, digits=6),
                "mock": False,
            }
            peaks.append(peak)
            flat_tracks.append(peak)
        window_tracks.append({
            "frame": center,
            "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
            "frameStart": start,
            "frameEnd": end,
            "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
            "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
            "peaks": peaks,
            "origEnergyDb": _finite_float(detailed.orig_energy_db, digits=3),
            "finalCoverageRatio": _finite_float(detailed.final_coverage_ratio, digits=4),
        })
    coverage_ratios = [wt["finalCoverageRatio"] for wt in window_tracks if wt["finalCoverageRatio"] is not None]
    coverage_summary = (
        {
            "meanCoverageRatio": _finite_float(float(np.mean(coverage_ratios)), digits=4),
            "minCoverageRatio": _finite_float(float(np.min(coverage_ratios)), digits=4),
            "p10CoverageRatio": _finite_float(float(np.percentile(coverage_ratios, 10)), digits=4),
        }
        if coverage_ratios
        else None
    )
    return {
        "mock": False,
        "method": f"adaptive_sage_coverage_{int(round(coverage_target * 100)):03d}",
        "delayGateDistanceM": _finite_float(delay_gate_distance_m, digits=3),
        "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
        "windowSizeFrames": win,
        "stepFrames": step,
        "windowTracks": window_tracks,
        "tracks": flat_tracks,
        "coverageSummary": coverage_summary,
    }


def compute_music_delay_tracks(
    cir: np.ndarray,
    *,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    window_size_frames: int = 20,
    step_frames: int = 100,
    max_delay_bins: int = 300,
    subarray_ratio: float = 0.586,
    max_order: int = 40,
    max_paths: int = 30,
) -> dict[str, Any]:
    """Frequency-domain MUSIC delay tracks, mirroring the SAGE track structure.

    Single-antenna delay-domain MUSIC: each window yields delay + power MPCs
    (no Doppler, no phase).  Power is read from the window PDP; complex
    amplitude is synthesized as ``sqrt(10**(P/10))`` so the existing Module-B
    consumers (which use ``|amplitude|**2``) work unchanged.  ``dopplerHz`` is
    set to 0 — MUSIC here does not estimate Doppler.
    """
    if cir.ndim != 2:
        raise ValueError(f"cir must be 2D, got shape={cir.shape}")
    n_frames, n_delay = cir.shape
    if n_frames == 0 or n_delay == 0:
        raise ValueError("cir is empty")
    win = max(4, min(int(window_size_frames), n_frames))
    step = max(1, int(step_frames))
    hi_bin = min(int(max_delay_bins), n_delay)
    gate_ns_max = float(hi_bin / float(bandwidth_hz) * 1e9)

    window_starts = np.arange(0, n_frames - win + 1, step, dtype=np.int64)
    if window_starts.size == 0:
        window_starts = np.array([0], dtype=np.int64)

    flat_tracks: list[dict[str, Any]] = []
    window_tracks: list[dict[str, Any]] = []
    for start_raw in window_starts:
        end = int(min(int(start_raw) + win, n_frames))
        start = int(max(0, end - win))
        center = start + (end - start) // 2
        segment = cir[start:end, :]
        estimates = estimate_window_delays_music(
            segment,
            bandwidth_hz=bandwidth_hz,
            subarray_ratio=subarray_ratio,
            max_order=max_order,
            min_delay_bin=0,
            max_delay_bin=hi_bin,
            max_paths=max_paths,
        )
        peaks: list[dict[str, Any]] = []
        for path_id, e in enumerate(estimates, start=1):
            amp = float(np.sqrt(10.0 ** (e.power_db / 10.0)))
            peak = {
                "frame": center,
                "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
                "frameStart": start,
                "frameEnd": end,
                "delayBin": int(e.delay_bin),
                "delayNs": _finite_float(e.delay_ns, digits=3),
                "dopplerHz": 0.0,
                "powerDb": _finite_float(e.power_db, digits=6),
                "pathId": path_id,
                "amplitudeReal": _finite_float(amp, digits=6),
                "amplitudeImag": 0.0,
                "mock": False,
            }
            peaks.append(peak)
            flat_tracks.append(peak)
        window_tracks.append({
            "frame": center,
            "timeSec": _finite_float(center / float(frame_rate_hz), digits=6),
            "frameStart": start,
            "frameEnd": end,
            "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
            "peaks": peaks,
        })
    return {
        "mock": False,
        "method": "delay_music_mdl",
        "dopplerAvailable": False,
        "delayGateNs": [0.0, _finite_float(gate_ns_max, digits=3)],
        "windowSizeFrames": win,
        "stepFrames": step,
        "windowTracks": window_tracks,
        "tracks": flat_tracks,
    }


def _mpc_scatter_from_peaks(frame_stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Peak-only placeholder for future MUSIC/SAGE/MPC results."""
    return [
        {
            "frame": item["frame"],
            "timeSec": item["timeSec"],
            "delayNs": item["peakDelayNs"],
            "dopplerHz": 0.0,
            "powerDb": item["peakPowerDb"],
            "pathId": 1,
            "mock": True,
        }
        for item in frame_stats
    ]


def compute_frame_payload(
    cir: np.ndarray,
    gps: Mapping[str, np.ndarray],
    tx_gps: TxGps,
    frame_stats: list[dict[str, Any]],
    *,
    frame_index: int,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    max_delay_bins: int = 512,
    relative_power: bool = False,
) -> dict[str, Any]:
    """Package all single-frame data needed when the UI slider selects a frame."""
    if not 0 <= frame_index < cir.shape[0]:
        raise IndexError(f"frame_index out of range: {frame_index}")
    frame_power_db = 10.0 * np.log10(np.abs(cir[frame_index]).astype(np.float64) ** 2 + 1e-30)
    stat = frame_stats[frame_index]
    return {
        "frame": frame_index,
        "timeSec": _finite_float(frame_index / float(frame_rate_hz), digits=6),
        "rxGps": _rx_gps_record(gps, frame_index, frame_rate_hz),
        "txGps": {k: v for k, v in asdict(tx_gps).items() if v is not None},
        "stats": stat,
        "pdpCurve": compute_pdp_curve(
            cir,
            frame_index=frame_index,
            bandwidth_hz=bandwidth_hz,
            max_delay_bins=max_delay_bins,
            relative=relative_power,
        ),
        "powerDistribution": compute_power_distribution(frame_power_db, relative_to_peak=False),
        "mpcScatter": [
            {
                "frame": frame_index,
                "timeSec": stat["timeSec"],
                "delayNs": stat["peakDelayNs"],
                "dopplerHz": 0.0,
                "powerDb": stat["peakPowerDb"],
                "pathId": 1,
                "mock": True,
            }
        ],
    }


def build_dataset_from_arrays(
    *,
    name: str,
    cir: np.ndarray,
    gps: Mapping[str, np.ndarray],
    tx_gps: TxGps,
    bandwidth_hz: float = BW_HZ,
    frame_rate_hz: float = FRAME_RATE_HZ,
    max_delay_bins: int = 256,
    relative_power: bool = False,
    include_joint: bool = False,
    include_music: bool = False,
    include_sage: bool = False,
    include_delay_music: bool = False,
    delay_gate_distance_m: float = 2000.0,
    b2b_cir: np.ndarray | None = None,
    b2b_attenuation_db: float = 0.0,
    b2b_regularization: float = 1e-3,
) -> dict[str, Any]:
    """Build the JSON-serializable frontend dataset from processed arrays."""
    # B2B frequency-domain calibration if a reference pulse is provided.
    if b2b_cir is not None and b2b_cir.size > 0:
        ref = np.asarray(b2b_cir[0], dtype=np.complex128)
        cir = regularized_frequency_calibrate(
            cir, ref, regularization=b2b_regularization, axis=1, attenuation_db=b2b_attenuation_db
        )

    n_frames = int(cir.shape[0])
    time_step = max(1, int(round(frame_rate_hz)))  # 1 frame per second
    delay_ns, power_db = downsample_cir_power_db(
        cir,
        bandwidth_hz=bandwidth_hz,
        max_delay_bins=max_delay_bins,
        relative_to_frame_peak=relative_power,
        time_step_frames=time_step,
    )
    stats = compute_frame_stats(cir, gps, tx_gps, bandwidth_hz=bandwidth_hz, frame_rate_hz=frame_rate_hz)
    time_sec = np.round(np.arange(0, n_frames, time_step, dtype=np.float64) / float(frame_rate_hz), 6).tolist()
    decimated_indices = list(range(0, n_frames, time_step))

    tx_payload = asdict(tx_gps)
    tx_payload = {k: v for k, v in tx_payload.items() if v is not None}

    frame_payloads = [
        compute_frame_payload(
            cir,
            gps,
            tx_gps,
            stats,
            frame_index=i,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            max_delay_bins=max_delay_bins,
            relative_power=relative_power,
        )
        for i in decimated_indices
    ]
    decimated_stats = [stats[i] for i in decimated_indices]
    decimated_rx_gps = [_rx_gps_record(gps, i, frame_rate_hz) for i in decimated_indices]

    joint_tracks = None
    if include_joint or include_music:
        joint_tracks = compute_joint_delay_doppler_tracks(
            cir,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            window_size_frames=min(int(round(frame_rate_hz)), n_frames),
            step_frames=min(int(round(frame_rate_hz)), n_frames),
            delay_gate_distance_m=delay_gate_distance_m,
            max_delay_bins=max_delay_bins,
            n_doppler_bins=min(256, max(64, int(round(frame_rate_hz)))),
            max_paths=15,
        )

    sage_tracks = None
    if include_sage:
        sage_tracks = compute_adaptive_sage_tracks(
            cir,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            window_size_frames=20,
            step_frames=100,
            delay_gate_distance_m=delay_gate_distance_m,
            max_delay_bins=max_delay_bins,
            coverage_target=0.97,
            min_coverage_gain=0.001,
            max_paths_hard=30,
            enable_weak_nonprominent_prune=True,
        )

    music_tracks = None
    if include_delay_music:
        music_tracks = compute_music_delay_tracks(
            cir,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            window_size_frames=20,
            step_frames=100,
            max_delay_bins=max_delay_bins,
        )

    primary_tracks = sage_tracks if sage_tracks is not None else joint_tracks

    dataset = {
        "meta": {
            "name": name,
            "frameRateHz": float(frame_rate_hz),
            "bandwidthHz": float(bandwidth_hz),
            "numFrames": n_frames,
            "numDelayBinsOriginal": int(cir.shape[1]),
            "numDelayBinsExported": len(delay_ns),
            "delayUnit": "ns",
            "txMode": "static",
            "relativePower": bool(relative_power),
        },
        "txGps": tx_payload,
        "rxGps": decimated_rx_gps,
        "frameStats": decimated_stats,
        "framePayloads": frame_payloads,
        "cirWaterfall": {
            "delayNs": delay_ns,
            "timeSec": time_sec,
            "powerDb": power_db,
        },
        "dopplerDelay": compute_doppler_delay(
            cir,
            bandwidth_hz=bandwidth_hz,
            frame_rate_hz=frame_rate_hz,
            max_delay_bins=max_delay_bins,
            n_doppler_bins=min(128, max(8, n_frames)),
        ),
        "dopplerTimeWaterfall": compute_doppler_time_waterfall(
            cir,
            frame_rate_hz=frame_rate_hz,
            window_size_frames=20,
            step_frames=100,
            max_delay_bins=max_delay_bins,
            n_doppler_bins=128,
        ),
        "mpcScatter": primary_tracks["tracks"] if primary_tracks is not None else _mpc_scatter_from_peaks(stats),
        "jointDelayDoppler": joint_tracks,
        "sageDelayDoppler": sage_tracks,
        "musicDelay": music_tracks,
    }
    if joint_tracks is not None:
        dataset["musicMpc"] = joint_tracks
    return dataset


def build_measurement_dataset(
    rx_path: str | Path,
    *,
    tx_gps_path: str | Path | None = None,
    max_frames: int | None = 300,
    max_delay_bins: int = 256,
    relative_power: bool = False,
    include_joint: bool = False,
    include_music: bool = False,
    include_sage: bool = False,
    include_delay_music: bool = False,
    delay_gate_distance_m: float = 2000.0,
    b2b_cir: np.ndarray | None = None,
    b2b_attenuation_db: float = 0.0,
    b2b_regularization: float = 1e-3,
) -> dict[str, Any]:
    """Read Rx .bin data and build a compact frontend dataset."""
    rx = Path(rx_path)
    tx = load_tx_gps(tx_gps_path)
    frames = _load_frames(rx, max_frames=max_frames)
    gps = _parse_gps(frames)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    return build_dataset_from_arrays(
        name=rx.name,
        cir=cir,
        gps=gps,
        tx_gps=tx,
        bandwidth_hz=BW_HZ,
        frame_rate_hz=FRAME_RATE_HZ,
        max_delay_bins=max_delay_bins,
        relative_power=relative_power,
        include_joint=include_joint,
        include_music=include_music,
        include_sage=include_sage,
        include_delay_music=include_delay_music,
        delay_gate_distance_m=delay_gate_distance_m,
        b2b_cir=b2b_cir,
        b2b_attenuation_db=b2b_attenuation_db,
        b2b_regularization=b2b_regularization,
    )


def export_measurement_dataset(
    rx_path: str | Path,
    out_path: str | Path,
    *,
    tx_gps_path: str | Path | None = None,
    max_frames: int | None = 300,
    max_delay_bins: int = 256,
    relative_power: bool = False,
    include_joint: bool = False,
    include_music: bool = False,
    include_sage: bool = False,
    include_delay_music: bool = False,
    delay_gate_distance_m: float = 2000.0,
) -> dict[str, Any]:
    """Build and write a frontend dataset JSON file."""
    dataset = build_measurement_dataset(
        rx_path,
        tx_gps_path=tx_gps_path,
        max_frames=max_frames,
        max_delay_bins=max_delay_bins,
        relative_power=relative_power,
        include_joint=include_joint,
        include_music=include_music,
        include_sage=include_sage,
        include_delay_music=include_delay_music,
        delay_gate_distance_m=delay_gate_distance_m,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return dataset


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export channel measurement data for the future HTML UI.")
    parser.add_argument("--rx", required=True, type=Path, help="Rx .bin file or directory")
    parser.add_argument("--out", required=True, type=Path, help="Output JSON path")
    parser.add_argument("--tx-gps", type=Path, default=None, help="Tx GPS JSON or current TX_GPS screenshot artifact")
    parser.add_argument("--max-frames", type=int, default=300, help="Maximum frames to process")
    parser.add_argument("--max-delay-bins", type=int, default=256, help="Maximum delay bins to export")
    parser.add_argument("--relative-power", action="store_true", help="Export CIR power relative to each frame peak")
    parser.add_argument("--joint", action="store_true", help="Run joint delay-doppler track estimation")
    parser.add_argument("--music", action="store_true", help="Alias for --joint (kept for backward compatibility)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    dataset = export_measurement_dataset(
        args.rx,
        args.out,
        tx_gps_path=args.tx_gps,
        max_frames=args.max_frames,
        max_delay_bins=args.max_delay_bins,
        relative_power=args.relative_power,
        include_joint=args.joint or args.music,
        include_music=args.music,
    )
    print(
        f"Exported {dataset['meta']['numFrames']} frames × "
        f"{dataset['meta']['numDelayBinsExported']} delay bins -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
