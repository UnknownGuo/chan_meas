import json
import math
from pathlib import Path

import numpy as np

from src.signal.delay_doppler_sage import estimate_window_paths
from src.ui_dataset import (
    DEFAULT_ZJK_TX_GPS,
    TxGps,
    build_dataset_from_arrays,
    compute_doppler_delay,
    compute_frame_payload,
    compute_frame_stats,
    compute_joint_delay_doppler_tracks,
    compute_music_mpc,
    compute_pdp_curve,
    compute_power_distribution,
    compute_sage_delay_doppler_tracks,
    downsample_cir_power_db,
    haversine_m,
    load_tx_gps,
)


def test_haversine_static_tx_to_nearby_rx_is_meter_scale():
    distance = haversine_m(40.303232, 115.771857, 40.303165333333325, 115.77186)
    assert 7.0 <= distance <= 8.5


def test_load_tx_gps_uses_json_sidecar_values(tmp_path: Path):
    path = tmp_path / "tx_gps.json"
    path.write_text(json.dumps({"lat": 1.2, "lon": 3.4, "alt": 5.6}), encoding="utf-8")

    tx = load_tx_gps(path)

    assert tx == TxGps(lat=1.2, lon=3.4, alt=5.6, source=str(path))


def test_load_tx_gps_falls_back_for_image_like_tx_gps_file(tmp_path: Path):
    image_like = tmp_path / "TX_GPS"
    image_like.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    tx = load_tx_gps(image_like)

    assert tx.lat == DEFAULT_ZJK_TX_GPS.lat
    assert tx.lon == DEFAULT_ZJK_TX_GPS.lon
    assert tx.alt == DEFAULT_ZJK_TX_GPS.alt
    assert tx.source == str(image_like)


def test_compute_frame_stats_peak_delay_power_distance_and_rms():
    cir = np.zeros((2, 8), dtype=np.complex64)
    cir[0, 2] = 1.0 + 0j
    cir[0, 3] = 0.5 + 0j
    cir[1, 5] = 2.0 + 0j
    gps = {
        "lat": np.array([40.303165333333325, 40.303165333333325]),
        "lon": np.array([115.77186, 115.77186]),
        "alt": np.array([563.5, 563.5]),
    }

    stats = compute_frame_stats(cir, gps, DEFAULT_ZJK_TX_GPS, bandwidth_hz=50e6, frame_rate_hz=100.0)

    assert len(stats) == 2
    assert stats[0]["frame"] == 0
    assert stats[0]["timeSec"] == 0.0
    assert stats[0]["peakDelayNs"] == 40.0
    assert math.isclose(stats[0]["peakPowerDb"], 0.0, abs_tol=1e-6)
    assert 7.0 <= stats[0]["distanceM"] <= 8.5
    assert stats[0]["pathCount"] == 2
    assert stats[1]["peakDelayNs"] == 100.0
    assert math.isclose(stats[1]["peakPowerDb"], 6.0205999, rel_tol=1e-5)


def test_downsample_cir_power_db_limits_delay_bins_and_preserves_frame_count():
    cir = np.ones((3, 16), dtype=np.complex64)

    delay_ns, power_db = downsample_cir_power_db(cir, bandwidth_hz=50e6, max_delay_bins=4)

    assert delay_ns == [0.0, 80.0, 160.0, 240.0]
    assert len(power_db) == 3
    assert len(power_db[0]) == 4


def test_build_dataset_from_arrays_has_frontend_contract_keys():
    cir = np.zeros((2, 8), dtype=np.complex64)
    cir[:, 2] = 1.0
    gps = {
        "lat": np.array([40.303165333333325, 40.303166]),
        "lon": np.array([115.77186, 115.771861]),
        "alt": np.array([563.5, 563.6]),
        "hour": np.array([7, 7]),
        "minute": np.array([59, 59]),
        "second": np.array([24, 24]),
    }

    dataset = build_dataset_from_arrays(
        name="synthetic.bin",
        cir=cir,
        gps=gps,
        tx_gps=DEFAULT_ZJK_TX_GPS,
        bandwidth_hz=50e6,
        frame_rate_hz=100.0,
        max_delay_bins=4,
    )

    assert set(dataset) >= {"meta", "txGps", "rxGps", "frameStats", "cirWaterfall", "dopplerDelay", "mpcScatter"}
    assert dataset["meta"]["name"] == "synthetic.bin"
    assert dataset["meta"]["numFrames"] == 2
    assert dataset["txGps"]["lat"] == DEFAULT_ZJK_TX_GPS.lat
    assert len(dataset["rxGps"]) == 1  # 100 Hz -> decimated to 1 fps
    assert len(dataset["frameStats"]) == 1
    assert len(dataset["cirWaterfall"]["powerDb"]) == 1


