"""Lightweight diagnostic: CIR + adaptive SAGE coverage stats only, no full UI
dataset (skips frame payloads / doppler waterfalls / etc.) so it's fast."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.b2b_frequency import regularized_frequency_calibrate
from src.calibration.constants import ZJK_B2B_ATTENUATION_DB, ZJK_B2B_REGULARIZATION
from src.paths import ZJK_RAW_DIR
from src.io.bin_read import _parse_iq, _sliding_correlate, FRAME_LEN
from src.ui_dataset import compute_adaptive_sage_tracks, BW_HZ, FRAME_RATE_HZ

FILES = sorted(p for p in ZJK_RAW_DIR.glob("*.bin") if p.stem != "cali_data")
B2B_PATH = ZJK_RAW_DIR / "calibration" / "b2b_cir.npy"


def main() -> None:
    b2b = np.load(B2B_PATH, mmap_mode="r")
    b2b_cir = np.array(b2b, copy=False)
    b2b_ref = np.asarray(b2b_cir[0], dtype=np.complex128)

    results = []
    for path in FILES:
        n_total = path.stat().st_size // FRAME_LEN
        raw = np.memmap(path, dtype=np.uint8, mode="r")
        frames = np.array(raw[: n_total * FRAME_LEN].reshape(n_total, FRAME_LEN), copy=True)
        iq = _parse_iq(frames)
        del frames
        cir = _sliding_correlate(iq)
        del iq
        cir = regularized_frequency_calibrate(
            cir, b2b_ref, regularization=ZJK_B2B_REGULARIZATION, axis=1, attenuation_db=ZJK_B2B_ATTENUATION_DB
        )
        sage = compute_adaptive_sage_tracks(
            cir,
            bandwidth_hz=BW_HZ,
            frame_rate_hz=FRAME_RATE_HZ,
            window_size_frames=20,
            step_frames=100,
            delay_gate_distance_m=2000.0,
            max_delay_bins=300,
            coverage_target=0.97,
            min_coverage_gain=0.001,
            max_paths_hard=30,
            enable_weak_nonprominent_prune=True,
        )
        cs = sage.get("coverageSummary")
        results.append((path.stem, cs))
        print(f"{path.name}: {cs}", flush=True)
        del cir

    print("\n=== summary ===")
    results.sort(key=lambda r: (r[1] is None, r[1]["meanCoverageRatio"] if r[1] else 0))
    print(f"{'file':<45}{'mean':>8}{'min':>8}{'p10':>8}")
    for name, cs in results:
        if cs is None:
            print(f"{name:<45}{'N/A':>8}")
        else:
            print(f"{name:<45}{cs['meanCoverageRatio']:>8.3f}{cs['minCoverageRatio']:>8.3f}{cs['p10CoverageRatio']:>8.3f}")


if __name__ == "__main__":
    main()
