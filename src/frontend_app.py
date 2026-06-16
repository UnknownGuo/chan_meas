"""FastAPI frontend shell for the channel-measurement offline analysis UI.

The heavy signal-processing code stays in :mod:`src.ui_dataset`.  This module is
only a thin web layer that serves the dashboard and already-exported JSON data,
so it can later be replaced/extended by real upload and processing endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
STATIC_DIR = WEB_DIR / "static"
DATASET_DIR = PROJECT_ROOT / "data" / "ui_samples"
TILE_CACHE_DIR = PROJECT_ROOT / "data" / "tile_cache" / "esri_imagery"
PREFERRED_DATASET_NAME = "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json"
LEGACY_DEFAULT_DATASET_NAME = "zjk_last_measurement_max15_full.json"


def list_dataset_files(dataset_dir: Path = DATASET_DIR) -> list[str]:
    """Return available exported UI dataset JSON file names."""
    if not dataset_dir.exists():
        return []
    return sorted(path.name for path in dataset_dir.glob("*.json") if path.is_file())


def _resolve_dataset_path(name: str, dataset_dir: Path = DATASET_DIR) -> Path:
    """Resolve a dataset name under dataset_dir and reject traversal."""
    if not name or Path(name).name != name:
        raise ValueError(f"Invalid dataset name: {name!r}")
    root = dataset_dir.resolve()
    path = (root / name).resolve()
    if root not in path.parents or path.suffix.lower() != ".json":
        raise ValueError(f"Invalid dataset path: {name!r}")
    return path


def load_dataset_file(name: str, dataset_dir: Path = DATASET_DIR) -> dict[str, Any]:
    """Load one exported frontend dataset JSON by file name.

    Older exported samples used ``musicMpc`` without ``jointDelayDoppler``.
    The dashboard consumes the newer key, so normalize the in-memory response
    without rewriting sample files.
    """
    path = _resolve_dataset_path(name, dataset_dir)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {name}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Dataset must be a JSON object: {name}")
    if "jointDelayDoppler" not in payload and "musicMpc" in payload:
        payload["jointDelayDoppler"] = payload["musicMpc"]
    return payload


def _dpsd_sidecar_path(name: str, dataset_dir: Path = DATASET_DIR) -> Path:
    dataset_path = _resolve_dataset_path(name, dataset_dir)
    return dataset_path.with_name(f"{dataset_path.stem}_dpsd.npz")


def load_dpsd_frame(name: str, frame_index: int, dataset_dir: Path = DATASET_DIR) -> dict[str, Any]:
    """Load one MATLAB-style DPSD frame from a sidecar NPZ file."""
    sidecar = _dpsd_sidecar_path(name, dataset_dir)
    if not sidecar.exists():
        raise FileNotFoundError(f"DPSD sidecar not found for dataset: {name}")
    with np.load(sidecar) as npz:
        power_db = npz["power_db"]
        idx = max(0, min(int(frame_index), int(power_db.shape[0]) - 1))
        delay_bins = npz["delay_bins"].astype(int)
        delay_ns = npz["delay_ns"].astype(float)
        doppler_hz = npz["doppler_hz"].astype(float)
        return {
            "mock": False,
            "method": "matlab_style_doppler_delay_fft",
            "frame": idx,
            "delayAxis": "delay_bin",
            "delayBins": delay_bins.tolist(),
            "delayNs": np.round(delay_ns, 3).tolist(),
            "dopplerHz": np.round(doppler_hz, 3).tolist(),
            "powerDb": np.round(power_db[idx].astype(float), 3).tolist(),
        }


def _default_dataset_name(dataset_dir: Path = DATASET_DIR) -> str:
    names = list_dataset_files(dataset_dir)
    for preferred in (PREFERRED_DATASET_NAME, LEGACY_DEFAULT_DATASET_NAME):
        if preferred in names:
            return preferred
    if names:
        return names[0]
    raise FileNotFoundError(f"No UI sample datasets found in {dataset_dir}")


def _load_or_fetch_map_tile(z: int, x: int, y: int, cache_dir: Path = TILE_CACHE_DIR) -> bytes:
    if not (0 <= int(z) <= 19 and int(x) >= 0 and int(y) >= 0):
        raise ValueError("invalid tile coordinates")
    path = cache_dir / str(int(z)) / str(int(x)) / f"{int(y)}.jpg"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{int(z)}/{int(y)}/{int(x)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 chan_meas research dashboard contact guomingqi99@gmail.com"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read()
    path.write_bytes(data)
    return data


def create_app(dataset_dir: Path = DATASET_DIR) -> FastAPI:
    """Create the dashboard FastAPI app."""
    app = FastAPI(title="chan_meas offline analysis dashboard", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/sage_outputs", StaticFiles(directory="/mnt/win_data/data_mea/zjk_mea/sage_outputs"), name="sage_outputs")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/tiles/base/{z}/{x}/{y}.jpg", include_in_schema=False)
    def base_tile(z: int, x: int, y: int) -> Response:
        try:
            return Response(content=_load_or_fetch_map_tile(z, x, y), media_type="image/jpeg")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"map tile unavailable: {exc}") from exc

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "datasetCount": len(list_dataset_files(dataset_dir))}

    @app.get("/api/datasets")
    def datasets() -> dict[str, Any]:
        names = list_dataset_files(dataset_dir)
        default_name = _default_dataset_name(dataset_dir) if names else None
        return {"datasets": names, "default": default_name}

    @app.get("/api/datasets/default")
    def default_dataset() -> dict[str, Any]:
        try:
            return load_dataset_file(_default_dataset_name(dataset_dir), dataset_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/datasets/{name}/dpsd/{frame_index}")
    def dataset_dpsd_frame(name: str, frame_index: int) -> dict[str, Any]:
        try:
            return load_dpsd_frame(name, frame_index, dataset_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/datasets/{name}")
    def dataset(name: str) -> dict[str, Any]:
        try:
            return load_dataset_file(name, dataset_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