def test_compute_pdp_curve_returns_delay_and_relative_power_for_one_frame():
    cir = np.zeros((2, 8), dtype=np.complex64)
    cir[0, 2] = 1.0
    cir[0, 3] = 0.5

    curve = compute_pdp_curve(cir, frame_index=0, bandwidth_hz=50e6, max_delay_bins=4, relative=True)

    assert curve["frame"] == 0
    assert curve["delayNs"] == [0.0, 40.0, 80.0, 120.0]
    assert curve["powerDb"][1] == 0.0
    assert curve["powerDb"][0] <= -250.0
    assert curve["peakDelayNs"] == 40.0


def test_compute_power_distribution_bins_relative_to_peak():
    power_db = np.array([-10.0, -25.0, -45.0, -65.0, -85.0])

    dist = compute_power_distribution(power_db, relative_to_peak=False)

    assert [item["label"] for item in dist] == [">-20", "-20~-40", "-40~-60", "-60~-80", "<-80"]
    assert [item["count"] for item in dist] == [1, 1, 1, 1, 1]
    assert sum(item["percent"] for item in dist) == 100.0


def test_compute_doppler_delay_detects_known_slow_time_frequency():
    n_frames = 32
    n_delay = 8
    frame_rate_hz = 100.0
    doppler_hz = 25.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 3] = np.exp(1j * 2 * np.pi * doppler_hz * t)

    dpsd = compute_doppler_delay(
        cir,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        max_delay_bins=8,
        n_doppler_bins=32,
    )

    assert dpsd["mock"] is False
    assert dpsd["delayNs"][3] == 60.0
    delay_idx = dpsd["delayNs"].index(60.0)
    col = np.array([row[delay_idx] for row in dpsd["powerDb"]])
    peak_doppler = dpsd["dopplerHz"][int(np.argmax(col))]
    assert abs(peak_doppler - doppler_hz) <= frame_rate_hz / n_frames


def test_compute_frame_payload_packages_pdp_stats_distribution_and_mpcs():
    cir = np.zeros((3, 8), dtype=np.complex64)
    cir[:, 2] = 1.0
    gps = {
        "lat": np.array([40.303165333333325] * 3),
        "lon": np.array([115.77186] * 3),
        "alt": np.array([563.5] * 3),
    }
    stats = compute_frame_stats(cir, gps, DEFAULT_ZJK_TX_GPS, bandwidth_hz=50e6, frame_rate_hz=100.0)

    payload = compute_frame_payload(cir, gps, DEFAULT_ZJK_TX_GPS, stats, frame_index=1, bandwidth_hz=50e6, frame_rate_hz=100.0)

    assert payload["frame"] == 1
    assert payload["pdpCurve"]["frame"] == 1
    assert payload["stats"]["frame"] == 1
    assert len(payload["powerDistribution"]) == 5
    assert payload["rxGps"]["frame"] == 1
    assert payload["mpcScatter"][0]["pathId"] == 1


def test_compute_doppler_time_waterfall_averages_delay_domain_per_window():
    n_frames = 200
    n_delay = 48
    frame_rate_hz = 100.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 12.0 * t)
    cir[:, 20] = 0.7 * np.exp(1j * 2 * np.pi * 12.0 * t)

    from src.ui_dataset import compute_doppler_time_waterfall

    waterfall = compute_doppler_time_waterfall(
        cir,
        frame_rate_hz=frame_rate_hz,
        window_size_frames=64,
        step_frames=100,
        max_delay_bins=48,
        n_doppler_bins=64,
        relative_to_peak=False,
    )

    assert waterfall["method"] == "delay_averaged_doppler_time_fft"
    assert waterfall["timeSec"] == [0.32, 1.32]
    assert len(waterfall["powerDb"]) == 64
    assert len(waterfall["powerDb"][0]) == 2
    peak_col0 = int(np.argmax([row[0] for row in waterfall["powerDb"]]))
    peak_doppler = waterfall["dopplerHz"][peak_col0]
    assert abs(peak_doppler - 12.0) <= 2.0


