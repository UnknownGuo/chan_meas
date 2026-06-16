"""Export B2B-calibrated + adaptive-SAGE UI datasets for the 5 special files."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui_dataset import build_measurement_dataset
from src.io.bin_read import FRAME_LEN

FILES = [
    Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-first-antenna-daquan.bin"),
    Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-second-antenna-xiaoquan.bin"),
    Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-firstantenna-xiaoquan.bin"),
    Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-firstantenna-rotate-sunrotate.bin"),
    Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-firstanteaan-rotate.bin"),
]

B2B_PATH = Path("/mnt/win_data/data_mea/zjk_mea/calibration/b2b_cir.npy")
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
        )
        out_name = f"{path.stem}_b2b_adaptive_sage.json"
        out_path = OUT_DIR / out_name
        out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {out_path}", flush=True)
    print("Done.")

if __name__ == "__main__":
    main()
