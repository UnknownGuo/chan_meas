import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.frontend_app import (
    DATASET_DIR,
    AnalyzeRequest,
    JOB_LOCK,
    JOBS,
    RUNNING_BY_STEM,
    create_app,
    list_dataset_files,
    load_dataset_file,
    normalize_stem,
)


def test_list_dataset_files_finds_existing_ui_samples():
    files = list_dataset_files(DATASET_DIR)

    assert "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json" in files
    assert files == sorted(files)


def test_load_dataset_file_rejects_path_traversal():
    with pytest.raises(ValueError):
        load_dataset_file("../memory.md", DATASET_DIR)


def test_load_dataset_file_merges_adaptive_summary_into_meta():
    payload = load_dataset_file("0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json", DATASET_DIR)
    summary = payload["meta"].get("summary")
    assert summary is not None
    assert summary["file"] == "0m-0m-all-firstantenna-xiaoquan.bin"
    assert summary["nWindows"] > 0


def test_api_datasets_and_default_dataset_contract():
    client = TestClient(create_app())

    listing = client.get("/api/datasets")
    assert listing.status_code == 200
    names = listing.json()["datasets"]
    assert "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json" in names

    dataset = client.get("/api/datasets/default")
    assert dataset.status_code == 200
    payload = dataset.json()
    assert set(payload) >= {
        "meta",
        "txGps",
        "rxGps",
        "frameStats",
        "framePayloads",
        "cirWaterfall",
        "dopplerDelay",
        "mpcScatter",
        "jointDelayDoppler",
    }
    assert payload["meta"]["numFrames"] > 0


def test_dashboard_html_serves_redesigned_layout():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "信道测量分析软件" in html
    assert "V2V" not in html
    assert 'id="mapPanel"' in html
    assert 'id="pdpWaterfallChart"' in html
    assert 'id="delayTimeChart"' in html
    assert 'id="dopplerTimeChart"' in html
    assert 'id="frameSlider"' in html
    assert 'id="carrierHzInput"' in html
    assert 'id="importBtn"' in html
    assert 'id="analyzeBtn"' in html
    assert 'src="/static/app.js' in html
    assert 'leaflet.css' in html


def test_static_frontend_files_exist_with_real_event_hooks():
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    css = (static_dir / "styles.css").read_text(encoding="utf-8")

    for hook in [
        "bindControls",
        "loadDatasetFromApi",
        "syncFrame",
        "updateMapPanel",
        "updatePdpWaterfall",
        "updateDelayTime",
        "updateDopplerTime",
        "updateStatusBar",
        "detectDisplayStep",
        "buildFrameIndex",
        "robustRange",
        "parseCarrier",
        "runAnalyze",
        "pollAnalyze",
    ]:
        assert f"function {hook}" in app_js

    assert "L.map" in app_js
    assert "echarts.init" in app_js
    assert ".app-shell" in css
    assert ".summary-grid" in css


# ---- TC-001: normalize_stem ----

def test_normalize_stem_strips_suffix_and_case():
    assert normalize_stem("0m-0m-all-firstantenna-xiaoquan.bin") == "0m-0m-all-firstantenna-xiaoquan"
    assert normalize_stem("0m-0m-all-firstantenna-xiaoquan.BIN") == "0m-0m-all-firstantenna-xiaoquan"


def test_normalize_stem_rejects_path_traversal():
    with pytest.raises(ValueError):
        normalize_stem("../etc/passwd.bin")


# ---- TC-002/003: /api/analyze cache hit / miss ----

def test_analyze_cache_hit_returns_ready(tmp_path: Path):
    (tmp_path / "xiaoquan_b2b_adaptive_sage.json").write_text("{}", encoding="utf-8")
    client = TestClient(create_app(dataset_dir=tmp_path))

    res = client.post("/api/analyze", json={"rxBinName": "xiaoquan.bin", "carrierHz": 2.8e10})

    assert res.status_code == 200
    assert res.json() == {"status": "ready", "datasetName": "xiaoquan_b2b_adaptive_sage.json"}


