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
from src.signal.delay_doppler_sage import estimate_window_paths

RX_PATH = Path("/mnt/win_data/data_mea/0121campus_test/0121mea/接收数据帧_20260121115358435.bin")
OUT_DIR = Path("/mnt/win_data/data_mea/0121campus_test/sage_v2_alltime_50frames")
WINDOW_SIZE = 50
STEP = 50
MAX_DELAY_BINS = 300
MAX_PATHS = 8
N_DOPPLER_BINS = 256


def save_records_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["windowIndex", "frameStart", "frameEnd", "timeSec", "pathId", "delayBin", "delayNs", "dopplerHz", "powerDb", "scoreDb", "amplitudeReal", "amplitudeImag"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_frames_total = RX_PATH.stat().st_size // FRAME_LEN
    print(f"Loading {n_frames_total} frames")
    frames = _load_frames(RX_PATH, max_frames=None)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    delay_bins = np.arange(0, min(MAX_DELAY_BINS, cir.shape[1]), dtype=np.int64)
    starts = list(range(0, cir.shape[0] - WINDOW_SIZE + 1, STEP))
    records: list[dict[str, Any]] = []
    for wi, start in enumerate(starts):
        end = start + WINDOW_SIZE
        seg = cir[start:end, :][:, delay_bins]
        ests = estimate_window_paths(
            seg,
            delay_bins=delay_bins,
            bandwidth_hz=BW_HZ,
            frame_rate_hz=FRAME_RATE_HZ,
            max_paths=MAX_PATHS,
            n_doppler_bins=N_DOPPLER_BINS,
            max_iter=4,
            min_peak_relative_db=18.0,
            min_delay_separation_bins=4,
            min_doppler_separation_bins=2,
            use_hann_window=True,
            use_gpu=False,
            pulse_half_width_bins=4,
            delay_search_bins=8,
            init_strategy="pdp",
        )
        t = (start + WINDOW_SIZE / 2) / FRAME_RATE_HZ
        for e in ests:
            records.append({
                "windowIndex": wi,
                "frameStart": start,
                "frameEnd": end,
                "timeSec": t,
                "pathId": e.path_id,
                "delayBin": e.delay_bin,
                "delayNs": e.delay_ns,
                "dopplerHz": e.doppler_hz,
                "powerDb": e.power_db,
                "scoreDb": e.score_db,
                "amplitudeReal": e.amplitude.real,
                "amplitudeImag": e.amplitude.imag,
            })
        if (wi + 1) % 50 == 0 or wi == len(starts) - 1:
            print(f"{wi+1}/{len(starts)} windows, records={len(records)}")
    csv_path = OUT_DIR / "sage_v2_paths_50frame_windows.csv"
    save_records_csv(csv_path, records)

    t = np.array([r["timeSec"] for r in records], dtype=float)
    delay = np.array([r["delayNs"] for r in records], dtype=float)
    dop = np.array([r["dopplerHz"] for r in records], dtype=float)
    p = np.array([r["powerDb"] for r in records], dtype=float)
    prel = p - np.nanmax(p)
    sizes = np.clip(14 + 3.0 * (prel + 35), 10, 65)

    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    sc = ax.scatter(t, delay, c=prel, s=sizes, cmap="turbo", vmin=-35, vmax=0, alpha=0.88, edgecolors="black", linewidths=0.12)
    ax.set_title("SAGE v2 MPC Delay-Power Scatter (50-frame windows)", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(0, 6000)
    ax.grid(alpha=0.22, linewidth=0.5)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Path power (dB relative to strongest SAGE v2 path)")
    fig.tight_layout()
    delay_png = OUT_DIR / "01_sage_v2_delay_power_scatter.png"
    fig.savefig(delay_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    sc = ax.scatter(t, dop, c=prel, s=sizes, cmap="turbo", vmin=-35, vmax=0, alpha=0.88, edgecolors="black", linewidths=0.12)
    ax.axhline(0, color="black", lw=0.7, alpha=0.45)
    ax.set_title("SAGE v2 MPC Doppler-Power Scatter (50-frame windows)", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Doppler (Hz)")
    ax.set_ylim(-50, 50)
    ax.grid(alpha=0.22, linewidth=0.5)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Path power (dB relative)")
    fig.tight_layout()
    dop_png = OUT_DIR / "02_sage_v2_doppler_power_scatter.png"
    fig.savefig(dop_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # Overlay with previously extracted PDP visible peaks if available.
    pdp_csv = Path("/mnt/win_data/data_mea/0121campus_test/sage_quicklook_420mhz_lastgroup_alltime_50frames/pdp_waterfall_visible_peaks_per_frame_top6.csv")
    overlay_png = None
    if pdp_csv.exists():
        pdp = np.genfromtxt(pdp_csv, delimiter=",", names=True, dtype=None, encoding="utf-8")
        fig, ax = plt.subplots(figsize=(12.5, 6.0))
        ax.scatter(pdp["timeSec"], pdp["delayNs"], c="0.72", s=3, alpha=0.18, edgecolors="none", label="PDP visible peaks")
        sc = ax.scatter(t, delay, c=prel, s=sizes, cmap="turbo", vmin=-35, vmax=0, alpha=0.92, edgecolors="black", linewidths=0.15, label="SAGE v2 paths")
        ax.set_title("PDP Waterfall Visible Peaks vs SAGE v2 Paths", fontsize=14, weight="bold")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Delay (ns)")
        ax.set_ylim(0, 6000)
        ax.grid(alpha=0.22, linewidth=0.5)
        ax.legend(loc="upper right", fontsize=8)
        cb = fig.colorbar(sc, ax=ax)
        cb.set_label("SAGE v2 power (dB relative)")
        fig.tight_layout()
        overlay_png = OUT_DIR / "03_overlay_pdp_visible_peaks_vs_sage_v2.png"
        fig.savefig(overlay_png, dpi=180, bbox_inches="tight")
        plt.close(fig)

    summary = {
        "rxPath": str(RX_PATH),
        "numFrames": int(cir.shape[0]),
        "numWindows": len(starts),
        "numPaths": len(records),
        "pathsPerWindowMean": float(len(records) / max(1, len(starts))),
        "outputs": {"csv": str(csv_path), "delayPower": str(delay_png), "dopplerPower": str(dop_png), "overlay": None if overlay_png is None else str(overlay_png)},
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
