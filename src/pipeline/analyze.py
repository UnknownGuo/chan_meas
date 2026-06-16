"""Single-bin analyze pipeline for the web UI's compute-or-cache flow.

See docs/specs/2026-06-16-channel-analysis-ui-implementation-spec.md (§4.3).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.io.bin_read import _load_frames, _parse_iq, _sliding_correlate
from src.ui_dataset import build_measurement_dataset


def analyze_one(
    rx_bin_path: Path,
    *,
    carrier_hz: float,
    out_dir: Path,
    cal_bin_path: Path | None = None,
    tx_mode: str = "static",
    tx_lat: float | None = None,
    tx_lon: float | None = None,
    tx_alt: float | None = None,
) -> Path:
    """Run the SAGE pipeline on one Rx .bin and write the UI dataset JSON.

    carrier_hz is recorded in meta only — the adaptive SAGE Doppler estimate
    is derived purely from frame_rate_hz (slow-time FFT) and does not need it
    (see implementation spec §4.3 clarification, 2026-06-16).
    """
    if carrier_hz is None or carrier_hz <= 0:
        raise ValueError("carrier_hz must be a positive number")

    b2b_cir = None
    if cal_bin_path is not None:
        b2b_cir = _sliding_correlate(_parse_iq(_load_frames(cal_bin_path)))

    dataset: dict[str, Any] = build_measurement_dataset(
        rx_bin_path,
        max_frames=None,
        max_delay_bins=300,
        relative_power=False,
        include_sage=True,
        b2b_cir=b2b_cir,
    )
    dataset.setdefault("meta", {})["carrierHz"] = carrier_hz
    dataset["meta"]["txMode"] = tx_mode
    if tx_mode == "static" and tx_lat is not None and tx_lon is not None:
        dataset["txGps"] = {
            "lat": tx_lat,
            "lon": tx_lon,
            "alt": tx_alt if tx_alt is not None else 0.0,
            "source": "user_input",
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{rx_bin_path.stem}_b2b_adaptive_sage.json"
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
