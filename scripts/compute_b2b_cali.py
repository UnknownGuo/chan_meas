"""
一次性脚本：从新 B2B .bin 文件计算校准向量，保存到 data/calibration/b2b/
用法：python3 scripts/compute_b2b_cali.py
"""
import sys
from pathlib import Path
import numpy as np
import scipy.io

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.io.bin_reader import compute_cali_from_b2b, diagnose_b2b_delay, _load_frames, _parse_iq, _sliding_correlate
from src.paths import CALIB_B2B_DIR

CALI_ROOT = Path("/mnt/win_data/data_mea/data_save/Cali_data/20260402_freq_bais_cali_mea")

BANDS = {
    "1400M": {
        "fc_hz": 1.4e9,
        "bin":   "Calib_V1_20260402_B2B_Black01_081cable_1400M_40dB.bin",
        "out":   "Calib_V1_20260402_B2B_Black01_081cable_1400M_40dB.mat",
    },
    "3600M": {
        "fc_hz": 3.6e9,
        "bin":   "Calib_V1_20260402_B2B_Black01_081cable_3600M_40dB.bin",
        "out":   "Calib_V1_20260402_B2B_Black01_081cable_3600M_40dB.mat",
    },
    "4900M": {
        "fc_hz": 4.9e9,
        "bin":   "Calib_V1_20260402_B2B_Black01_081cable_4900M_40dB.bin",
        "out":   "Calib_V1_20260402_B2B_Black01_081cable_4900M_40dB.mat",
    },
}

CALIB_B2B_DIR.mkdir(parents=True, exist_ok=True)

for band, info in BANDS.items():
    bin_path = CALI_ROOT / info["bin"]
    out_path = CALIB_B2B_DIR / info["out"]

    print(f"\n── {band} ({info['fc_hz']/1e9:.1f} GHz) ──")
    print(f"   输入: {bin_path}")

    # 计算校准向量（前100帧幅度均值 + 第0帧相位）
    cali_vec = compute_cali_from_b2b(bin_path, n_avg=100, mag_avg=True)

    # 诊断信息
    frames = _load_frames(bin_path)
    iq     = _parse_iq(frames)
    cir    = _sliding_correlate(iq)
    diag   = diagnose_b2b_delay(cir)
    del frames, iq, cir

    print(f"   帧数      : {diag.get('note', '')}")
    print(f"   主峰 bin  : {diag['peak_bin']}")
    print(f"   硬件时延  : {diag['peak_delay_ns']:.0f} ns")
    print(f"   主峰功率  : {diag['peak_power_db']:.1f} dB above noise")

    # 保存
    scipy.io.savemat(str(out_path), {
        "cali_vec":     cali_vec,
        "fc_hz":        info["fc_hz"],
        "band":         band,
        "peak_bin":     diag["peak_bin"],
        "peak_delay_ns": diag["peak_delay_ns"],
    })
    print(f"   ✅ 保存至: {out_path}")

print("\n全部完成。")
