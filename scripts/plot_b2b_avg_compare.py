"""
对比 B2B CIR 三种平均方式：第1帧 / 前100帧幅度均值 / 全帧幅度均值
输出: scripts/b2b_avg_compare.png
"""
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.io.bin_reader import _load_frames, _parse_iq, _sliding_correlate

CALI_ROOT = Path("/mnt/win_data/data_mea/data_save/Cali_data/20260402_freq_bais_cali_mea")
BANDS = {
    "1400M (1.4 GHz)": ("Calib_V1_20260402_B2B_Black01_081cable_1400M_40dB.bin", 1.4e9),
    "3600M (3.6 GHz)": ("Calib_V1_20260402_B2B_Black01_081cable_3600M_40dB.bin", 3.6e9),
    "4900M (4.9 GHz)": ("Calib_V1_20260402_B2B_Black01_081cable_4900M_40dB.bin", 4.9e9),
}

fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
delay_ns = np.arange(1024) / 50e6 * 1e9  # BW=50MHz → 20ns/bin

for ax, (label, (fname, fc_hz)) in zip(axes, BANDS.items()):
    bin_path = CALI_ROOT / fname
    print(f"Loading {label} ...")

    frames = _load_frames(bin_path)
    iq     = _parse_iq(frames)
    cir    = _sliding_correlate(iq)   # (N, 1024) complex64
    N      = cir.shape[0]
    print(f"  总帧数: {N}")

    # 三种平均
    mag_1     = np.abs(cir[0])                        # 第1帧幅度
    mag_100   = np.abs(cir[:100]).mean(axis=0)        # 前100帧幅度均值
    mag_all   = np.abs(cir).mean(axis=0)              # 全帧幅度均值

    to_db = lambda x: 20 * np.log10(x + 1e-12)

    ax.plot(delay_ns, to_db(mag_1),   lw=0.8, alpha=0.7, label="第1帧")
    ax.plot(delay_ns, to_db(mag_100), lw=1.2, alpha=0.9, label=f"前100帧幅度均值")
    ax.plot(delay_ns, to_db(mag_all), lw=1.5,             label=f"全{N}帧幅度均值")

    ax.set_xlim([0, 3000])
    ax.set_ylabel("幅度 (dB)")
    ax.set_title(label)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel("时延 (ns)")
fig.suptitle("B2B CIR — 不同帧数幅度平均对比", fontsize=13, y=1.01)
plt.tight_layout()

out_path = Path(__file__).parent / "b2b_avg_compare.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"\n图已保存: {out_path}")
