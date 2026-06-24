#!/usr/bin/env python3
"""Extract GPS from all .bin files in zjk_mea (except cali_data.bin) → .txt."""

from pathlib import Path
import numpy as np
import sys

# Add project src to path
sys.path.insert(0, "/home/guo/桌面/project/chan_meas")
from src.io.bin_read import _load_frames, _parse_gps

DATA_DIR = Path("/mnt/win_data/data_mea/zjk_mea")
OUT_DIR = DATA_DIR  # 输出到同一目录

bin_files = sorted(DATA_DIR.glob("*.bin"))
for bin_path in bin_files:
    if bin_path.name == "cali_data.bin":
        print(f"Skip calibration: {bin_path.name}")
        continue

    txt_path = OUT_DIR / (bin_path.stem + "_gps.txt")

    frames = _load_frames(bin_path)
    gps = _parse_gps(frames)
    n = len(gps["lat"])

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("#frame_idx,lat,lon,alt,hour,minute,second\n")
        for i in range(n):
            f.write(
                f"{i},{gps['lat'][i]:.9f},{gps['lon'][i]:.9f},"
                f"{gps['alt'][i]:.1f},{gps['hour'][i]},{gps['minute'][i]},{gps['second'][i]}\n"
            )

    print(f"{bin_path.name:50s} → {txt_path.name}  ({n} frames)")

print("\nDone.")
