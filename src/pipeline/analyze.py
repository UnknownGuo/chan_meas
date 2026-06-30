"""Single-bin analyze pipeline for the web UI's compute-or-cache flow.

See docs/specs/2026-06-16-channel-analysis-ui-implementation-spec.md (§4.3).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.calibration.constants import B2B_ATTENUATION_DB, B2B_REGULARIZATION
from src.io.bin_read import _load_frames, _parse_iq, _sliding_correlate
from src.ui_dataset import build_measurement_dataset, TxGps


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
    include_sage: bool = False,
    include_delay_music: bool = False,
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

    # 用户填了 TX 经纬度才有 TX：传入后逐帧距离才会计算（模块 B 路损需要它）。
    tx_obj = None
    if tx_mode == "static" and tx_lat is not None and tx_lon is not None:
        tx_obj = TxGps(
            lat=float(tx_lat),
            lon=float(tx_lon),
            alt=float(tx_alt) if tx_alt is not None else 0.0,
            source="user_input",
        )

    dataset: dict[str, Any] = build_measurement_dataset(
        rx_bin_path,
        tx_gps=tx_obj,
        max_frames=None,
        max_delay_bins=300,
        relative_power=False,
        include_sage=include_sage,
        include_delay_music=include_delay_music,
        b2b_cir=b2b_cir,
        b2b_attenuation_db=B2B_ATTENUATION_DB,
        b2b_regularization=B2B_REGULARIZATION,
    )
    dataset.setdefault("meta", {})["carrierHz"] = carrier_hz
    dataset["meta"]["txMode"] = tx_mode

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{rx_bin_path.stem}_b2b_adaptive_sage.json"
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
