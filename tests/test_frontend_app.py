import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.frontend_app import DATASET_DIR, create_app, list_dataset_files, load_dataset_file


def test_list_dataset_files_finds_existing_ui_samples():
    files = list_dataset_files(DATASET_DIR)

    assert "zjk_last_measurement_music_sample.json" in files
    assert files == sorted(files)


def test_load_dataset_file_rejects_path_traversal():
    with pytest.raises(ValueError):
        load_dataset_file("../memory.md", DATASET_DIR)


def test_api_datasets_and_default_dataset_contract():
    client = TestClient(create_app())

    listing = client.get("/api/datasets")
    assert listing.status_code == 200
    names = listing.json()["datasets"]
    assert "zjk_last_measurement_music_sample.json" in names

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


def test_dashboard_html_serves_mount_points_and_assets():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "V2V信道测量数据离线分析平台" in html
    assert 'id="mapPanel"' in html
    assert 'id="cirWaterfallChart"' in html
    assert 'id="dpsdChart"' in html
    assert 'id="mpcPng"' in html
    assert 'sage_outputs' in html or 'mpcPng' in html
    assert 'id="frameSlider"' in html
    assert 'powerDistributionChart' not in html
    assert 'src="/static/app.js' in html
    assert 'leaflet.css' in html
    assert '工程接口' not in html


def test_default_dataset_prefers_full_max15_joint_tracks_when_available(tmp_path: Path):
    full = {
        "meta": {"name": "full", "numFrames": 682},
        "txGps": {},
        "rxGps": [{}] * 682,
        "frameStats": [{}] * 682,
        "framePayloads": [{}] * 682,
        "cirWaterfall": {},
        "dopplerDelay": {},
        "mpcScatter": [{"pathId": 15}],
        "jointDelayDoppler": {"tracks": [{"pathId": 15}]},
    }
    old = {
        "meta": {"name": "old", "numFrames": 96},
        "musicMpc": {"peaks": []},
    }
    (tmp_path / "zjk_last_measurement_music_sample.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "zjk_last_measurement_max15_full.json").write_text(json.dumps(full), encoding="utf-8")

    app = create_app(dataset_dir=tmp_path)
    client = TestClient(app)

    listing = client.get("/api/datasets").json()
    assert listing["default"] == "zjk_last_measurement_max15_full.json"

    dataset = client.get("/api/datasets/default").json()
    assert dataset["meta"]["numFrames"] == 682
    assert max(track["pathId"] for track in dataset["jointDelayDoppler"]["tracks"]) == 15


def test_static_frontend_files_exist_with_real_event_hooks():
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    css = (static_dir / "styles.css").read_text(encoding="utf-8")

    for hook in [
        "bindControls",
        "loadDatasetFromApi",
        "syncFrame",
        "updateMapPanel",
        "updateCIRPlot",
        "updateDPSDPlot",
        "updateMusicPlot",
        "updateMusicTrackPlot",
        "updateStatsPanel",
    ]:
        assert f"function {hook}" in app_js

    assert "delay_averaged_doppler_time_fft" in app_js
    assert "Time/s" in app_js
    assert "mpcPng" in app_js
    assert "sage_outputs" in app_js
    assert "L.map" in app_js
    assert "echarts.init" in app_js
    assert ".app-shell" in css
    assert ".analysis-grid" in css
