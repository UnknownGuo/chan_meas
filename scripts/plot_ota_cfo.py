"""
Plot per-frame CFO (relative to frame 0) for three OTA bands.

Method: cross-frame phase difference
  R_k   = sum_n( CIR_peak[k] * conj(CIR_peak[0]) )
  phi_k = unwrap( angle(R_k) )
  CFO_k = phi_k / (2π × k × T_frame)   [Hz]

CIR peak bin determined from the incoherent-averaged PDP of each band.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── project root → src on path ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("bin_reader", ROOT / "src" / "io" / "bin_reader.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_load_frames = _mod._load_frames
_parse_iq = _mod._parse_iq
_sliding_correlate = _mod._sliding_correlate

# ── constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("/mnt/win_data/data_mea/data_save/Cali_data/20260402_freq_bais_cali_mea")
T_FRAME_S = 10e-3   # 10 ms frame interval

BANDS = {
    "1.4 GHz": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_1400M.bin",
    "3.6 GHz": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_3600M.bin",
    "4.9 GHz": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_4900M.bin",
}

COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]


def load_cir(bin_path: Path) -> np.ndarray:
    """Load CIR (n_frames, U) from a single OTA .bin file."""
    print(f"  Loading {bin_path.name} ...", flush=True)
    frames = _load_frames(bin_path)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq
    return cir


def cfo_vs_time(cir: np.ndarray, smooth_win: int = 200):
    """
    Compute per-frame CFO relative to frame 0, using adjacent-frame phase diff.

    Adjacent-frame method:
        delta_phi[k] = angle( peak[k] * conj(peak[k-1]) )
        cfo_inst[k]  = delta_phi[k] / (2π × T_frame)   [Hz]

    Accumulated phase (relative to frame 0):
        phi_acc[k] = cumsum(delta_phi)

    Valid range: |CFO| < 1/(2 × T_frame) = 50 Hz.
    If true CFO > 50 Hz the phase wraps each frame and this method fails.

    Returns
    -------
    time_s    : (n_frames,) float64 — time axis [s]
    cfo_inst  : (n_frames,) float64 — instantaneous CFO per frame [Hz]
    cfo_smooth: (n_frames,) float64 — running-median smoothed CFO [Hz]
    phi_acc   : (n_frames,) float64 — accumulated phase drift [rad]
    """
    # Find dominant peak bin from incoherent-averaged PDP
    pdp_avg = np.mean(np.abs(cir) ** 2, axis=0)
    peak_bin = int(np.argmax(pdp_avg))
    print(f"    peak bin = {peak_bin}", flush=True)

    peak_vals = cir[:, peak_bin].astype(np.complex128)   # (n_frames,)

    # Adjacent-frame phase difference
    delta_phi = np.angle(peak_vals[1:] * np.conj(peak_vals[:-1]))  # (n_frames-1,)

    # Instantaneous CFO
    cfo_inst_core = delta_phi / (2.0 * np.pi * T_FRAME_S)    # (n_frames-1,)

    # Prepend frame-0 = 0
    cfo_inst = np.concatenate([[0.0], cfo_inst_core])         # (n_frames,)

    # Running-median smoothing
    from scipy.signal import medfilt
    k_med = smooth_win | 1                                    # ensure odd
    cfo_smooth = medfilt(cfo_inst, kernel_size=k_med)

    # Accumulated phase (relative to frame 0)
    phi_acc = np.concatenate([[0.0], np.cumsum(delta_phi)])   # (n_frames,)

    time_s = np.arange(len(cfo_inst)) * T_FRAME_S
    return time_s, cfo_inst, cfo_smooth, phi_acc


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=False)
    ax_cfo, ax_phi = axes

    for (band_label, bin_path), color in zip(BANDS.items(), COLORS):
        print(f"\nBand: {band_label}")
        cir = load_cir(bin_path)
        print(f"    n_frames = {cir.shape[0]}")
        time_s, cfo_inst, cfo_smooth, phi_acc = cfo_vs_time(cir)

        # Raw (thin, alpha) + smoothed (thick)
        ax_cfo.plot(time_s, cfo_inst, lw=0.4, color=color, alpha=0.25)
        ax_cfo.plot(time_s, cfo_smooth, lw=1.5, color=color, label=band_label)
        ax_phi.plot(time_s, phi_acc, lw=0.9, color=color, label=band_label)

    # ── CFO panel ─────────────────────────────────────────────────────────────
    ax_cfo.set_ylabel("CFO (Hz)", fontsize=12)
    ax_cfo.set_title(
        "Instantaneous CFO vs. Time  (Static OTA, 2026-04-02, adjacent-frame method)",
        fontsize=13,
    )
    ax_cfo.legend(fontsize=11)
    ax_cfo.grid(True, linestyle="--", alpha=0.5)
    ax_cfo.set_xlabel("Time (s)", fontsize=12)
    ax_cfo.axhline(0, color="k", lw=0.6, ls=":")
    # clip y-axis to ±50 Hz (valid range of adjacent-frame method)
    ax_cfo.set_ylim(-50, 50)
    _set_tick_font(ax_cfo)

    # ── Phase drift panel ─────────────────────────────────────────────────────
    ax_phi.set_ylabel("Phase drift rel. frame 0 (rad)", fontsize=12)
    ax_phi.set_title(
        "Accumulated Phase Drift Relative to Frame 0",
        fontsize=13,
    )
    ax_phi.legend(fontsize=11)
    ax_phi.grid(True, linestyle="--", alpha=0.5)
    ax_phi.set_xlabel("Time (s)", fontsize=12)
    _set_tick_font(ax_phi)

    fig.tight_layout(pad=2.0)
    out_path = Path(__file__).parent / "ota_cfo_20260402.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nSaved → {out_path}")


def _set_tick_font(ax):
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontname("Times New Roman")
        label.set_fontsize(10)


if __name__ == "__main__":
    main()
