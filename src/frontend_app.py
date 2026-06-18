"""FastAPI frontend shell for the channel-measurement offline analysis UI.

The heavy signal-processing code stays in :mod:`src.ui_dataset`.  This module is
only a thin web layer that serves the dashboard and already-exported JSON data,
so it can later be replaced/extended by real upload and processing endpoints.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import urllib.request

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.paths import ZJK_RAW_DIR, ZJK_SAGE_OUTPUTS_DIR
from src.pipeline.analyze import analyze_one

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"
STATIC_DIR = WEB_DIR / "static"
DATASET_DIR = PROJECT_ROOT / "data" / "ui_samples"
TILE_CACHE_DIR = PROJECT_ROOT / "data" / "tile_cache" / "esri_imagery"
PREFERRED_DATASET_NAME = "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json"
LEGACY_DEFAULT_DATASET_NAME = "zjk_last_measurement_max15_full.json"

# 原始测量 .bin 所在目录 + SAGE 离线处理输出目录；都从 config/local.py 取，换机器不用改代码。
RAW_BIN_DIRS = [ZJK_RAW_DIR] if ZJK_RAW_DIR else []
SAGE_OUTPUTS_DIR = ZJK_SAGE_OUTPUTS_DIR
ADAPTIVE_SUMMARY_PATH = (
    SAGE_OUTPUTS_DIR / "adaptive_w20_step100" / "adaptive_summary.json" if SAGE_OUTPUTS_DIR else None
)

# ---- compute-or-cache job state（单 worker 假设，见实现规格 §4.1）----
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}
RUNNING_BY_STEM: dict[str, str] = {}
_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def normalize_stem(name: str) -> str:
    """Strip path and .bin suffix (case-insensitive); reject path traversal."""
    if not name or Path(name).name != name:
        raise ValueError(f"Invalid bin file name: {name!r}")
    stem = name
    if stem.lower().endswith(".bin"):
        stem = stem[: -len(".bin")]
    return stem


def _resolve_raw_bin(name: str, search_dirs: list[Path] = RAW_BIN_DIRS) -> Path:
    if not name or Path(name).name != name:
        raise ValueError(f"Invalid bin file name: {name!r}")
    for d in search_dirs:
        candidate = d / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"未找到原始测量文件: {name}")


class AnalyzeRequest(BaseModel):
    rxBinName: str
    calBinName: str | None = None
    carrierHz: float = Field(gt=0)
    txMode: str = "static"
    txLat: float | None = None
    txLon: float | None = None
    txAlt: float | None = None
    force: bool = False


def _run_analysis(job_id: str, stem: str, req: AnalyzeRequest, dataset_dir: Path) -> None:
    try:
        rx_path = _resolve_raw_bin(req.rxBinName)
        cal_path = _resolve_raw_bin(req.calBinName) if req.calBinName else None
        analyze_one(
            rx_path,
            carrier_hz=req.carrierHz,
            out_dir=dataset_dir,
            cal_bin_path=cal_path,
            tx_mode=req.txMode,
            tx_lat=req.txLat,
            tx_lon=req.txLon,
            tx_alt=req.txAlt,
        )
        with JOB_LOCK:
            JOBS[job_id] = {"status": "done", "progress": 100, "datasetName": f"{stem}_b2b_adaptive_sage.json"}
    except Exception as exc:  # noqa: BLE001
        with JOB_LOCK:
            JOBS[job_id] = {"status": "error", "progress": 0, "detail": str(exc)}
    finally:
        with JOB_LOCK:
            RUNNING_BY_STEM.pop(stem, None)


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
    _merge_adaptive_summary(payload)
    return payload


def _merge_adaptive_summary(payload: dict[str, Any]) -> None:
    """Merge adaptive_summary.json entry (by bin name) into meta.summary (HIGH-3)."""
    bin_name = payload.get("meta", {}).get("name")
    if not bin_name or ADAPTIVE_SUMMARY_PATH is None or not ADAPTIVE_SUMMARY_PATH.exists():
        return
    try:
        summary = json.loads(ADAPTIVE_SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for entry in summary.get("files", []):
        if entry.get("file") == bin_name:
            payload.setdefault("meta", {})["summary"] = entry
            return


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
    if SAGE_OUTPUTS_DIR is not None and SAGE_OUTPUTS_DIR.exists():
        app.mount("/sage_outputs", StaticFiles(directory=SAGE_OUTPUTS_DIR), name="sage_outputs")

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

    @app.post("/api/analyze")
    def analyze(req: AnalyzeRequest) -> dict[str, Any]:
        try:
            stem = normalize_stem(req.rxBinName)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        json_path = dataset_dir / f"{stem}_b2b_adaptive_sage.json"
        with JOB_LOCK:
            if stem in RUNNING_BY_STEM:
                return {"status": "running", "jobId": RUNNING_BY_STEM[stem]}
            if json_path.exists() and not req.force:
                return {"status": "ready", "datasetName": json_path.name}
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {"status": "running", "progress": 0}
            RUNNING_BY_STEM[stem] = job_id
            _EXECUTOR.submit(_run_analysis, job_id, stem, req, dataset_dir)
        return {"status": "running", "jobId": job_id}

    @app.get("/api/analyze/status/{job_id}")
    def analyze_status(job_id: str) -> dict[str, Any]:
        with JOB_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown jobId: {job_id}")
        return job

    return app


app = create_app()
