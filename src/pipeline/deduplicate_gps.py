#!/usr/bin/env python3
"""
将测量目录下所有 *_gps.txt 合并到单独文件夹，
并对每个文件去除重复的 GPS 记录（基于 lat/lon/alt/hour/minute/second）。
"""

from pathlib import Path
import pandas as pd

SRC_DIR = Path("raw_bins")  # 改为你的本地测量目录
OUT_DIR = SRC_DIR / "gps_txt"
OUT_DIR.mkdir(exist_ok=True)

# 要处理的 txt 文件
txt_files = sorted(SRC_DIR.glob("*_gps.txt"))

total_before = 0
total_after = 0

for txt_path in txt_files:
    df = pd.read_csv(txt_path, comment="#", header=None,
                     names=["frame_idx", "lat", "lon", "alt", "hour", "minute", "second"])
    before = len(df)
    # 基于 GPS 字段去重（保留第一个出现的）
    df_dedup = df.drop_duplicates(subset=["lat", "lon", "alt", "hour", "minute", "second"], keep="first")
    after = len(df_dedup)

    out_path = OUT_DIR / txt_path.name
    df_dedup.to_csv(out_path, index=False)

    total_before += before
    total_after += after
    dup = before - after
    print(f"{txt_path.name:55s}  原始={before:6d}  去重={after:6d}  删除={dup:6d}")

print(f"\n总计: 原始={total_before}  去重后={total_after}  删除={total_before-total_after}")
print(f"输出目录: {OUT_DIR}")
