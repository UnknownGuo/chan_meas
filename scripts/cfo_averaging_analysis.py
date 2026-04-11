"""CFO estimation and coherent averaging effect analysis.

Three output figures:
  Fig 1 — CFO time series (B2B calibration file)
  Fig 2 — Intra-frame IQ averaging effect: PDP vs N sequences (B2B)
  Fig 3 — Intra-frame IQ averaging effect: PDP vs N sequences (OTA)

Usage:
  python scripts/cfo_averaging_analysis.py

Data path: /mnt/win_data/data_mea/洛阳测试10ms未平均/
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Project path
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.io.bin_reader_luoyang import LuoyangBinReader
from src.calibration.cfo_estimator import (
    CFOEstimator,
    build_lfm_matched_filter,
    coherent_average,
    generate_cir_from_iq,
    calculate_cfo_statistics,
    T_FRAME,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path("/mnt/win_data/data_mea/洛阳测试10ms未平均")
B2B_FILE = DATA_DIR / "接收数据帧_20251222142759088.bin"
OTA_FILES = [
    DATA_DIR / "接收数据帧_1.bin",
    DATA_DIR / "接收数据帧_3.bin",
]

OUT_DIR = Path(__file__).parent
BW_HZ: float = 50e6          # signal bandwidth [Hz], for delay-axis scaling
N_AVG_LIST = [1, 2, 3, 5, 10, 15]

np.random.seed(42)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_cir_from_iq_sequences(
    iq_3d: np.ndarray,
    n_seqs: Optional[int] = None,
) -> np.ndarray:
    """
    Average the first *n_seqs* IQ sequences per frame, then generate CIR.

    Parameters
    ----------
    iq_3d : (n_frames, P_SEQS, U) complex64
    n_seqs : int or None
        Number of sequences to average.  None → use all.

    Returns
    -------
    np.ndarray
        CIR array of shape (n_frames, U), dtype complex64.
    """
    n_frames, p_seqs, u = iq_3d.shape
    if n_seqs is None:
        n_seqs = p_seqs

    mf = build_lfm_matched_filter(u)

    # Coherent average of first n_seqs sequences per frame → (n_frames, U)
    iq_avg = coherent_average(iq_3d[:, :n_seqs, :], axis=1)

    cir = np.empty((n_frames, u), dtype=np.complex64)
    for k in range(n_frames):
        cir[k] = generate_cir_from_iq(iq_avg[k], mf)
    return cir


def _delay_axis_ns(u: int) -> np.ndarray:
    """Return delay axis in nanoseconds (resolution = 1/BW_HZ)."""
    return np.arange(u) * (1e9 / BW_HZ)


def _dynamic_range_db(
    pdp: np.ndarray,
    noise_percentile: float = 10.0,
) -> tuple[float, float, float]:
    """Return (peak_db, noise_db, dynamic_range_db)."""
    peak_db = float(pdp.max())
    noise_db = float(np.percentile(pdp, noise_percentile))
    return peak_db, noise_db, peak_db - noise_db


# ---------------------------------------------------------------------------
# Figure 1 — CFO time series
# ---------------------------------------------------------------------------


def plot_cfo_timeseries(
    cir: np.ndarray,
    out_path: Path,
) -> None:
    """
    Two-panel CFO time-series figure.

    Top panel  : adjacent-frame CFO (Hz) vs frame index.
    Bottom panel: unwrapped cumulative phase (rad) vs frame index.

    Parameters
    ----------
    cir : (n_frames, U) complex64 — full-average CIR per frame.
    """
    estimator = CFOEstimator(cir, frame_period_s=T_FRAME)
    cfo_adj, _dphi = estimator.estimate_by_adjacent_frames()
    phi_unwrap, _cfo_cum, cfo_slope = estimator.estimate_by_cumulative_phase()
    stats = calculate_cfo_statistics(cfo_adj)

    n_frames = len(cir)
    frame_idx_adj = np.arange(1, n_frames)
    frame_idx_all = np.arange(n_frames)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=False)
    fig.suptitle(
        f"CFO Time Series  (B2B calibration)\n"
        f"Adjacent-frame: mean={stats['mean_hz']:.2f} Hz, "
        f"σ={stats['std_hz']:.2f} Hz  |  "
        f"Linear-fit CFO={cfo_slope:.2f} Hz",
        fontsize=11,
    )

    ax0 = axes[0]
    ax0.plot(frame_idx_adj, cfo_adj, lw=0.8, color="steelblue", alpha=0.7,
             label="Adjacent-frame CFO")
    ax0.axhline(stats["mean_hz"], color="red", lw=1.2, ls="--",
                label=f"Mean {stats['mean_hz']:.2f} Hz")
    ax0.axhline( 50, color="gray", lw=0.8, ls=":", label="±50 Hz observable limit")
    ax0.axhline(-50, color="gray", lw=0.8, ls=":")
    ax0.set_ylabel("CFO (Hz)")
    ax0.set_xlabel("Frame index")
    ax0.legend(fontsize=8)
    ax0.grid(True, alpha=0.3)

    ax1 = axes[1]
    ax1.plot(frame_idx_all, phi_unwrap, lw=0.8, color="darkorange",
             label="Accumulated phase (unwrapped)")
    t_sec = frame_idx_all * T_FRAME
    phi_fit = 2.0 * np.pi * cfo_slope * t_sec
    ax1.plot(frame_idx_all, phi_fit, "r--", lw=1.2,
             label=f"Linear fit ({cfo_slope:.2f} Hz)")
    ax1.set_ylabel("Accumulated phase (rad)")
    ax1.set_xlabel("Frame index")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[Fig 1] saved: {out_path}")
    print(f"        peak_bin={estimator.peak_bin}, "
          f"CFO mean={stats['mean_hz']:.2f} Hz, σ={stats['std_hz']:.2f} Hz")
    print(f"        linear-fit CFO={cfo_slope:.2f} Hz")


# ---------------------------------------------------------------------------
# Figure 2 / 3 — intra-frame averaging effect
# ---------------------------------------------------------------------------


def plot_intra_frame_averaging(
    iq_3d: np.ndarray,
    title: str,
    out_path: Path,
) -> None:
    """
    2×3 subplot grid: PDP for N=1,2,3,5,10,15 intra-frame averaged sequences.

    For each N:
      1. Coherently average the first N IQ sequences per frame.
      2. Generate per-frame CIR via matched filtering.
      3. Amplitude-average |CIR| across all frames for a stable PDP.
      4. Convert to dB and annotate dynamic range.

    Parameters
    ----------
    iq_3d : (n_frames, P_SEQS, U) complex64 — raw per-sequence IQ.
    title  : Figure suptitle string.
    out_path : Destination PNG path.
    """
    n_frames, p_seqs, u = iq_3d.shape
    delay_ns = _delay_axis_ns(u)

    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharey=True, sharex=True)
    fig.suptitle(title, fontsize=11)

    for ax, n in zip(axes.flatten(), N_AVG_LIST):
        if n > p_seqs:
            ax.set_title(f"N={n}  (only {p_seqs} seqs available)")
            ax.grid(True, alpha=0.3)
            continue

        cir = _build_cir_from_iq_sequences(iq_3d, n_seqs=n)

        # Amplitude-average across frames → stable PDP
        pdp_amp = np.abs(cir).mean(axis=0)          # (U,)
        pdp = 20.0 * np.log10(pdp_amp + 1e-12)

        peak_db, noise_db, dr = _dynamic_range_db(pdp)

        ax.plot(delay_ns, pdp, lw=0.9, color="steelblue")
        ax.set_title(f"N={n} seq  DR={dr:.1f} dB", fontsize=10)
        ax.set_ylim(bottom=peak_db - 80)
        ax.grid(True, alpha=0.3)

        # Double-headed arrow annotating dynamic range
        arrow_x = delay_ns[int(u * 0.55)]
        ax.annotate(
            "",
            xy=(arrow_x, noise_db),
            xytext=(arrow_x, peak_db),
            arrowprops=dict(arrowstyle="<->", color="red", lw=1.5),
        )
        ax.text(
            arrow_x + delay_ns[3],
            (peak_db + noise_db) / 2,
            f"{dr:.1f} dB",
            color="red", fontsize=8, va="center",
        )

    for ax in axes[1]:
        ax.set_xlabel("Delay (ns)")
    for ax in axes[:, 0]:
        ax.set_ylabel("PDP (dB)")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[Fig] saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    reader = LuoyangBinReader()

    # -- Fig 1: CFO time series (full 15-seq average per frame) -----------
    print(f"\nLoading B2B file: {B2B_FILE}")
    if not B2B_FILE.exists():
        print(f"  [ERROR] file not found: {B2B_FILE}")
        return

    iq_b2b = reader.read_iq_sequences(B2B_FILE)                 # (N, 15, 1024)
    print(f"  B2B IQ shape: {iq_b2b.shape}")

    cir_b2b_full = _build_cir_from_iq_sequences(iq_b2b)         # all 15 seqs
    print(f"  B2B CIR shape: {cir_b2b_full.shape}")
    plot_cfo_timeseries(cir_b2b_full, OUT_DIR / "fig1_cfo_timeseries.png")
    del cir_b2b_full

    # -- Fig 2: intra-frame averaging effect (B2B) -------------------------
    print("\n  Plotting intra-frame averaging effect for B2B...")
    plot_intra_frame_averaging(
        iq_b2b,
        title="Intra-frame IQ coherent averaging effect (B2B, all frames amplitude-averaged)",
        out_path=OUT_DIR / "fig2_b2b_intraframe_avg.png",
    )
    del iq_b2b

    # -- Fig 3: intra-frame averaging effect (OTA) -------------------------
    ota_file = next((f for f in OTA_FILES if f.exists()), None)
    if ota_file is None:
        print(f"\n[skip Fig 3] OTA files not found: {OTA_FILES}")
        return

    print(f"\nLoading OTA file: {ota_file}")
    iq_ota = reader.read_iq_sequences(ota_file, max_frames=500)  # (N, 15, 1024)
    print(f"  OTA IQ shape: {iq_ota.shape}")

    plot_intra_frame_averaging(
        iq_ota,
        title=f"Intra-frame IQ coherent averaging effect (OTA, {ota_file.name})",
        out_path=OUT_DIR / "fig3_ota_intraframe_avg.png",
    )

    print("\nDone. Figures saved to scripts/.")


if __name__ == "__main__":
    main()
