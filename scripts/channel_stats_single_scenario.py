"""Channel statistics (Path Loss / Shadow Fading / Multipath Fading / RMS Delay
Spread / K-factor / PDP waterfall) for one zjk_mea .bin file.

Ports the methodology in matlab_code_reference/Wuhan_3_scenarios/ (PL_results_new.m,
calculateRMSDelaySpread.m, K_factor_cal.m, PDP_figure.m) to Python, with two
deliberate deviations agreed on during diagnosis in this project:

1. Path Loss / K-factor / RMS DS use the ORIGINAL (non-coherent, per-window
   averaged) PDP power within a distance gate, NOT the SAGE-extracted path
   power sum. Reason: adaptive SAGE's coverage ratio (captured-path power /
   true PDP energy) varies ~5x across scenes/distances in this dataset, so
   using SAGE path-power sums as a stand-in for total received power would
   bake an algorithm artifact into the curves.

2. LSF/SSF sliding-window sizes are NOT the literal 600*lambda/120*lambda from
   the MATLAB reference (that convention assumes GHz-band carriers; at this
   scenario's 420 MHz carrier and ~190 m distance span it would give windows
   bigger than the whole measurement). Instead:
     win_LSF = 20 m       (typical shadowing decorrelation distance, ~freq-independent)
     win_SSF = 4 * lambda (a few wavelengths; averages out fast fading)

Both RAW (full delay-gate, includes noise floor at large delay) and DENOISED
(per-window noise floor estimated from the tail of the gated PDP, subtracted
and thresholded at NOISE_MARGIN_DB above floor) variants are computed and
plotted side by side, because RMS Delay Spread / K-factor are very sensitive
to exactly this noise-floor-vs-gate-width choice (see report in conversation:
raw RMS DS ~870 ns / K ~0.9 dB look implausible for an 8-197 m near-field scene
because most of the 2000 m delay gate beyond ~1500 ns is pure noise floor).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.b2b_frequency import regularized_frequency_calibrate
from src.calibration.constants import ZJK_B2B_ATTENUATION_DB, ZJK_B2B_REGULARIZATION
from src.io.bin_read import BW_HZ, FRAME_LEN, FRAME_RATE_HZ, _parse_gps, _parse_iq, _sliding_correlate
from src.paths import ZJK_RAW_DIR
from src.ui_dataset import DEFAULT_ZJK_TX_GPS, distance_3d_m

# ---- scenario + physical params ----
BIN_NAME = "0m-0m-all-firstanteaan-rotate.bin"
CARRIER_HZ = 420e6  # zjk_mea hardware carrier (memory.md), NOT a tunable here
LAMBDA_M = 299_792_458.0 / CARRIER_HZ
DELAY_GATE_M = 2000.0
WINDOW_FRAMES = 20
STEP_FRAMES = 100
WIN_LSF_M = 20.0
WIN_SSF_M = 4.0 * LAMBDA_M

# Denoising: noise floor estimated from the tail of the gated PDP (visually
# confirmed pure-noise region in the waterfall plot), bins within MARGIN_DB of
# that floor are zeroed after subtraction.
NOISE_REGION_START_NS = 4000.0
NOISE_MARGIN_DB = 6.0

OUT_DIR = ROOT / "outputs" / "channel_stats" / Path(BIN_NAME).stem
FONT = {"fontname": "Times New Roman", "fontsize": 18, "fontweight": "bold"}


def calculate_rms_delay_spread(delay_ns: np.ndarray, power_lin: np.ndarray) -> tuple[float, float]:
    """Port of calculateRMSDelaySpread.m. power_lin must be linear (not dB)."""
    power_lin = np.clip(power_lin, 0.0, None)
    total = float(np.sum(power_lin))
    if total <= 0:
        return 0.0, 0.0
    mean_delay = float(np.sum(delay_ns * power_lin) / total)
    mean_sq_delay = float(np.sum(delay_ns**2 * power_lin) / total)
    rms = float(np.sqrt(max(mean_sq_delay - mean_delay**2, 0.0)))
    return rms, mean_delay


def denoise_pdp(delay_ns: np.ndarray, pdp_lin: np.ndarray) -> np.ndarray:
    tail_mask = delay_ns >= NOISE_REGION_START_NS
    if not np.any(tail_mask):
        return pdp_lin
    noise_floor_lin = float(np.median(pdp_lin[tail_mask]))
    threshold_lin = noise_floor_lin * 10.0 ** (NOISE_MARGIN_DB / 10.0)
    out = np.clip(pdp_lin - noise_floor_lin, 0.0, None)
    return np.where(pdp_lin > threshold_lin, out, 0.0)


def sliding_mean_by_distance(distance_sorted: np.ndarray, values_sorted: np.ndarray, window_m: float) -> np.ndarray:
    out = np.zeros_like(values_sorted)
    half = window_m / 2.0
    for k in range(values_sorted.size):
        mask = np.abs(distance_sorted - distance_sorted[k]) <= half
        out[k] = np.mean(values_sorted[mask])
    return out


def style_axes(ax) -> None:
    ax.grid(alpha=0.3)
    ax.tick_params(labelsize=14)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontname("Times New Roman")


def _ecdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(values)
    f = np.arange(1, x.size + 1) / x.size
    return f, x


def compute_window_series(
    cir: np.ndarray,
    gps: dict[str, np.ndarray],
    gated_idx: np.ndarray,
    delay_ns_gated: np.ndarray,
    starts: np.ndarray,
    *,
    denoise: bool,
) -> dict[str, Any]:
    tx = DEFAULT_ZJK_TX_GPS
    distance_m, pl_db, k_db, rms_ds_ns, time_sec, pdp_db_rows = [], [], [], [], [], []
    for s in starts:
        seg = cir[s : s + WINDOW_FRAMES, gated_idx]
        pdp_lin = np.mean(np.abs(seg) ** 2, axis=0)
        if denoise:
            pdp_lin = denoise_pdp(delay_ns_gated, pdp_lin)
        total_lin = float(np.sum(pdp_lin))
        if total_lin <= 0:
            continue
        peak_idx = int(np.argmax(pdp_lin))
        peak_lin = float(pdp_lin[peak_idx])
        scatter_lin = total_lin - peak_lin

        center = s + WINDOW_FRAMES // 2
        rms_ns, _ = calculate_rms_delay_spread(delay_ns_gated, pdp_lin)

        distance_m.append(distance_3d_m(tx, gps["lat"][center], gps["lon"][center], gps["alt"][center]))
        pl_db.append(10.0 * np.log10(total_lin))
        k_db.append(10.0 * np.log10(peak_lin / scatter_lin) if scatter_lin > 0 else np.nan)
        rms_ds_ns.append(rms_ns)
        time_sec.append(center / FRAME_RATE_HZ)
        pdp_db_rows.append(10.0 * np.log10(pdp_lin + 1e-30))

    return {
        "distance_m": np.asarray(distance_m),
        "pl_db": np.asarray(pl_db),
        "k_db": np.asarray(k_db),
        "rms_ds_ns": np.asarray(rms_ds_ns),
        "time_sec": np.asarray(time_sec),
        "pdp_db_mat": np.asarray(pdp_db_rows),
    }


def compute_window_series_sage_from_export(dataset_json_path: Path) -> dict[str, Any]:
    """Reuse the already-exported UI dataset's adaptive-SAGE windowTracks
    (same params: coverage_target=0.97, min_coverage_gain=0.001,
    enable_weak_nonprominent_prune=True) instead of recomputing SAGE from
    scratch. Path Loss / K-factor / RMS DS use a non-coherent power sum over
    each window's final_paths (sum |amplitude|^2), matching
    PL_results_new.m / K_factor_cal.m, not a coherent complex-amplitude sum.
    """
    import json

    dataset = json.loads(dataset_json_path.read_text(encoding="utf-8"))
    frame_stats = [item for item in (dataset.get("frameStats") or []) if "distanceM" in item]
    fs_frames = np.array([float(item["frame"]) for item in frame_stats])
    fs_dist = np.array([float(item["distanceM"]) for item in frame_stats])

    def nearest_distance(frame: float) -> float | None:
        if fs_frames.size == 0:
            return None
        return float(fs_dist[np.argmin(np.abs(fs_frames - frame))])

    distance_m, pl_db, k_db, rms_ds_ns, time_sec = [], [], [], [], []
    scatter_points: list[tuple[float, float, float]] = []  # (time_sec, delay_ns, power_db)
    for window in dataset["sageDelayDoppler"]["windowTracks"]:
        peaks = window.get("peaks") or []
        if not peaks:
            continue
        powers_lin = np.array([p["amplitudeReal"] ** 2 + p["amplitudeImag"] ** 2 for p in peaks])
        delays_ns = np.array([p["delayNs"] for p in peaks])
        total_lin = float(np.sum(powers_lin))
        peak_idx = int(np.argmax(powers_lin))
        peak_lin = float(powers_lin[peak_idx])
        scatter_lin = total_lin - peak_lin

        dist = nearest_distance(float(window["frame"]))
        if dist is None or dist <= 0:
            continue
        rms_ns, _ = calculate_rms_delay_spread(delays_ns, powers_lin)
        t = float(window["timeSec"])

        distance_m.append(dist)
        pl_db.append(10.0 * np.log10(total_lin))
        k_db.append(10.0 * np.log10(peak_lin / scatter_lin) if scatter_lin > 0 else np.nan)
        rms_ds_ns.append(rms_ns)
        time_sec.append(t)
        for p in peaks:
            scatter_points.append((t, p["delayNs"], p["powerDb"]))

    return {
        "distance_m": np.asarray(distance_m),
        "pl_db": np.asarray(pl_db),
        "k_db": np.asarray(k_db),
        "rms_ds_ns": np.asarray(rms_ds_ns),
        "time_sec": np.asarray(time_sec),
        "scatter_points": scatter_points,
    }


def make_plots(series: dict[str, Any], delay_ns_gated: np.ndarray, out_dir: Path, tag: str) -> dict[str, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    distance_m, pl_db, k_db, rms_ds_ns, time_sec = (
        series["distance_m"], series["pl_db"], series["k_db"], series["rms_ds_ns"], series["time_sec"]
    )
    pdp_db_mat = series.get("pdp_db_mat")
    scatter_points = series.get("scatter_points")

    # ---- 1. Path Loss ----
    log_d = np.log10(distance_m)
    coeffs = np.polyfit(log_d, pl_db, 1)
    pl_fit = np.polyval(coeffs, log_d)
    ple = -coeffs[0] / 10.0
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(distance_m, pl_db, s=18, alpha=0.6, color="#2474d2", label="Measurement")
    order = np.argsort(distance_m)
    ax.plot(distance_m[order], pl_fit[order], "-", color="#d24724", linewidth=2.5, label=f"Fit (PLE={ple:.2f})")
    ax.set_xscale("log")
    ax.set_xlabel("Distance (m)", **FONT)
    ax.set_ylabel("Received Power / Path Loss proxy (dB)", **FONT)
    ax.set_title(f"{BIN_NAME}: Path Loss [{tag}]", **FONT)
    ax.legend(fontsize=12)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "1_path_loss.png", dpi=180)
    plt.close(fig)

    # ---- 2. Shadow Fading ----
    delta_pl = pl_db - pl_fit
    sort_idx = np.argsort(distance_m)
    d_sorted = distance_m[sort_idx]
    delta_sorted = delta_pl[sort_idx]
    lsf_sorted = sliding_mean_by_distance(d_sorted, delta_sorted, WIN_LSF_M)
    mu, sigma = float(np.mean(lsf_sorted)), float(np.std(lsf_sorted))
    fig, ax = plt.subplots(figsize=(8, 5.5))
    f, x = _ecdf(lsf_sorted)
    ax.plot(x, f, "--", color="#2474d2", linewidth=2, label="Measured Shadow Fading")
    x_fit = np.linspace(x.min() - 3, x.max() + 3, 200)
    ax.plot(x_fit, stats.norm.cdf(x_fit, mu, sigma), "-", color="#d24724", linewidth=2.5, label=f"Gaussian Fit (μ={mu:.2f}, σ={sigma:.2f})")
    ax.set_xlabel("Shadow Fading (dB)", **FONT)
    ax.set_ylabel("Cumulative Probability", **FONT)
    ax.set_title(f"{BIN_NAME}: Shadow Fading [{tag}] (LSF win={WIN_LSF_M:.0f} m)", **FONT)
    ax.legend(fontsize=12, loc="lower right")
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "2_shadow_fading.png", dpi=180)
    plt.close(fig)

    # ---- 3. Multipath (small-scale) Fading ----
    residual2 = delta_sorted - lsf_sorted
    ssf_sorted_db = sliding_mean_by_distance(d_sorted, residual2, WIN_SSF_M)
    ssf_amp = 10.0 ** (ssf_sorted_db[np.abs(ssf_sorted_db) > 0.02] / 20.0)
    nu, loc, scale = stats.nakagami.fit(ssf_amp, floc=0)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    f, x = _ecdf(ssf_amp)
    ax.plot(x, f, "--", color="#2474d2", linewidth=2, label="Measured Multipath Fading")
    x_fit = np.linspace(0.01, x.max() + 0.2, 200)
    ax.plot(x_fit, stats.nakagami.cdf(x_fit, nu, loc=loc, scale=scale), "-", color="#d24724", linewidth=2.5, label=f"Nakagami Fit (μ={nu:.2f}, ω={scale**2:.2f})")
    ax.set_xlabel("Signal Amplitude (Linear Scale)", **FONT)
    ax.set_ylabel("Cumulative Probability", **FONT)
    ax.set_title(f"{BIN_NAME}: Multipath Fading [{tag}] (SSF win={WIN_SSF_M:.2f} m = 4λ)", **FONT)
    ax.legend(fontsize=12, loc="lower right")
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "3_multipath_fading.png", dpi=180)
    plt.close(fig)

    # ---- 4. RMS Delay Spread ----
    rms_valid = rms_ds_ns[rms_ds_ns > 0]
    c, loc, scale = stats.genpareto.fit(rms_valid)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    f, x = _ecdf(rms_valid)
    ax.plot(x, f, "--", color="#2474d2", linewidth=2, label="Measured RMS Delay Spread")
    x_fit = np.linspace(0, rms_valid.max() * 1.2, 200)
    ax.plot(x_fit, stats.genpareto.cdf(x_fit, c, loc=loc, scale=scale), "-", color="#d24724", linewidth=2.5, label=f"GP Fit (k={c:.2f})")
    ax.set_xlabel("RMS Delay Spread (ns)", **FONT)
    ax.set_ylabel("Cumulative Probability", **FONT)
    ax.set_title(f"{BIN_NAME}: RMS Delay Spread [{tag}]", **FONT)
    ax.legend(fontsize=12, loc="lower right")
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "4_rms_delay_spread.png", dpi=180)
    plt.close(fig)

    # ---- 5. K-factor ----
    k_valid = k_db[np.isfinite(k_db)]
    mu_k, sigma_k = float(np.mean(k_valid)), float(np.std(k_valid))
    fig, ax = plt.subplots(figsize=(8, 5.5))
    f, x = _ecdf(k_valid)
    ax.plot(x, f, "--", color="#2474d2", linewidth=2, label="Measured K-factor")
    x_fit = np.linspace(x.min() - 3, x.max() + 3, 200)
    ax.plot(x_fit, stats.norm.cdf(x_fit, mu_k, sigma_k), "-", color="#d24724", linewidth=2.5, label=f"Gaussian Fit (μ={mu_k:.2f}, σ={sigma_k:.2f})")
    ax.set_xlabel("K-factor (dB)", **FONT)
    ax.set_ylabel("Cumulative Probability", **FONT)
    ax.set_title(f"{BIN_NAME}: K-factor [{tag}]", **FONT)
    ax.legend(fontsize=12, loc="lower right")
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "5_k_factor.png", dpi=180)
    plt.close(fig)

    # ---- 6. PDP waterfall (or SAGE delay-time MPC scatter, if no full PDP matrix) ----
    fig, ax = plt.subplots(figsize=(11, 5.5))
    if pdp_db_mat is not None:
        im = ax.imshow(
            pdp_db_mat.T,
            origin="lower",
            aspect="auto",
            cmap="hot",
            extent=[time_sec[0], time_sec[-1], delay_ns_gated[0], delay_ns_gated[-1]],
        )
        cb = fig.colorbar(im, ax=ax, pad=0.012)
        cb.set_label("dB", **FONT)
        ax.set_title(f"{BIN_NAME}: PDP waterfall [{tag}]", **FONT)
    else:
        pts = np.asarray(scatter_points)
        t_pts, delay_pts, power_pts = pts[:, 0], pts[:, 1], pts[:, 2]
        rel = power_pts - np.max(power_pts)
        order = np.argsort(rel)
        sc = ax.scatter(t_pts[order], delay_pts[order], c=rel[order], s=14, cmap="hot", vmin=-35, vmax=0, edgecolors="black", linewidths=0.1, alpha=0.85)
        cb = fig.colorbar(sc, ax=ax, pad=0.012)
        cb.set_label("Relative MPC power (dB)", **FONT)
        ax.set_ylim(delay_ns_gated[0], delay_ns_gated[-1])
        ax.set_title(f"{BIN_NAME}: SAGE MPC delay-time scatter [{tag}]", **FONT)
    ax.set_xlabel("Time (s)", **FONT)
    ax.set_ylabel("Delay (ns)", **FONT)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "6_pdp_waterfall.png", dpi=180)
    plt.close(fig)

    return {
        "ple": ple,
        "shadow_sigma_db": sigma,
        "k_mean_db": mu_k,
        "rms_ds_mean_ns": float(np.mean(rms_valid)),
    }


def main() -> None:
    path = ZJK_RAW_DIR / BIN_NAME
    b2b = np.load(ZJK_RAW_DIR / "calibration" / "b2b_cir.npy", mmap_mode="r")
    b2b_ref = np.asarray(b2b[0], dtype=np.complex128)

    n_total = path.stat().st_size // FRAME_LEN
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    frames = np.array(raw[: n_total * FRAME_LEN].reshape(n_total, FRAME_LEN), copy=True)
    gps = _parse_gps(frames)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    cir = regularized_frequency_calibrate(
        cir, b2b_ref, regularization=ZJK_B2B_REGULARIZATION, axis=1, attenuation_db=ZJK_B2B_ATTENUATION_DB
    )
    n_delay = cir.shape[1]

    gate_ns_max = DELAY_GATE_M / 299_792_458.0 * 1e9
    delay_ns_full = np.arange(n_delay, dtype=np.float64) / BW_HZ * 1e9
    gated_idx = np.flatnonzero(delay_ns_full <= gate_ns_max)
    delay_ns_gated = delay_ns_full[gated_idx]
    print(f"n_total frames={n_total}, gated delay bins={gated_idx.size} (0..{delay_ns_gated[-1]:.0f} ns)")

    starts = np.arange(0, max(1, n_total - WINDOW_FRAMES + 1), STEP_FRAMES, dtype=int)

    raw_series = compute_window_series(cir, gps, gated_idx, delay_ns_gated, starts, denoise=False)
    denoised_series = compute_window_series(cir, gps, gated_idx, delay_ns_gated, starts, denoise=True)
    print(f"n_windows={len(raw_series['distance_m'])}, distance range=[{raw_series['distance_m'].min():.1f}, {raw_series['distance_m'].max():.1f}] m")

    sage_json_path = ROOT / "data" / "ui_samples" / f"{Path(BIN_NAME).stem}_b2b_adaptive_sage.json"
    print(f"Loading existing SAGE export: {sage_json_path}")
    sage_series = compute_window_series_sage_from_export(sage_json_path)
    print(f"SAGE: n_windows={len(sage_series['distance_m'])}")

    raw_summary = make_plots(raw_series, delay_ns_gated, OUT_DIR / "raw", "RAW: full 2000m gate, no denoise")
    denoised_summary = make_plots(
        denoised_series, delay_ns_gated, OUT_DIR / "denoised",
        f"DENOISED: noise floor removed, margin={NOISE_MARGIN_DB:.0f}dB",
    )
    sage_summary = make_plots(
        sage_series, delay_ns_gated, OUT_DIR / "sage",
        "SAGE: adaptive-SAGE MPC power sum (non-coherent)",
    )

    print("\n=== summary: raw vs denoised vs sage ===")
    for key in ("ple", "shadow_sigma_db", "k_mean_db", "rms_ds_mean_ns"):
        print(f"{key:>16}: raw={raw_summary[key]:8.3f}   denoised={denoised_summary[key]:8.3f}   sage={sage_summary[key]:8.3f}")
    print(f"\nFigures written to {OUT_DIR}/{{raw,denoised,sage}}")


if __name__ == "__main__":
    main()
