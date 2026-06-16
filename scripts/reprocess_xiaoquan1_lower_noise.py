"""One-off: re-run the adaptive SAGE extraction for xiaoquan-1 only, with a
tighter coverage target / gain floor to suppress the weak-path noise visible
in adaptive_separate_delay_time_power.png.

Same pipeline as run_adaptive_sage_w20_step100_remaining.py, just scoped to a
single file with COVERAGE_TARGET=0.95 / MIN_COVERAGE_GAIN=0.0005 (was
0.97 / 0.001). Originals were already backed up to backup_cov97_gain001/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_adaptive_sage_w20_step100_remaining as pipeline
import numpy as np

pipeline.COVERAGE_TARGET = 0.90
pipeline.MIN_COVERAGE_GAIN = 0.005

STEMS = ["0m-0m-all-firstantenna-xiaoquan", "0m-0m-all-second-antenna-xiaoquan"]

if __name__ == "__main__":
    b2b = np.load(pipeline.B2B_PATH, mmap_mode="r")
    b2b_ref = np.array(b2b[0], dtype=np.complex128)
    for stem in STEMS:
        bin_path = pipeline.DATA_DIR / f"{stem}.bin"
        rec = pipeline.process_one_file(bin_path, b2b_ref)
        print(rec)