def test_compute_doppler_delay_frame_matches_matlab_style_fft_axes():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 100.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 12.0 * t)
    cir[:, 30] = 0.8 * np.exp(1j * 2 * np.pi * -18.0 * t)

    from src.ui_dataset import compute_doppler_delay_frame

    dpsd = compute_doppler_delay_frame(
        cir,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        max_delay_bins=48,
        n_doppler_bins=64,
        relative_to_peak=False,
    )

    assert dpsd["method"] == "matlab_style_doppler_delay_fft"
    assert dpsd["delayAxis"] == "delay_bin"
    assert dpsd["dopplerHz"][0] == -50.0
    assert dpsd["dopplerHz"][-1] == 50.0
    assert len(dpsd["powerDb"]) == 64
    assert len(dpsd["powerDb"][0]) == 48
    delay10_col = dpsd["delayBins"].index(10)
    delay30_col = dpsd["delayBins"].index(30)
    peak_doppler_10 = dpsd["dopplerHz"][int(np.argmax([row[delay10_col] for row in dpsd["powerDb"]]))]
    peak_doppler_30 = dpsd["dopplerHz"][int(np.argmax([row[delay30_col] for row in dpsd["powerDb"]]))]
    assert abs(peak_doppler_10 - 12.0) <= 2.0
    assert abs(peak_doppler_30 - -18.0) <= 2.0


def test_compute_joint_delay_doppler_tracks_recovers_two_paths_in_one_window():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 64.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 8.0 * t)
    cir[:, 25] = 0.6 * np.exp(1j * 2 * np.pi * -12.0 * t)

    result = compute_joint_delay_doppler_tracks(
        cir,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        window_size_frames=64,
        step_frames=64,
        delay_gate_distance_m=2000.0,
        max_delay_bins=48,
        n_doppler_bins=64,
        max_paths=2,
    )

    assert result["mock"] is False
    assert result["method"] == "joint_delay_doppler_fft"
    assert result["delayGateDistanceM"] == 2000.0
    assert result["windowSizeFrames"] == 64
    assert result["stepFrames"] == 64
    assert len(result["windowTracks"]) == 1
    window = result["windowTracks"][0]
    assert window["frame"] == 32
    assert len(window["peaks"]) == 2
    delays = sorted(round(p["delayNs"], 1) for p in window["peaks"])
    dopplers = sorted(round(p["dopplerHz"], 1) for p in window["peaks"])
    assert delays == [200.0, 500.0]
    assert dopplers == [-12.0, 8.0]
    assert len(result["tracks"]) == 2


def test_build_dataset_from_arrays_includes_joint_tracks_when_requested():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 64.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 8.0 * t)
    cir[:, 25] = 0.6 * np.exp(1j * 2 * np.pi * -12.0 * t)
    gps = {
        "lat": np.array([40.303165333333325] * n_frames),
        "lon": np.array([115.77186] * n_frames),
        "alt": np.array([563.5] * n_frames),
        "hour": np.array([7] * n_frames),
        "minute": np.array([59] * n_frames),
        "second": np.arange(n_frames) % 60,
    }

    dataset = build_dataset_from_arrays(
        name="joint.bin",
        cir=cir,
        gps=gps,
        tx_gps=DEFAULT_ZJK_TX_GPS,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        max_delay_bins=48,
        include_joint=True,
    )

    assert "jointDelayDoppler" in dataset
    assert dataset["jointDelayDoppler"]["method"] == "joint_delay_doppler_fft"
    assert len(dataset["jointDelayDoppler"]["tracks"]) == 2
    assert dataset["mpcScatter"][0]["mock"] is False


