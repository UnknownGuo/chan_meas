"""Run adaptive SAGE (B2B-calibrated, coverage=0.95, w20/s100) on remaining
Zhangjiakou bin files and produce the three figures the user wants:

  - adaptive_original_pdp_waterfall.png
  - adaptive_separate_delay_time_power.png
  - adaptive_gps_map_with_basemap.png  (handled by generate_adaptive_sage_gps_maps.py
    afterwards, since it uses the same adaptive window-center scheme)

Outputs go to:
  /home/guo/桌面/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100/<stem>/

A few extra by-products (CSV summaries, paths-per-window plot) are also written
because the established 5 special files have them; this keeps the directory
layout uniform across all measurements.
"""
from __future__ import annotations

import csv
import json
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.b2b_frequency import regularized_frequency_calibrate
from src.io.bin_read import BW_HZ, FRAME_LEN, FRAME_RATE_HZ, _parse_iq, _sliding_correlate
from src.signal.sage_adaptive import estimate_window_paths_adaptive
from src.signal.sage_validation import SageCandidate, classify_candidates_by_tracks

DATA_DIR = Path("/mnt/win_data/data_mea/zjk_mea")
OUT_ROOT = Path("/home/guo/桌面/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100")
B2B_PATH = Path("/mnt/win_data/data_mea/zjk_mea/calibration/b2b_cir.npy")
B2B_ATTENUATION_DB = 60.0  # fixed attenuator inserted only for the B2B loopback recording

# Files that already have the three required figures and full pipeline output.
# (Empty here so that running this script reprocesses every bin file in DATA_DIR.)
ALREADY_DONE: set[str] = set()

# Adaptive SAGE settings — must match the established pipeline.
WINDOW = 20
STEP = 100
MAX_DELAY_BINS = 300
MAX_PATHS_HARD = 30
COVERAGE_TARGET = 0.97  # raised from 0.95 to capture more weak MPCs
MIN_COVERAGE_GAIN = 0.001  # relaxed gain floor so weak-but-real MPCs survive

CSV_FIELDS = [
    "file",
    "windowIndex",
    "frameStart",
    "frameEnd",
    "timeSec",
    "pathId",
    "delayBin",
    "delayNs",
    "dopplerHz",
    "powerDb",
    "scoreDb",
    "amplitudeReal",
    "amplitudeImag",
]


def _read_indexed_frames(path: Path, indices: np.ndarray) -> np.ndarray:
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    n_total = len(raw) // FRAME_LEN
    frames = raw[: n_total * FRAME_LEN].reshape(n_total, FRAME_LEN)
    return np.array(frames[indices], copy=True)


def _save_pdp_waterfall(
    mat_db: np.ndarray,
    times: np.ndarray,
    delay_ns: np.ndarray,
    title: str,
    out_path: Path,
    vmin: float | None = None,
    vmax: float | None = None,
    cbar_label: str = "PDP power (dB, unnormalized)",
) -> None:
    fig, ax = plt.subplots(figsize=(12, 5.6))
    im = ax.imshow(
        mat_db,
        origin="lower",
        aspect="auto",
        cmap="turbo",
        vmin=vmin,
        vmax=vmax,
        extent=[float(delay_ns[0]), float(delay_ns[-1]), float(times[0]), float(times[-1])],
    )
    ax.set_title(title)
    ax.set_xlabel("Delay (ns)")
    ax.set_ylabel("Measurement time (s)")
    ax.set_xlim(0, 6000)
    cbar = fig.colorbar(im, ax=ax, pad=0.012)
    cbar.set_label(cbar_label)
    fig.tight_layout()
    fig.savefig(out_path, dpi=210, bbox_inches="tight")
    plt.close(fig)


