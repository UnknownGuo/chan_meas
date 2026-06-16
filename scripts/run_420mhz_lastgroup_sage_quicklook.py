from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io.bin_read import BW_HZ, FRAME_RATE_HZ, _load_frames, _parse_iq, _sliding_correlate
from src.signal.delay_doppler_sage import _fft_spectrum, _select_peaks, _fit_path, _complex_tone

RX_PATH = Path("/mnt/win_data/data_mea/0121campus_test/0121mea/接收数据帧_20260121115358435.bin")
OUT_DIR = Path("/mnt/win_data/data_mea/0121campus_test/sage_quicklook_420mhz_lastgroup_first_second")
N_FRAMES = 100
MAX_DELAY_BINS = 300  # 0..6000 ns at 50 MHz
N_DOPPLER_BINS = 256
MAX_PATHS = 8
MAX_ITER = 5
MIN_PEAK_RELATIVE_DB = 18.0


def db20(x: np.ndarray, floor: float = 1e-30) -> np.ndarray:
    return 20.0 * np.log10(np.abs(x).astype(np.float64) + floor)


def db10_power(x: np.ndarray, floor: float = 1e-30) -> np.ndarray:
    return 10.0 * np.log10(np.abs(x).astype(np.float64) ** 2 + floor)


def residual_metric(segment: np.ndarray, recon: np.ndarray, initial_sse: float) -> dict[str, float]:
    residual = segment - recon
    sse = float(np.sum(np.abs(residual) ** 2))
    improvement_db = 10.0 * np.log10(max(initial_sse, 1e-30) / max(sse, 1e-30))
    normalized_sse = sse / max(initial_sse, 1e-30)
    return {"sse": sse, "residualReductionDb": improvement_db, "normalizedSse": normalized_sse}


def fit_sage_with_history(segment: np.ndarray, delay_bins: np.ndarray) -> dict[str, Any]:
    _, power_db = _fft_spectrum(
        segment,
        n_doppler_bins=N_DOPPLER_BINS,
        use_hann_window=True,
        use_gpu=False,
    )
    doppler_axis = np.fft.fftshift(np.fft.fftfreq(N_DOPPLER_BINS, d=1.0 / float(FRAME_RATE_HZ)))
    chosen = _select_peaks(
        power_db,
        max_paths=MAX_PATHS,
        min_peak_relative_db=MIN_PEAK_RELATIVE_DB,
        min_delay_separation_bins=1,
        min_doppler_separation_bins=2,
    )
    n_slow, n_delay = segment.shape
    initial_sse = float(np.sum(np.abs(segment) ** 2))
    s_sum = np.zeros_like(segment, dtype=np.complex128)
    s_list: list[np.ndarray] = []
    states: list[dict[str, Any]] = []
    history: list[dict[str, float | int | str]] = []

    history.append({"step": 0, "label": "empty", **residual_metric(segment, s_sum, initial_sse)})

    for path_id, (score_db, dop_idx, delay_col) in enumerate(chosen, start=1):
        fd0 = float(doppler_axis[dop_idx])
        series = segment[:, delay_col].astype(np.complex128)
        fd, amp, _ = _fit_path(series, frame_rate_hz=FRAME_RATE_HZ, init_doppler_hz=fd0)
        tone = _complex_tone(FRAME_RATE_HZ, fd, n_slow)
        s_path = np.zeros_like(segment, dtype=np.complex128)
        s_path[:, delay_col] = amp * tone
        s_sum += s_path
        s_list.append(s_path)
        states.append({
            "path_id": path_id,
            "delay_col": int(delay_col),
            "doppler_hz": float(fd),
            "amplitude": complex(amp),
            "score_db": float(score_db),
        })
        history.append({"step": len(history), "label": f"init_p{path_id}", **residual_metric(segment, s_sum, initial_sse)})

    for it in range(1, MAX_ITER + 1):
        for idx, state in enumerate(states):
            x_l = segment.astype(np.complex128) - (s_sum - s_list[idx])
            old_delay = int(state["delay_col"])
            best = None
            for delay_col in range(max(0, old_delay - 1), min(n_delay, old_delay + 2)):
                series = x_l[:, delay_col]
                fd, amp, score = _fit_path(
                    series,
                    frame_rate_hz=FRAME_RATE_HZ,
                    init_doppler_hz=float(state["doppler_hz"]),
                )
                if best is None or score > best[0]:
                    best = (float(score), int(delay_col), float(fd), complex(amp))
            if best is None:
                continue
            _, new_delay, new_fd, new_amp = best
            tone = _complex_tone(FRAME_RATE_HZ, new_fd, n_slow)
            s_new = np.zeros_like(segment, dtype=np.complex128)
            s_new[:, new_delay] = new_amp * tone
            s_sum = s_sum - s_list[idx] + s_new
            s_list[idx] = s_new
            state["delay_col"] = int(new_delay)
            state["doppler_hz"] = float(new_fd)
            state["amplitude"] = complex(new_amp)
            history.append({"step": len(history), "label": f"iter{it}_p{idx+1}", **residual_metric(segment, s_sum, initial_sse)})

    residual = segment.astype(np.complex128) - s_sum
    residual_floor = float(np.mean(np.abs(residual) ** 2) + 1e-30)
    peaks = []
    for state in states:
        delay_col = int(state["delay_col"])
        delay_bin = int(delay_bins[delay_col])
        amp = complex(state["amplitude"])
        peaks.append({
            "pathId": int(state["path_id"]),
            "delayCol": delay_col,
            "delayBin": delay_bin,
            "delayNs": float(delay_bin / float(BW_HZ) * 1e9),
            "dopplerHz": float(state["doppler_hz"]),
            "amplitudeReal": float(amp.real),
            "amplitudeImag": float(amp.imag),
            "powerDb": float(10.0 * np.log10(abs(amp) ** 2 + residual_floor)),
            "initScoreDb": float(state["score_db"]),
        })
    peaks.sort(key=lambda x: x["powerDb"], reverse=True)
    for i, p in enumerate(peaks, start=1):
        p["pathId"] = i

    return {
        "powerDb": power_db,
        "dopplerHz": doppler_axis,
        "reconstruction": s_sum,
        "history": history,
        "peaks": peaks,
        "initialSse": initial_sse,
        "final": residual_metric(segment, s_sum, initial_sse),
    }