def test_build_dataset_from_arrays_uses_default_joint_max_paths_15():
    n_frames = 64
    n_delay = 80
    frame_rate_hz = 64.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    for path_idx in range(15):
        delay_bin = 4 + path_idx * 4
        doppler_hz = -24.0 + path_idx * 3.0
        amplitude = 1.0 - path_idx * 0.02
        cir[:, delay_bin] = amplitude * np.exp(1j * 2 * np.pi * doppler_hz * t)
    gps = {
        "lat": np.array([40.303165333333325] * n_frames),
        "lon": np.array([115.77186] * n_frames),
        "alt": np.array([563.5] * n_frames),
    }

    dataset = build_dataset_from_arrays(
        name="joint15.bin",
        cir=cir,
        gps=gps,
        tx_gps=DEFAULT_ZJK_TX_GPS,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        max_delay_bins=80,
        include_joint=True,
    )

    path_ids = {track["pathId"] for track in dataset["jointDelayDoppler"]["tracks"]}
    assert max(path_ids) == 15


def test_compute_sage_delay_doppler_tracks_recovers_two_paths_in_one_window():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 64.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 8.0 * t)
    cir[:, 25] = 0.6 * np.exp(1j * 2 * np.pi * -12.0 * t)

    result = compute_sage_delay_doppler_tracks(
        cir,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        window_size_frames=64,
        step_frames=64,
        delay_gate_distance_m=2000.0,
        max_delay_bins=48,
        n_doppler_bins=64,
        max_paths=2,
        max_iter=2,
        use_gpu=False,
    )

    assert result["mock"] is False
    assert result["method"] == "delay_doppler_sage"
    assert result["windowSizeFrames"] == 64
    assert result["stepFrames"] == 64
    assert len(result["windowTracks"]) == 1
    window = result["windowTracks"][0]
    assert window["frame"] == 32
    assert len(window["peaks"]) == 2
    delays = sorted(round(p["delayNs"], 1) for p in window["peaks"])
    dopplers = sorted(round(p["dopplerHz"], 1) for p in window["peaks"])
    assert delays == [200.0, 500.0]
    assert dopplers == [-12.0, 8.0]
    assert all("amplitudeReal" in peak and "amplitudeImag" in peak for peak in window["peaks"])


def test_estimate_window_paths_rejects_flat_delay_burst_candidates():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 64.0
    bandwidth_hz = 50e6
    t = np.arange(n_frames) / frame_rate_hz
    rng = np.random.default_rng(0)
    segment = 0.03 * np.exp(1j * 2 * np.pi * 1.5 * t)[:, None] * np.ones((1, n_delay), dtype=np.complex128)
    segment = segment + 0.004 * (rng.standard_normal((n_frames, n_delay)) + 1j * rng.standard_normal((n_frames, n_delay)))
    segment[:, 12] += 1.0 * np.exp(1j * 2 * np.pi * 8.0 * t)

    estimates = estimate_window_paths(
        segment,
        delay_bins=np.arange(n_delay, dtype=np.int64),
        bandwidth_hz=bandwidth_hz,
        frame_rate_hz=frame_rate_hz,
        max_paths=8,
        n_doppler_bins=64,
        max_iter=3,
        min_peak_relative_db=18.0,
        min_delay_separation_bins=1,
        min_doppler_separation_bins=2,
        use_hann_window=True,
        use_gpu=False,
    )

    assert len(estimates) == 1
    assert abs(estimates[0].delay_ns - 240.0) <= 20.0


def test_build_dataset_from_arrays_includes_sage_tracks_when_requested():
    n_frames = 64
    n_delay = 48
    frame_rate_hz = 64.0
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex64)
    cir[:, 10] = np.exp(1j * 2 * np.pi * 8.0 * t)
    cir[:, 25] = 0.6 * np.exp(1j * 2 * np.pi * -12.0 * t)
    gps = {
        "lat": np.array([40.303165333333325] * n_frames),
        "lon": np.array([115.77186] * n_frames),
        "alt": np.array([563.5] * n_frames),
    }

    dataset = build_dataset_from_arrays(
        name="sage.bin",
        cir=cir,
        gps=gps,
        tx_gps=DEFAULT_ZJK_TX_GPS,
        bandwidth_hz=50e6,
        frame_rate_hz=frame_rate_hz,
        max_delay_bins=48,
        include_sage=True,
    )

    assert "sageDelayDoppler" in dataset
    assert dataset["sageDelayDoppler"]["method"] == "adaptive_sage_coverage_095"
    assert len(dataset["sageDelayDoppler"]["tracks"]) == 2
    assert dataset["mpcScatter"][0]["mock"] is False
