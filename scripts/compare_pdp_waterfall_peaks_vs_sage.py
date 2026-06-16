from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = Path("/mnt/win_data/data_mea/0121campus_test/sage_quicklook_420mhz_lastgroup_alltime_50frames")
PDP_CSV = BASE / "pdp_waterfall_visible_peaks_per_frame_top6.csv"
SAGE_CSV = BASE / "alltime_sage_paths_50frame_windows.csv"
OUT = BASE / "compare_pdp_waterfall_peaks_vs_sage"
OUT.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def arr(rows, key, dtype=float):
    return np.array([dtype(r[key]) for r in rows])


def main() -> int:
    pdp_rows = read_csv(PDP_CSV)
    sage_rows = read_csv(SAGE_CSV)
    # Keep all PDP visible peaks but use alpha/small points.
    t_p = arr(pdp_rows, "timeSec")
    d_p = arr(pdp_rows, "delayNs")
    r_p = arr(pdp_rows, "relativeDbToFramePeak")
    abs_p = arr(pdp_rows, "absolutePowerDb")
    # stronger visible peaks for clearer overlay
    strong_mask = r_p >= -12

    t_s = arr(sage_rows, "timeSec")
    d_s = arr(sage_rows, "delayNs")
    fd_s = arr(sage_rows, "dopplerHz")
    p_s = arr(sage_rows, "powerDb")
    p_s_rel = p_s - np.nanmax(p_s) if p_s.size else p_s

    # 1) PDP visible peaks only.
    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    sc = ax.scatter(t_p, d_p, c=r_p, s=5, cmap="turbo", vmin=-18, vmax=0, alpha=0.45, edgecolors="none")
    ax.set_title("PDP Waterfall Visible Peaks (per-frame top local peaks)", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(0, 6000)
    ax.grid(alpha=0.22, linewidth=0.5)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Peak power relative to each frame peak (dB)")
    fig.tight_layout()
    out1 = OUT / "01_pdp_waterfall_visible_peaks_delay_power.png"
    fig.savefig(out1, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 2) Overlay: PDP visible peaks grey/background + SAGE paths colored.
    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    ax.scatter(t_p, d_p, c="0.72", s=3, alpha=0.22, edgecolors="none", label="PDP visible peaks (top 6/frame, >= -18 dB)")
    ax.scatter(t_p[strong_mask], d_p[strong_mask], c="0.40", s=4, alpha=0.28, edgecolors="none", label="PDP stronger peaks (>= -12 dB)")
    sc = ax.scatter(t_s, d_s, c=p_s_rel, s=np.clip(16 + 3.2 * (p_s_rel + 35), 12, 80), cmap="turbo", vmin=-35, vmax=0, alpha=0.92, edgecolors="black", linewidths=0.18, label="Adaptive SAGE paths, 50-frame windows")
    ax.set_title("PDP Waterfall Peaks vs Adaptive SAGE Paths: Delay-Power", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(0, 6000)
    ax.grid(alpha=0.22, linewidth=0.5)
    ax.legend(loc="upper right", fontsize=8)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("SAGE path power (dB relative to strongest SAGE path)")
    fig.tight_layout()
    out2 = OUT / "02_overlay_pdp_peaks_vs_sage_delay_power.png"
    fig.savefig(out2, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 3) Zoom dominant delay region overlay.
    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    zoom = (d_p >= 1200) & (d_p <= 3200)
    zoom_s = (d_s >= 1200) & (d_s <= 3200)
    ax.scatter(t_p[zoom], d_p[zoom], c="0.70", s=4, alpha=0.26, edgecolors="none", label="PDP visible peaks")
    ax.scatter(t_p[zoom & strong_mask], d_p[zoom & strong_mask], c="0.30", s=5, alpha=0.34, edgecolors="none", label="PDP stronger peaks")
    sc = ax.scatter(t_s[zoom_s], d_s[zoom_s], c=p_s_rel[zoom_s], s=np.clip(18 + 3.5 * (p_s_rel[zoom_s] + 35), 14, 85), cmap="turbo", vmin=-35, vmax=0, alpha=0.94, edgecolors="black", linewidths=0.18, label="SAGE paths")
    ax.set_title("Zoom: Dominant Delay Region, PDP Peaks vs SAGE Paths", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Delay (ns)")
    ax.set_ylim(1200, 3200)
    ax.grid(alpha=0.22, linewidth=0.5)
    ax.legend(loc="upper right", fontsize=8)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("SAGE path power (dB relative)")
    fig.tight_layout()
    out3 = OUT / "03_zoom_overlay_pdp_peaks_vs_sage_delay_power.png"
    fig.savefig(out3, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 4) Doppler overlay: SAGE doppler with PDP path count background diagnostics.
    fig, ax = plt.subplots(figsize=(12.5, 6.0))
    sc = ax.scatter(t_s, fd_s, c=p_s_rel, s=np.clip(16 + 3.2 * (p_s_rel + 35), 12, 80), cmap="turbo", vmin=-35, vmax=0, alpha=0.9, edgecolors="black", linewidths=0.18)
    ax.axhline(0, color="black", linewidth=0.7, alpha=0.45)
    ax.set_title("Adaptive SAGE Paths: Doppler-Power (50-frame windows)", fontsize=14, weight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Doppler (Hz)")
    ax.set_ylim(-50, 50)
    ax.grid(alpha=0.22, linewidth=0.5)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("SAGE path power (dB relative)")
    fig.tight_layout()
    out4 = OUT / "04_sage_doppler_power_for_overlay_set.png"
    fig.savefig(out4, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # Counts per time bin: how dense the PDP visible peaks are vs SAGE path count.
    # Use same 50-frame / 0.5 s window centers as SAGE for comparability.
    centers = np.unique(t_s)
    if centers.size:
        half = 0.25
        pdp_count = np.array([np.count_nonzero((t_p >= c - half) & (t_p < c + half)) for c in centers])
        sage_count = np.array([np.count_nonzero(np.isclose(t_s, c)) for c in centers])
        fig, ax1 = plt.subplots(figsize=(12.5, 5.2))
        ax1.plot(centers, pdp_count, color="0.35", lw=0.8, label="PDP visible peaks / 0.5 s")
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("PDP visible peak count", color="0.25")
        ax1.tick_params(axis="y", labelcolor="0.25")
        ax1.grid(alpha=0.22, linewidth=0.5)
        ax2 = ax1.twinx()
        ax2.plot(centers, sage_count, color="#d62728", lw=1.0, label="SAGE accepted paths / 0.5 s")
        ax2.set_ylabel("SAGE accepted path count", color="#d62728")
        ax2.tick_params(axis="y", labelcolor="#d62728")
        fig.suptitle("PDP-visible peak density vs SAGE accepted path count", fontsize=14, weight="bold")
        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines + lines2, labels + labels2, loc="upper left", fontsize=8)
        fig.tight_layout()
        out5 = OUT / "05_pdp_peak_count_vs_sage_path_count.png"
        fig.savefig(out5, dpi=180, bbox_inches="tight")
        plt.close(fig)
    else:
        out5 = None

    summary = {
        "pdpRecords": int(len(pdp_rows)),
        "sageRecords": int(len(sage_rows)),
        "outputs": [str(out1), str(out2), str(out3), str(out4), None if out5 is None else str(out5)],
    }
    (OUT / "summary.json").write_text(__import__("json").dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(__import__("json").dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