def style_ax(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=13, weight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.22, linewidth=0.5)


def save_fig(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames_total = RX_PATH.stat().st_size // 4132
    frames = _load_frames(RX_PATH, max_frames=N_FRAMES)
    iq = _parse_iq(frames)
    gps = None
    try:
        from src.io.bin_read import _parse_gps
        gps = _parse_gps(frames)
    except Exception:
        gps = None
    cir = _sliding_correlate(iq)

    delay_bins = np.arange(0, min(MAX_DELAY_BINS, cir.shape[1]), dtype=np.int64)
    segment = cir[:N_FRAMES, :][:, delay_bins].astype(np.complex128)
    result = fit_sage_with_history(segment, delay_bins)

    delay_ns = delay_bins.astype(np.float64) / float(BW_HZ) * 1e9
    time_sec = np.arange(segment.shape[0], dtype=np.float64) / float(FRAME_RATE_HZ)
    doppler_hz = np.asarray(result["dopplerHz"])
    power_db = np.asarray(result["powerDb"])
    recon = np.asarray(result["reconstruction"])

    # 1) Delay-Doppler power spectrum.
    fig, ax = plt.subplots(figsize=(9.6, 5.6))
    im = ax.imshow(
        power_db,
        origin="lower",
        aspect="auto",
        extent=(float(delay_ns[0]), float(delay_ns[-1]), float(doppler_hz[0]), float(doppler_hz[-1])),
        cmap="turbo",
        vmin=-42,
        vmax=0,
    )
    for p in result["peaks"]:
        ax.scatter([p["delayNs"]], [p["dopplerHz"]], s=44, c="white", edgecolors="black", linewidths=0.8)
        ax.text(p["delayNs"], p["dopplerHz"], f" P{p['pathId']}", color="white", fontsize=8, va="center")
    style_ax(ax, "Delay-Doppler-Power Spectrum (first 1 s / 100 frames)", "Delay (ns)", "Doppler (Hz)")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("Relative amplitude (dB, peak=0)")
    dd_path = OUT_DIR / "01_delay_doppler_power.png"
    save_fig(fig, dd_path)

    # 2) Likelihood / residual-reduction curve.
    hist = result["history"]
    steps = [int(h["step"]) for h in hist]
    ll = [float(h["residualReductionDb"]) for h in hist]
    nsse = [float(h["normalizedSse"]) for h in hist]
    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    ax.plot(steps, ll, marker="o", linewidth=1.6, markersize=3.5, label="residual reduction (dB)")
    ax2 = ax.twinx()
    ax2.plot(steps, nsse, color="#d62728", linestyle="--", linewidth=1.3, label="normalized SSE")
    ax2.set_ylabel("Normalized residual SSE")
    ax2.set_yscale("log")
    style_ax(ax, "SAGE Likelihood Proxy / Residual Convergence", "SAGE update step", "Residual reduction vs empty model (dB)")
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="best")
    likelihood_path = OUT_DIR / "02_likelihood_function.png"
    save_fig(fig, likelihood_path)

    raw_db = db10_power(segment)
    raw_ref = float(np.max(raw_db))
    raw_rel = raw_db - raw_ref
    recon_rel = db10_power(recon) - raw_ref

    # 3) Raw PDP waterfall.
    fig, ax = plt.subplots(figsize=(9.6, 5.6))
    im = ax.imshow(
        raw_rel,
        origin="lower",
        aspect="auto",
        extent=(float(delay_ns[0]), float(delay_ns[-1]), float(time_sec[0]), float(time_sec[-1])),
        cmap="turbo",
        vmin=-50,
        vmax=0,
    )
    style_ax(ax, "Raw PDP Waterfall (first 1 s / 100 frames)", "Delay (ns)", "Time (s)")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("Relative power (dB, raw peak=0)")
    raw_path = OUT_DIR / "03_raw_pdp_waterfall.png"
    save_fig(fig, raw_path)

    # 4) Reconstructed PDP waterfall.
    fig, ax = plt.subplots(figsize=(9.6, 5.6))
    im = ax.imshow(
        recon_rel,
        origin="lower",
        aspect="auto",
        extent=(float(delay_ns[0]), float(delay_ns[-1]), float(time_sec[0]), float(time_sec[-1])),
        cmap="turbo",
        vmin=-50,
        vmax=0,
    )
    for p in result["peaks"]:
        ax.axvline(p["delayNs"], color="white", alpha=0.55, linewidth=0.8)
    style_ax(ax, "Reconstructed PDP Waterfall from SAGE Paths", "Delay (ns)", "Time (s)")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("Relative power (dB, raw peak=0)")
    recon_path = OUT_DIR / "04_reconstructed_pdp_waterfall.png"
    save_fig(fig, recon_path)

    summary = {
        "rxPath": str(RX_PATH),
        "framesTotalInFile": int(frames_total),
        "processedFrames": int(N_FRAMES),
        "processedTimeSec": float(N_FRAMES / FRAME_RATE_HZ),
        "bandwidthHz": float(BW_HZ),
        "frameRateHz": float(FRAME_RATE_HZ),
        "delayGateBins": [int(delay_bins[0]), int(delay_bins[-1])],
        "delayGateNs": [float(delay_ns[0]), float(delay_ns[-1])],
        "dopplerBins": int(N_DOPPLER_BINS),
        "maxPaths": int(MAX_PATHS),
        "maxIter": int(MAX_ITER),
        "finalResidualReductionDb": float(result["final"]["residualReductionDb"]),
        "finalNormalizedSse": float(result["final"]["normalizedSse"]),
        "peaks": result["peaks"],
        "outputs": {
            "delayDopplerPower": str(dd_path),
            "likelihood": str(likelihood_path),
            "rawPdpWaterfall": str(raw_path),
            "reconstructedPdpWaterfall": str(recon_path),
        },
    }
    if gps is not None:
        summary["gpsFirstFrame"] = {
            "lat": float(gps["lat"][0]),
            "lon": float(gps["lon"][0]),
            "alt": float(gps["alt"][0]),
            "hour": int(gps["hour"][0]),
            "minute": int(gps["minute"][0]),
            "second": int(gps["second"][0]),
        }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
