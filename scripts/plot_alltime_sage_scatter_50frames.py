from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io.bin_read import BW_HZ, FRAME_RATE_HZ, FRAME_LEN, _load_frames, _parse_iq, _sliding_correlate
from scripts.try_adaptive_sage_windows_420mhz import adaptive_sage

RX_PATH = Path("/mnt/win_data/data_mea/0121campus_test/0121mea/接收数据帧_20260121115358435.bin")
OUT_DIR = Path("/mnt/win_data/data_mea/0121campus_test/sage_quicklook_420mhz_lastgroup_alltime_50frames")
WINDOW_SIZE = 50
STEP = 50
MAX_DELAY_BINS = 300


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_frames_total = RX_PATH.stat().st_size // FRAME_LEN
    print(f"Loading {n_frames_total} frames from {RX_PATH}")
    frames = _load_frames(RX_PATH, max_frames=None)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    n_frames = int(cir.shape[0])
    delay_bins = np.arange(0, min(MAX_DELAY_BINS, cir.shape[1]), dtype=np.int64)

    records: list[dict[str, Any]] = []
    window_summaries: list[dict[str, Any]] = []
    starts = list(range(0, n_frames - WINDOW_SIZE + 1, STEP))
    print(f"Processing {len(starts)} windows of {WINDOW_SIZE} frames, step={STEP}")
    for wi, start in enumerate(starts):
        end = start + WINDOW_SIZE
        seg = cir[start:end, :][:, delay_bins].astype(np.complex128)
        res = adaptive_sage(seg, delay_bins)
        center = start + WINDOW_SIZE / 2.0
        center_time = center / float(FRAME_RATE_HZ)
        window_summaries.append({
            "windowIndex": wi,
            "frameStart": int(start),
            "frameEnd": int(end),
            "centerFrame": float(center),
            "timeSec": float(center_time),
            "numPaths": int(len(res["peaks"])),
            "residualReductionDb": float(res["final"]["residualReductionDb"]),
            "normalizedSse": float(res["final"]["normalizedSse"]),
        })
        for p in res["peaks"]:
            records.append({
                "windowIndex": wi,
                "frameStart": int(start),
                "frameEnd": int(end),
                "centerFrame": float(center),
                "timeSec": float(center_time),
                "pathId": int(p["pathId"]),
                "delayBin": int(p["delayBin"]),
                "delayNs": float(p["delayNs"]),
                "dopplerHz": float(p["dopplerHz"]),
                "powerDb": float(p["powerDb"]),
                "initScoreDb": float(p["initScoreDb"]),
                "amplitudeReal": float(p["amplitudeReal"]),
                "amplitudeImag": float(p["amplitudeImag"]),
                "residualReductionDb": float(res["final"]["residualReductionDb"]),
            })
        if (wi + 1) % 50 == 0 or wi == len(starts) - 1:
            print(f"  {wi+1}/{len(starts)} windows, records={len(records)}")

    csv_path = OUT_DIR / "alltime_sage_paths_50frame_windows.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "windowIndex", "frameStart", "frameEnd", "centerFrame", "timeSec", "pathId",
            "delayBin", "delayNs", "dopplerHz", "powerDb", "initScoreDb",
            "amplitudeReal", "amplitudeImag", "residualReductionDb",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    win_csv = OUT_DIR / "alltime_sage_window_summary_50frame_windows.csv"
    with win_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["windowIndex", "frameStart", "frameEnd", "centerFrame", "timeSec", "numPaths", "residualReductionDb", "normalizedSse"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(window_summaries)

    if records:
        t = np.array([r["timeSec"] for r in records], dtype=float)
        delay_ns = np.array([r["delayNs"] for r in records], dtype=float)
        doppler_hz = np.array([r["dopplerHz"] for r in records], dtype=float)
        power_db = np.array([r["powerDb"] for r in records], dtype=float)
        path_id = np.array([r["pathId"] for r in records], dtype=int)
        # Relative color scale for visual contrast; keep raw power in CSV.
        p_rel = power_db - float(np.nanmax(power_db))
        sizes = np.clip(16 + 3.0 * (p_rel + 35.0), 10, 70)
        vmin = max(float(np.nanmin(p_rel)), -35.0)
        vmax = 0.0

        fig, ax = plt.subplots(figsize=(12, 5.8))
        sc = ax.scatter(t, delay_ns, c=p_rel, s=sizes, cmap="turbo", vmin=vmin, vmax=vmax, alpha=0.86, edgecolors="none")
        ax.set_title("All-time MPC Delay-Power Scatter (adaptive SAGE, 50-frame windows)", fontsize=14, weight="bold")
        ax.set_xlabel("Time (s), window center")
        ax.set_ylabel("Delay (ns)")
        ax.set_ylim(0, 6000)
        ax.grid(alpha=0.22, linewidth=0.5)
        cb = fig.colorbar(sc, ax=ax)
        cb.set_label("Path power (dB relative to strongest extracted path)")
        fig.tight_layout()
        delay_png = OUT_DIR / "01_alltime_delay_power_scatter_50frames.png"
        fig.savefig(delay_png, dpi=180, bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 5.8))
        sc = ax.scatter(t, doppler_hz, c=p_rel, s=sizes, cmap="turbo", vmin=vmin, vmax=vmax, alpha=0.86, edgecolors="none")
        ax.axhline(0, color="black", linewidth=0.7, alpha=0.45)
        ax.set_title("All-time MPC Doppler-Power Scatter (adaptive SAGE, 50-frame windows)", fontsize=14, weight="bold")
        ax.set_xlabel("Time (s), window center")
        ax.set_ylabel("Doppler (Hz)")
        ax.set_ylim(-50, 50)
        ax.grid(alpha=0.22, linewidth=0.5)
        cb = fig.colorbar(sc, ax=ax)
        cb.set_label("Path power (dB relative to strongest extracted path)")
        fig.tight_layout()
        doppler_png = OUT_DIR / "02_alltime_doppler_power_scatter_50frames.png"
        fig.savefig(doppler_png, dpi=180, bbox_inches="tight")
        plt.close(fig)

        # Auxiliary diagnostics: path count and residual reduction over time.
        tw = np.array([w["timeSec"] for w in window_summaries], dtype=float)
        npaths = np.array([w["numPaths"] for w in window_summaries], dtype=float)
        red = np.array([w["residualReductionDb"] for w in window_summaries], dtype=float)
        fig, axs = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True)
        axs[0].plot(tw, npaths, color="#d62728", linewidth=1.0)
        axs[0].set_ylabel("Accepted paths")
        axs[0].set_title("Adaptive SAGE per-window diagnostics")
        axs[0].grid(alpha=0.22, linewidth=0.5)
        axs[1].plot(tw, red, color="#1f77b4", linewidth=1.0)
        axs[1].set_xlabel("Time (s), window center")
        axs[1].set_ylabel("Residual reduction (dB)")
        axs[1].grid(alpha=0.22, linewidth=0.5)
        fig.tight_layout()
        diag_png = OUT_DIR / "03_alltime_window_diagnostics_50frames.png"
        fig.savefig(diag_png, dpi=180, bbox_inches="tight")
        plt.close(fig)
    else:
        delay_png = doppler_png = diag_png = None

    compact = {
        "rxPath": str(RX_PATH),
        "framesTotal": int(n_frames),
        "durationSec": float(n_frames / FRAME_RATE_HZ),
        "windowSizeFrames": WINDOW_SIZE,
        "stepFrames": STEP,
        "numWindows": int(len(starts)),
        "numExtractedPaths": int(len(records)),
        "bandwidthHz": float(BW_HZ),
        "frameRateHz": float(FRAME_RATE_HZ),
        "delayGateNs": [0.0, float(delay_bins[-1] / float(BW_HZ) * 1e9)],
        "powerDbRange": [float(min([r["powerDb"] for r in records])) if records else None, float(max([r["powerDb"] for r in records])) if records else None],
        "pathCountStats": {
            "min": int(min([w["numPaths"] for w in window_summaries])) if window_summaries else None,
            "max": int(max([w["numPaths"] for w in window_summaries])) if window_summaries else None,
            "mean": float(np.mean([w["numPaths"] for w in window_summaries])) if window_summaries else None,
        },
        "outputs": {
            "pathsCsv": str(csv_path),
            "windowSummaryCsv": str(win_csv),
            "delayPowerScatter": None if delay_png is None else str(delay_png),
            "dopplerPowerScatter": None if doppler_png is None else str(doppler_png),
            "diagnostics": None if diag_png is None else str(diag_png),
        },
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
