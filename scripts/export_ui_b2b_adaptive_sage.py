"""Export B2B-calibrated + adaptive-SAGE UI datasets for every measurement .bin
file under the zjk_mea raw data directory (excludes cali_data.bin)."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.constants import ZJK_B2B_ATTENUATION_DB, ZJK_B2B_REGULARIZATION
from src.paths import ZJK_RAW_DIR
from src.ui_dataset import build_measurement_dataset
from src.io.bin_read import FRAME_LEN

FILES = sorted(p for p in ZJK_RAW_DIR.glob("*.bin") if p.stem != "cali_data")

B2B_PATH = ZJK_RAW_DIR / "calibration" / "b2b_cir.npy"
OUT_DIR = ROOT / "data" / "ui_samples"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def main() -> None:
    b2b = np.load(B2B_PATH, mmap_mode="r")
    b2b_cir = np.array(b2b, copy=False)  # keep as array, first frame used inside
    for path in FILES:
        n_frames = path.stat().st_size // FRAME_LEN
        max_frames = None  # use all frames; CIR waterfall will be downsampled to 1 per second in UI
        print(f"Exporting {path.name} ({n_frames} frames, B2B+adaptive SAGE)", flush=True)
        dataset = build_measurement_dataset(
            path,
            max_frames=max_frames,
            max_delay_bins=300,
            relative_power=False,
            include_sage=True,
            include_joint=False,
            include_music=False,
            b2b_cir=b2b_cir,
            b2b_attenuation_db=ZJK_B2B_ATTENUATION_DB,
            b2b_regularization=ZJK_B2B_REGULARIZATION,
        )
        out_name = f"{path.stem}_b2b_adaptive_sage.json"
        out_path = OUT_DIR / out_name
        out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {out_path}", flush=True)
    print("Done.")

if __name__ == "__main__":
    main()