def _save_delay_time_scatter(rows: list[dict], out_dir: Path, prefix: str) -> None:
    if not rows:
        return
    t = np.array([r["timeSec"] for r in rows])
    delay = np.array([r["delayNs"] for r in rows])
    p = np.array([r["powerDb"] for r in rows])
    rel = p - np.max(p)
    order = np.argsort(rel)
    t, delay, rel = t[order], delay[order], rel[order]
    delay_hi = min(6000, max(300, float(np.percentile(delay, 98) + 200)))
    fig, ax = plt.subplots(figsize=(12, 5.6))
    sc = ax.scatter(
        t,
        delay,
        c=rel,
        s=36,
        cmap="hot",
        vmin=-35,
        vmax=0,
        edgecolors="black",
        linewidths=0.12,
        alpha=0.82,
    )
    ax.set_title(f"{prefix}: adaptive SAGE MPC Delay-Time")
    ax.set_xlabel("Measurement time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(0, delay_hi)
    ax.grid(alpha=0.25)
    cbar = fig.colorbar(sc, ax=ax, pad=0.012)
    cbar.set_label("Relative MPC power (dB)")
    ax.text(
        0.01,
        0.02,
        f"N={len(rows)} MPCs; adaptive coverage={COVERAGE_TARGET*100:.0f}%",
        transform=ax.transAxes,
        fontsize=8,
        bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"),
    )
    fig.tight_layout()
    fig.savefig(out_dir / "adaptive_separate_delay_time_power.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _save_doppler_time_scatter(rows: list[dict], out_dir: Path, prefix: str) -> None:
    if not rows:
        return
    t = np.array([r["timeSec"] for r in rows])
    dop = np.array([r["dopplerHz"] for r in rows])
    p = np.array([r["powerDb"] for r in rows])
    rel = p - np.max(p)
    order = np.argsort(rel)
    t, dop, rel = t[order], dop[order], rel[order]
    dop_abs = max(1.0, float(np.percentile(np.abs(dop), 98)) * 1.18)
    fig, ax = plt.subplots(figsize=(12, 5.6))
    sc = ax.scatter(
        t,
        dop,
        c=rel,
        s=36,
        cmap="hot",
        vmin=-35,
        vmax=0,
        edgecolors="black",
        linewidths=0.12,
        alpha=0.82,
    )
    ax.axhline(0, color="white", lw=2.2, alpha=0.85, zorder=0)
    ax.axhline(0, color="black", lw=0.7, alpha=0.45, zorder=1)
    ax.set_title(f"{prefix}: adaptive SAGE MPC Doppler-Time")
    ax.set_xlabel("Measurement time (s)")
    ax.set_ylabel("Doppler (Hz)")
    ax.set_ylim(-dop_abs, dop_abs)
    ax.grid(alpha=0.25)
    cbar = fig.colorbar(sc, ax=ax, pad=0.012)
    cbar.set_label("Relative MPC power (dB)")
    ax.text(
        0.01,
        0.02,
        f"N={len(rows)} MPCs; adaptive coverage={COVERAGE_TARGET*100:.0f}%",
        transform=ax.transAxes,
        fontsize=8,
        bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"),
    )
    fig.tight_layout()
    fig.savefig(out_dir / "adaptive_separate_doppler_time_power.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def process_one_file(path: Path, b2b_ref: np.ndarray) -> dict:
    out_dir = OUT_ROOT / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    n_total = path.stat().st_size // FRAME_LEN
    starts = np.arange(0, max(1, n_total - WINDOW + 1), STEP, dtype=int)
    if starts.size == 0:
        starts = np.array([0], dtype=int)

    needed = np.unique(np.concatenate([np.arange(s, s + WINDOW, dtype=int) for s in starts]))
    needed = needed[needed < n_total]

    frames = _read_indexed_frames(path, needed)
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

    orig_rows: list[np.ndarray] = []
    times: list[float] = []
    rows: list[dict] = []
    recon_db_mat = np.zeros((len(starts), MAX_DELAY_BINS), dtype=np.float64)
    recon_lin = np.zeros_like(recon_db_mat)
    n_paths_per_window: list[int] = []

    for wi, s in enumerate(starts):
        s = int(s)
        idx_in_cir = []
        ok = True
        for k in range(s, s + WINDOW):
            if k not in pos:
                ok = False
                break
            idx_in_cir.append(pos[k])
        if not ok or len(idx_in_cir) != WINDOW:
            continue

        seg = cir[idx_in_cir, :MAX_DELAY_BINS]
        pdp = np.mean(np.abs(seg) ** 2, axis=0)
        orig_rows.append(pdp)
        times.append((s + WINDOW / 2) / FRAME_RATE_HZ)

        detailed = estimate_window_paths_adaptive(
            seg,
            delay_bins=delay_bins,
            bandwidth_hz=BW_HZ,
            frame_rate_hz=FRAME_RATE_HZ,
            coverage_target=COVERAGE_TARGET,
            min_coverage_gain=MIN_COVERAGE_GAIN,
            max_paths_hard=MAX_PATHS_HARD,
            coverage_delay_bins=MAX_DELAY_BINS,
            enable_weak_nonprominent_prune=False,
        )
        n_paths_per_window.append(len(detailed.final_paths))
        for p in detailed.final_paths:
            rec = {
                "file": path.name,
                "windowIndex": wi,
                "frameStart": s,
                "frameEnd": s + WINDOW,
                "timeSec": float((s + WINDOW / 2) / FRAME_RATE_HZ),
                "pathId": p.path_id,
                "delayBin": p.delay_bin,
                "delayNs": p.delay_ns,
                "dopplerHz": p.doppler_hz,
                "powerDb": p.power_db,
                "scoreDb": p.score_db,
                "amplitudeReal": float(np.real(p.amplitude)),
                "amplitudeImag": float(np.imag(p.amplitude)),
            }
            rows.append(rec)
            center = int(round(p.delay_ns / (1e9 / float(BW_HZ))))
            amp2 = 10 ** (p.power_db / 10.0)
            for off in range(-4, 5):
                j = center + off
                if 0 <= j < MAX_DELAY_BINS:
                    recon_lin[wi, j] += amp2 * np.exp(-0.5 * (off / 1.2) ** 2)

    if not orig_rows:
        return {"file": path.name, "error": "no valid windows"}

    orig = np.vstack(orig_rows)
    times_arr = np.asarray(times)
    orig_db = 10 * np.log10(orig + 1e-30)
    recon_db = 10 * np.log10(recon_lin + 1e-30)

    _save_pdp_waterfall(
        orig_db,
        times_arr,
        delay_ns,
        f"{path.name}: 20-frame original PDP (B2B cal, step=1s, unnormalized)",
        out_dir / "adaptive_original_pdp_waterfall.png",
        cbar_label="PDP power (dB, unnormalized)",
    )
    _save_pdp_waterfall(
        recon_db,
        times_arr,
        delay_ns,
        f"{path.name}: adaptive SAGE reconstructed PDP (unnormalized)",
        out_dir / "adaptive_reconstructed_pdp_waterfall.png",
        cbar_label="Reconstructed PDP power (dB, unnormalized)",
    )

    fig, axs = plt.subplots(1, 2, figsize=(14, 5.3), sharey=True)
    for ax, mat, title in [
        (axs[0], orig_db, "20-frame original PDP"),
        (axs[1], recon_db, "adaptive SAGE reconstructed"),
    ]:
        im = ax.imshow(
            mat,
            origin="lower",
            aspect="auto",
            cmap="turbo",
            extent=[float(delay_ns[0]), float(delay_ns[-1]), float(times_arr[0]), float(times_arr[-1])],
        )
        ax.set_title(title)
        ax.set_xlabel("Delay (ns)")
        ax.set_xlim(0, 6000)
    axs[0].set_ylabel("Measurement time (s)")
    cbar = fig.colorbar(im, ax=axs.ravel().tolist(), pad=0.015)
    cbar.set_label("PDP power (dB, unnormalized)")
    fig.suptitle(f"{path.name}: adaptive SAGE original vs reconstructed")
    fig.savefig(out_dir / "adaptive_original_vs_reconstructed.png", dpi=210, bbox_inches="tight")
    plt.close(fig)

    _save_delay_time_scatter(rows, out_dir, path.stem)
    _save_doppler_time_scatter(rows, out_dir, path.stem)

    fig, ax = plt.subplots(figsize=(12, 3.2))
    ax.bar(times_arr, n_paths_per_window, width=0.8, color="steelblue", edgecolor="black", linewidth=0.3)
    ax.set_xlabel("Measurement time (s)")
    ax.set_ylabel("Paths per window")
    ax.set_title(f"{path.name}: adaptive SAGE paths per 20-frame window (step=1s)")
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out_dir / "adaptive_paths_per_window.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    cands = [
        SageCandidate(
            file=r["file"],
            window_index=r["windowIndex"],
            time_sec=r["timeSec"],
            candidate_id=i + 1,
            delay_ns=r["delayNs"],
            doppler_hz=r["dopplerHz"],
            power_db=r["powerDb"],
            score_db=r["scoreDb"],
        )
        for i, r in enumerate(rows)
    ]
    val = classify_candidates_by_tracks(
        cands,
        delay_gate_ns=120,
        doppler_gate_hz=50,
        max_gap_windows=2,
        min_track_length=3,
    )
    track_summary: list[dict] = []
    for tr in val.tracks:
        track_summary.append(
            {
                "file": path.name,
                "trackId": tr.track_id,
                "classification": tr.classification,
                "rejectReason": tr.reject_reason,
                "lengthWindows": tr.length_windows,
                "startWindow": tr.start_window,
                "endWindow": tr.end_window,
                "delayMedianNs": tr.delay_median_ns,
                "delayStdNs": tr.delay_std_ns,
                "dopplerMedianHz": tr.doppler_median_hz,
                "dopplerStdHz": tr.doppler_std_hz,
                "powerMedianDb": tr.power_median_db,
                "powerMaxDb": tr.power_max_db,
            }
        )

    with (out_dir / "adaptive_sage_mpc_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    if track_summary:
        with (out_dir / "adaptive_validated_track_summary.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(track_summary[0].keys()))
            w.writeheader()
            w.writerows(track_summary)

    return {
        "file": path.name,
        "framesTotal": int(n_total),
        "windowFrames": WINDOW,
        "stepFrames": STEP,
        "nWindows": int(len(starts)),
        "mpcCandidates": int(len(rows)),
        "validatedTracks": int(sum(t.classification == "validated_mpc" for t in val.tracks)),
        "shortLivedTracks": int(sum(t.classification != "validated_mpc" for t in val.tracks)),
        "medianPathsPerWindow": float(np.median(n_paths_per_window)) if n_paths_per_window else 0.0,
        "maxPathsPerWindow": int(max(n_paths_per_window)) if n_paths_per_window else 0,
        "outputDir": str(out_dir),
    }


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    bins = sorted(p for p in DATA_DIR.glob("*.bin") if p.stem != "cali_data" and p.stem not in ALREADY_DONE)
    if not bins:
        print("Nothing to do — all bin files already processed.")
        return 0

    print(f"Processing {len(bins)} files; output -> {OUT_ROOT}")
    for p in bins:
        print(f"  - {p.name} ({p.stat().st_size/1e6:.1f} MB)")

    b2b = np.load(B2B_PATH, mmap_mode="r")
    b2b_ref = np.array(b2b[0], dtype=np.complex128)

    summary: list[dict] = []
    for i, path in enumerate(bins, 1):
        print(f"\n[{i}/{len(bins)}] {path.name}", flush=True)
        try:
            rec = process_one_file(path, b2b_ref)
            summary.append(rec)
            print(f"  -> {rec.get('outputDir', 'ERROR')}", flush=True)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            summary.append({"file": path.name, "error": str(e)})

    # Update aggregate summaries (append/refresh).
    out_json = OUT_ROOT / "adaptive_summary.json"
    if out_json.exists():
        try:
            old = json.loads(out_json.read_text(encoding="utf-8"))
            existing = old.get("files", [])
            existing_names = {r.get("file") for r in existing}
            merged = existing + [r for r in summary if r.get("file") not in existing_names]
        except Exception:
            merged = summary
    else:
        merged = summary
    out_json.write_text(
        json.dumps({"outputDir": str(OUT_ROOT), "files": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSummary -> {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