def test_analyze_cache_miss_returns_running_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.frontend_app._EXECUTOR.submit", lambda *a, **k: None)
    client = TestClient(create_app(dataset_dir=tmp_path))

    res = client.post("/api/analyze", json={"rxBinName": "not_cached.bin", "carrierHz": 2.8e10})

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "running"
    assert isinstance(body["jobId"], str) and body["jobId"]

    with JOB_LOCK:
        JOBS.pop(body["jobId"], None)
        RUNNING_BY_STEM.pop("not_cached", None)


def test_analyze_invalid_carrier_hz_rejected(tmp_path: Path):
    client = TestClient(create_app(dataset_dir=tmp_path))

    res = client.post("/api/analyze", json={"rxBinName": "x.bin", "carrierHz": 0})

    assert res.status_code == 422


# ---- TC-004: /api/analyze/status ----

def test_analyze_status_unknown_job_404(tmp_path: Path):
    client = TestClient(create_app(dataset_dir=tmp_path))

    res = client.get("/api/analyze/status/does-not-exist")

    assert res.status_code == 404


def test_analyze_status_returns_job_state():
    job_id = "test-job-1"
    with JOB_LOCK:
        JOBS[job_id] = {"status": "running", "progress": 42}
    try:
        client = TestClient(create_app())
        res = client.get(f"/api/analyze/status/{job_id}")
        assert res.status_code == 200
        assert res.json() == {"status": "running", "progress": 42}
    finally:
        with JOB_LOCK:
            JOBS.pop(job_id, None)


# ---- IT-002: cache miss -> background job -> done ----

def test_analyze_end_to_end_with_mocked_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_analyze_one(rx_bin_path, *, carrier_hz, out_dir, **kwargs):
        out_path = out_dir / f"{rx_bin_path.stem}_b2b_adaptive_sage.json"
        out_path.write_text(json.dumps({"meta": {"name": rx_bin_path.name}}), encoding="utf-8")
        return out_path

    monkeypatch.setattr("src.frontend_app.analyze_one", fake_analyze_one)
    monkeypatch.setattr("src.frontend_app._resolve_raw_bin", lambda name, search_dirs=None: Path(f"/tmp/{name}"))

    from concurrent.futures import ThreadPoolExecutor
    sync_executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr("src.frontend_app._EXECUTOR", sync_executor)

    client = TestClient(create_app(dataset_dir=tmp_path))
    res = client.post("/api/analyze", json={"rxBinName": "newfile.bin", "carrierHz": 2.8e10})
    assert res.json()["status"] == "running"
    job_id = res.json()["jobId"]

    sync_executor.shutdown(wait=True)

    status = client.get(f"/api/analyze/status/{job_id}").json()
    assert status["status"] == "done"
    assert status["datasetName"] == "newfile_b2b_adaptive_sage.json"
    assert (tmp_path / "newfile_b2b_adaptive_sage.json").exists()


def test_default_dataset_prefers_preferred_name_when_available(tmp_path: Path):
    preferred = {
        "meta": {"name": "0m-0m-all-firstantenna-xiaoquan.bin", "numFrames": 28309},
        "txGps": {},
        "rxGps": [{}],
        "frameStats": [{}],
        "framePayloads": [{}],
        "cirWaterfall": {},
        "dopplerDelay": {},
        "mpcScatter": [],
        "jointDelayDoppler": {"tracks": []},
    }
    other = {"meta": {"name": "other.bin", "numFrames": 96}, "musicMpc": {"peaks": []}}
    (tmp_path / "other_sample.json").write_text(json.dumps(other), encoding="utf-8")
    (tmp_path / "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json").write_text(
        json.dumps(preferred), encoding="utf-8"
    )

    app = create_app(dataset_dir=tmp_path)
    client = TestClient(app)

    listing = client.get("/api/datasets").json()
    assert listing["default"] == "0m-0m-all-firstantenna-xiaoquan_b2b_adaptive_sage.json"

    dataset = client.get("/api/datasets/default").json()
    assert dataset["meta"]["numFrames"] == 28309
