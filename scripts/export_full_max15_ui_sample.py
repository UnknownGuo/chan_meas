#!/usr/bin/env python3
"""Export a compact full-run max_paths=15 dataset for the web dashboard.

This keeps the browser timeline at the joint-delay-Doppler window level instead
of exporting all raw frames.  For the current zjk last-measurement file this
produces 682 UI frames/windows and pathId values up to 15.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.io.bin_read import BW_HZ, FRAME_RATE_HZ, _load_frames, _parse_gps, _parse_iq, _sliding_correlate
from src.ui_dataset import (
    DEFAULT_ZJK_TX_GPS,
    compute_doppler_time_waterfall,
    compute_frame_payload,
    compute_frame_stats,
    compute_joint_delay_doppler_tracks,
    downsample_cir_power_db,
    load_tx_gps,
)


def _slice_gps(gps: dict[str, np.ndarray], indices: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for key, values in gps.items():
        arr = np.asarray(values)
        if arr.shape[0] >= int(indices.max()) + 1:
            out[key] = arr[indices]
    return out


def _rx_records(gps_window: dict[str, np.ndarray], frame_rate_hz: float) -> list[dict[str, Any]]:
    n = len(gps_window["lat"])
    records: list[dict[str, Any]] = []
    for i in range(n):
        records.append(
            {
                "frame": i,
                "timeSec": round(i / float(frame_rate_hz), 6),
                "lat": round(float(gps_window["lat"][i]), 9),
                "lon": round(float(gps_window["lon"][i]), 9),
                "alt": round(float(gps_window.get("alt", np.zeros(n))[i]), 3),
                "hour": int(gps_window.get("hour", np.zeros(n, dtype=np.uint8))[i]),
                "minute": int(gps_window.get("minute", np.zeros(n, dtype=np.uint8))[i]),
                "second": int(gps_window.get("second", np.zeros(n, dtype=np.uint8))[i]),
            }
        )
    return records


def build_full_window_dataset(
    rx_path: Path,
    *,
    tx_gps_path: Path | None,
    out_path: Path,
    max_delay_bins: int = 301,
    joint_delay_bins: int = 256,
    max_paths: int = 15,
    delay_gate_distance_m: float = 2000.0,
) -> dict[str, Any]:
    frames = _load_frames(rx_path, max_frames=None)
    gps = _parse_gps(frames)
    iq = _parse_iq(frames)
    del frames
    cir = _sliding_correlate(iq)
    del iq

    tx_gps = load_tx_gps(tx_gps_path) if tx_gps_path else DEFAULT_ZJK_TX_GPS
    window_size = int(round(FRAME_RATE_HZ))
    step = window_size
    joint = compute_joint_delay_doppler_tracks(
        cir,
        bandwidth_hz=BW_HZ,
        frame_rate_hz=FRAME_RATE_HZ,
        window_size_frames=window_size,
        step_frames=step,
        delay_gate_distance_m=delay_gate_distance_m,
        max_delay_bins=joint_delay_bins,
        n_doppler_bins=256,
        max_paths=max_paths,
    )

    centers = np.array([item["frame"] for item in joint["windowTracks"]], dtype=np.int64)
    cir_window = cir[centers]
    plot_delay_bins = min(cir_window.shape[1], int(round(6000e-9 * BW_HZ)) + 1)
    cir_window_plot = cir_window[:, :plot_delay_bins]
    gps_window = _slice_gps(gps, centers)
    stats = compute_frame_stats(cir_window, gps_window, tx_gps, bandwidth_hz=BW_HZ, frame_rate_hz=1.0)
    delay_ns, power_db = downsample_cir_power_db(cir_window_plot, bandwidth_hz=BW_HZ, max_delay_bins=max_delay_bins)
    time_sec = np.round(np.arange(len(centers), dtype=np.float64), 6).tolist()
    frame_payloads = [
        compute_frame_payload(
            cir_window_plot,
            gps_window,
            tx_gps,
            stats,
            frame_index=i,
            bandwidth_hz=BW_HZ,
            frame_rate_hz=1.0,
            max_delay_bins=max_delay_bins,
        )
        for i in range(len(centers))
    ]

    # Re-index tracks from raw center frame numbers to UI window indices so the
    # browser slider and MUSIC/SAGE scatter use the same 0..N-1 timeline.
    center_to_ui = {int(raw): int(i) for i, raw in enumerate(centers)}
    tracks: list[dict[str, Any]] = []
    window_tracks: list[dict[str, Any]] = []
    for ui_idx, window in enumerate(joint["windowTracks"]):
        window_copy = dict(window)
        window_copy["rawFrame"] = int(window["frame"])
        window_copy["frame"] = ui_idx
        window_copy["timeSec"] = float(ui_idx)
        peaks = []
        for peak in window["peaks"]:
            peak_copy = dict(peak)
            peak_copy["rawFrame"] = int(peak["frame"])
            peak_copy["frame"] = ui_idx
            peak_copy["timeSec"] = float(ui_idx)
            peaks.append(peak_copy)
            tracks.append(peak_copy)
        window_copy["peaks"] = peaks
        window_tracks.append(window_copy)
    joint["rawFrameCenters"] = centers.astype(int).tolist()
    joint["windowTracks"] = window_tracks
    joint["tracks"] = tracks

    doppler_time_waterfall = compute_doppler_time_waterfall(
        cir,
        frame_rate_hz=FRAME_RATE_HZ,
        window_size_frames=window_size,
        step_frames=step,
        max_delay_bins=300,
        n_doppler_bins=64,
        relative_to_peak=True,
    )

    doppler_time_waterfall["timeSec"] = time_sec

    tx_payload = {k: v for k, v in tx_gps.__dict__.items() if v is not None}
    dataset = {
        "meta": {
            "name": rx_path.name,
            "sourcePath": str(rx_path),
            "frameRateHz": 1.0,
            "rawFrameRateHz": float(FRAME_RATE_HZ),
            "bandwidthHz": float(BW_HZ),
            "numFrames": int(len(centers)),
            "numRawFrames": int(cir.shape[0]),
            "uiTimeline": "joint_delay_doppler_windows",
            "windowSizeFrames": int(window_size),
            "stepFrames": int(step),
            "maxPaths": int(max_paths),
            "dopplerDelayMethod": "delay_averaged_doppler_time_fft",
            "numDelayBinsOriginal": int(cir.shape[1]),
            "numDelayBinsExported": len(delay_ns),
            "delayUnit": "ns",
            "txMode": "static",
            "relativePower": False,
        },
        "txGps": tx_payload,
        "rxGps": _rx_records(gps_window, 1.0),
        "frameStats": stats,
        "framePayloads": frame_payloads,
        "cirWaterfall": {"delayNs": delay_ns, "timeSec": time_sec, "powerDb": power_db},
        "dopplerDelay": doppler_time_waterfall,
        "mpcScatter": tracks,
        "jointDelayDoppler": joint,
        "musicMpc": joint,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rx", type=Path, default=Path("/mnt/win_data/data_mea/zjk_mea/0m-0m-all-firstantenna-rotate-sunrotate.bin"))
    parser.add_argument("--tx-gps", type=Path, default=Path("/mnt/win_data/data_mea/zjk_mea/TX_GPS"))
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "ui_samples" / "zjk_last_measurement_max15_full.json")
    args = parser.parse_args()
    dataset = build_full_window_dataset(args.rx, tx_gps_path=args.tx_gps, out_path=args.out)
    path_ids = sorted({track["pathId"] for track in dataset["jointDelayDoppler"]["tracks"]})
    print(
        f"Exported {dataset['meta']['numFrames']} UI windows from {dataset['meta']['numRawFrames']} raw frames; "
        f"tracks={len(dataset['jointDelayDoppler']['tracks'])}; pathId={path_ids[:3]}..{path_ids[-3:]} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
