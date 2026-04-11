"""
Compare per-frame CFO between static OTA and B2B calibration data.

Layout: 3 columns (one per band) × 2 rows
  Row 0: Instantaneous CFO (smoothed, adjacent-frame method)
  Row 1: Accumulated phase drift relative to frame 0

Method: adjacent-frame cross-correlation on CIR peak
  delta_phi[k] = angle( peak[k] * conj(peak[k-1]) )
  CFO_inst[k]  = delta_phi[k] / (2π × T_frame)
  phi_acc[k]   = cumsum(delta_phi)

Valid range: |CFO| < 1/(2 T_frame) = 50 Hz.
"""

from __future__ import annotations

import importlib.util as _ilu
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import medfilt

# ── load bin_reader internals ─────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
_spec = _ilu.spec_from_file_location("bin_reader", ROOT / "src" / "io" / "bin_reader.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_load_frames     = _mod._load_frames
_parse_iq        = _mod._parse_iq
_sliding_correlate = _mod._sliding_correlate

# ── constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("/mnt/win_data/data_mea/data_save/Cali_data/20260402_freq_bais_cali_mea")
T_FRAME_S  = 10e-3
SMOOTH_WIN = 201   # median-filter kernel (odd)

BANDS = {
    "1.4 GHz": {
        "ota": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_1400M.bin",
        "b2b": DATA_DIR / "Calib_V1_20260402_B2B_Black01_081cable_1400M_40dB.bin",
    },
    "3.6 GHz": {
        "ota": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_3600M.bin",
        "b2b": DATA_DIR / "Calib_V1_20260402_B2B_Black01_081cable_3600M_40dB.bin",
    },
    "4.9 GHz": {
        "ota": DATA_DIR / "Calib_V1_20260402_OTA_Black01_081cable_4900M.bin",
        "b2b": DATA_DIR / "Calib_V1_20260402_B2B_Black01_081cable_4900M_40dB.bin",
    },
}

COLOR_OTA = "#1f77b4"
COLOR_B2B = "#d62728"


# ── helpers ───────────────────────────────────────────────────────────────────

def load_cir(bin_path: Path) -> np.ndarray:
    print(f"  {bin_path.name} ...", flush=True)
    frames = _load_frames(bin_path)
    iq     = _parse_iq(frames);  del frames
    cir    = _sliding_correlate(iq);  del iq
    return cir


def cfo_analysis(cir: np.ndarray):
    """Return (time_s, cfo_inst, cfo_smooth, phi_acc)."""
    pdp_avg  = np.mean(np.abs(cir) ** 2, axis=0)
    peak_bin = int(np.argmax(pdp_avg))
    print(f"    peak_bin={peak_bin}, n_frames={cir.shape[0]}", flush=True)

    peak = cir[:, peak_bin].astype(np.complex128)
    delta_phi = np.angle(peak[1:] * np.conj(peak[:-1]))   # (N-1,)
    cfo_inst  = np.concatenate([[0.0], delta_phi / (2.0 * np.pi * T_FRAME_S)])
    cfo_smooth = medfilt(cfo_inst, kernel_size=SMOOTH_WIN)
    phi_acc   = np.concatenate([[0.0], np.cumsum(delta_phi)])
    time_s    = np.arange(len(cfo_inst)) * T_FRAME_S
    return time_s, cfo_inst, cfo_smooth, phi_acc


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    n_bands = len(BANDS)
    fig, axes = plt.subplots(
        2, n_bands, figsize=(5 * n_bands, 9), sharex="col"
    )
    # axes[row, col]

    for col, (band_label, paths) in enumerate(BANDS.items()):
        ax_cfo = axes[0, col]
        ax_phi = axes[1, col]

        for label, color, key in [("OTA", COLOR_OTA, "ota"),
                                   ("B2B", COLOR_B2B, "b2b")]:
            print(f"\n[{band_label}] {label}")
            cir = load_cir(paths[key])
            t, cfo_inst, cfo_smooth, phi_acc = cfo_analysis(cir)

            # ── instantaneous CFO ────────────────────────────────────────────
            ax_cfo.plot(t, cfo_inst,   lw=0.3, color=color, alpha=0.20)
            ax_cfo.plot(t, cfo_smooth, lw=1.8, color=color, label=label)

            # ── accumulated phase ────────────────────────────────────────────
            ax_phi.plot(t, phi_acc, lw=1.0, color=color, label=label)

        # ── formatting ───────────────────────────────────────────────────────
        ax_cfo.set_title(band_label, fontsize=13)
        ax_cfo.set_ylim(-50, 50)
        ax_cfo.axhline(0, color="k", lw=0.6, ls=":")
        ax_cfo.grid(True, linestyle="--", alpha=0.45)
        ax_cfo.legend(fontsize=10)
        if col == 0:
            ax_cfo.set_ylabel("CFO (Hz)", fontsize=11)
            ax_phi.set_ylabel("Phase drift rel. frame 0 (rad)", fontsize=11)

        ax_phi.grid(True, linestyle="--", alpha=0.45)
        ax_phi.legend(fontsize=10)
        ax_phi.set_xlabel("Time (s)", fontsize=11)

    fig.suptitle(
        "CFO: Static OTA vs. B2B  —  2026-04-02  (adjacent-frame method, smooth win=2 s)",
        fontsize=13, y=1.01,
    )
    fig.tight_layout(pad=2.0)

    out_path = Path(__file__).parent / "cfo_ota_vs_b2b_20260402.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
