from pathlib import Path

import pytest

from src.pipeline.analyze import analyze_one


# ---- TC-005: analyze_one rejects missing/invalid carrier_hz ----

def test_analyze_one_rejects_none_carrier_hz():
    with pytest.raises(ValueError):
        analyze_one(Path("/tmp/whatever.bin"), carrier_hz=None, out_dir=Path("/tmp"))


def test_analyze_one_rejects_zero_or_negative_carrier_hz():
    with pytest.raises(ValueError):
        analyze_one(Path("/tmp/whatever.bin"), carrier_hz=0, out_dir=Path("/tmp"))
    with pytest.raises(ValueError):
        analyze_one(Path("/tmp/whatever.bin"), carrier_hz=-2.8e10, out_dir=Path("/tmp"))


def test_analyze_one_writes_carrier_hz_and_tx_override_into_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rx_bin = tmp_path / "demo.bin"
    rx_bin.write_bytes(b"")

    def fake_build_dataset(rx_path, **kwargs):
        return {"meta": {"name": rx_path.name}, "txGps": {"lat": 0.0, "lon": 0.0}}

    monkeypatch.setattr("src.pipeline.analyze.build_measurement_dataset", fake_build_dataset)

    out_dir = tmp_path / "out"
    out_path = analyze_one(
        rx_bin,
        carrier_hz=2.8e10,
        out_dir=out_dir,
        tx_mode="static",
        tx_lat=40.30,
        tx_lon=115.77,
        tx_alt=560.0,
    )

    assert out_path.exists()
    import json
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["meta"]["carrierHz"] == 2.8e10
    assert payload["meta"]["txMode"] == "static"
    assert payload["txGps"] == {"lat": 40.30, "lon": 115.77, "alt": 560.0, "source": "user_input"}
