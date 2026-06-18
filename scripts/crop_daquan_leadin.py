"""One-off: remove the ~85s walk-in lead-in from the daquan dataset before
the real big-loop scan starts, and regenerate the three figures used in the
comparison report (GPS map, original PDP waterfall, MPC delay-time scatter).

The lead-in covers window_index 0-84 (frames 0-8499): the operator walking
from the building to the TX. Window 85 (t=85.1s) is the closest approach to
TX (2.55 m) and is treated as the new t=0 reference; everything before it is
dropped, nothing else about the pipeline changes.

Outputs are written next to the existing pipeline outputs with a
"cropped_" prefix so the original full-length record is untouched.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.b2b_frequency import regularized_frequency_calibrate
from src.io.bin_read import BW_HZ, FRAME_LEN, FRAME_RATE_HZ, _load_frames, _parse_gps, _parse_iq, _sliding_correlate
from scripts.generate_adaptive_sage_gps_maps import _make_map, _window_centers, _write_summary, _write_window_csv
from scripts.run_adaptive_sage_w20_step100_remaining import (
    B2B_ATTENUATION_DB,
    MAX_DELAY_BINS,
    WINDOW,
    STEP,
    _save_pdp_waterfall,
)

STEM = "0m-0m-all-first-antenna-daquan"
BIN_PATH = Path("/mnt/win_data/data_mea/zjk_mea") / f"{STEM}.bin"
B2B_PATH = Path("/mnt/win_data/data_mea/zjk_mea/calibration/b2b_cir.npy")
OUT_DIR = Path("/home/guo/桌面/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100") / STEM

CROP_WINDOW_INDEX = 185  # 85 (closest approach to TX) + 100s further requested crop


def crop_gps_map() -> None:
    frames = _load_frames(BIN_PATH, max_frames=None)
    gps = _parse_gps(frames)
    del frames

    centers_full = _window_centers(len(gps["lat"]), window_size=WINDOW, step=STEP)
    raw_start_frame = int(centers_full[CROP_WINDOW_INDEX] - WINDOW // 2)  # = window's frameStart

    cropped_gps = {k: v[raw_start_frame:] for k, v in gps.items()}
    centers_cropped = centers_full[CROP_WINDOW_INDEX:] - raw_start_frame

    csv_path = OUT_DIR / "cropped_adaptive_window_center_gps.csv"
    png_path = OUT_DIR / "cropped_adaptive_gps_map_with_basemap.png"
    txt_path = OUT_DIR / "cropped_adaptive_gps_map_summary.txt"

    dist_stats = _write_window_csv(csv_path, cropped_gps, centers_cropped)
    _make_map(png_path, STEM, cropped_gps, centers_cropped)
    _write_summary(txt_path, BIN_PATH, cropped_gps, centers_cropped, dist_stats)

    print(f"[gps] window points after crop: {dist_stats['n_window_points']}")
    print(f"[gps] distance to TX: {dist_stats['distance_min_m']:.2f}-{dist_stats['distance_max_m']:.2f} "
          f"(mean {dist_stats['distance_mean_m']:.2f}) m")
    print(f"  -> {csv_path}\n  -> {png_path}\n  -> {txt_path}")


def crop_pdp_waterfall() -> None:
    n_total = BIN_PATH.stat().st_size // FRAME_LEN
    starts = np.arange(0, max(1, n_total - WINDOW + 1), STEP, dtype=int)
    starts_cropped = starts[CROP_WINDOW_INDEX:]
    raw_start_frame = int(starts_cropped[0])

    needed = np.unique(np.concatenate([np.arange(s, s + WINDOW, dtype=int) for s in starts_cropped]))
    needed = needed[needed < n_total]

    raw = np.memmap(BIN_PATH, dtype=np.uint8, mode="r")
    frames = np.array(raw[: n_total * FRAME_LEN].reshape(n_total, FRAME_LEN)[needed], copy=True)

    b2b = np.load(B2B_PATH, mmap_mode="r")
    b2b_ref = np.array(b2b[0], dtype=np.complex128)

    cir = regularized_frequency_calibrate(
        _sliding_correlate(_parse_iq(frames)),
        b2b_ref,
        regularization=1e-3,
        axis=1,
        attenuation_db=B2B_ATTENUATION_DB,
    )
    pos = {int(idx): i for i, idx in enumerate(needed)}

    delay_bins = np.arange(MAX_DELAY_BINS, dtype=np.int64)
    delay_ns = delay_bins.astype(np.float64) / float(BW_HZ) * 1e9

    orig_rows = []
    times = []
    for s in starts_cropped:
        s = int(s)
        idx_in_cir = [pos[k] for k in range(s, s + WINDOW)]
        seg = cir[idx_in_cir, :MAX_DELAY_BINS]
        orig_rows.append(np.mean(np.abs(seg) ** 2, axis=0))
        times.append((s + WINDOW / 2 - raw_start_frame) / FRAME_RATE_HZ)

    orig_db = 10 * np.log10(np.vstack(orig_rows) + 1e-30)
    times_arr = np.asarray(times)

    out_path = OUT_DIR / "cropped_adaptive_original_pdp_waterfall.png"
    _save_pdp_waterfall(
        orig_db, times_arr, delay_ns,
        f"{STEM} (lead-in removed): 20-frame original PDP (B2B cal, step=1s, unnormalized)",
        out_path,
        cbar_label="PDP power (dB, unnormalized)",
    )
    print(f"[pdp] windows after crop: {len(starts_cropped)}, time range {times_arr[0]:.1f}-{times_arr[-1]:.1f}s")
    print(f"  -> {out_path}")


def crop_delay_time_scatter() -> None:
    src_csv = OUT_DIR / "adaptive_sage_mpc_candidates.csv"
    with src_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    time_offset = CROP_WINDOW_INDEX * STEP / FRAME_RATE_HZ  # = 85.0s
    cropped_rows = []
    for r in rows:
        wi = int(r["windowIndex"])
        if wi < CROP_WINDOW_INDEX:
            continue
        cropped_rows.append({
            **r,
            "windowIndex": wi - CROP_WINDOW_INDEX,
            "frameStart": int(r["frameStart"]) - CROP_WINDOW_INDEX * STEP,
            "frameEnd": int(r["frameEnd"]) - CROP_WINDOW_INDEX * STEP,
            "timeSec": float(r["timeSec"]) - time_offset,
            "delayNs": float(r["delayNs"]),
            "powerDb": float(r["powerDb"]),
        })

    out_csv = OUT_DIR / "cropped_adaptive_sage_mpc_candidates.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(cropped_rows)

    import matplotlib.pyplot as plt

    t = np.array([r["timeSec"] for r in cropped_rows])
    delay = np.array([r["delayNs"] for r in cropped_rows])
    p = np.array([r["powerDb"] for r in cropped_rows])
    rel = p - np.max(p)
    order = np.argsort(rel)
    t, delay, rel = t[order], delay[order], rel[order]
    delay_hi = min(6000, max(300, float(np.percentile(delay, 98) + 200)))

    fig, ax = plt.subplots(figsize=(12, 5.6))
    sc = ax.scatter(t, delay, c=rel, s=36, cmap="hot", vmin=-35, vmax=0,
                     edgecolors="black", linewidths=0.12, alpha=0.82)
    ax.set_title(f"{STEM} (lead-in removed): adaptive SAGE MPC Delay-Time")
    ax.set_xlabel("Measurement time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(0, delay_hi)
    ax.grid(alpha=0.25)
    cbar = fig.colorbar(sc, ax=ax, pad=0.012)
    cbar.set_label("Relative MPC power (dB)")
    ax.text(0.01, 0.02, f"N={len(cropped_rows)} MPCs (lead-in removed)",
            transform=ax.transAxes, fontsize=8,
            bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"))
    fig.tight_layout()
    out_png = OUT_DIR / "cropped_adaptive_separate_delay_time_power.png"
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)

    print(f"[dt] N(MPC) after crop: {len(cropped_rows)} (was {len(rows)})")
    print(f"  -> {out_csv}\n  -> {out_png}")


if __name__ == "__main__":
    crop_gps_map()
    crop_pdp_waterfall()
    crop_delay_time_scatter()
