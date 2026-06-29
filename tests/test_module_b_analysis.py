import math

from src.analysis.module_b import (
    build_module_b_payload,
    compute_path_loss_series,
    fit_log_distance_curve,
    rms_delay_spread_ns,
    rms_doppler_spread_hz,
)


def _toy_dataset():
    return {
        "meta": {
            "name": "toy.bin",
            "frameRateHz": 100.0,
            "bandwidthHz": 50e6,
        },
        "frameStats": [
            {"frame": 10, "timeSec": 0.10, "distanceM": 10.0},
            {"frame": 110, "timeSec": 1.10, "distanceM": 20.0},
        ],
        "sageDelayDoppler": {
            "windowSizeFrames": 20,
            "stepFrames": 100,
            "windowTracks": [
                {
                    "frame": 10,
                    "timeSec": 0.10,
                    "frameStart": 0,
                    "frameEnd": 20,
                    "peaks": [
                        {
                            "delayNs": 10.0,
                            "dopplerHz": 1.0,
                            "amplitudeReal": 1.0,
                            "amplitudeImag": 0.0,
                        },
                        {
                            "delayNs": 20.0,
                            "dopplerHz": -1.0,
                            "amplitudeReal": 0.5,
                            "amplitudeImag": 0.0,
                        },
                    ],
                },
                {
                    "frame": 110,
                    "timeSec": 1.10,
                    "frameStart": 100,
                    "frameEnd": 120,
                    "peaks": [
                        {
                            "delayNs": 30.0,
                            "dopplerHz": 2.0,
                            "amplitudeReal": 0.25,
                            "amplitudeImag": 0.25,
                        }
                    ],
                },
            ]
        },
    }


def test_compute_path_loss_series_uses_noncoherent_power_sum():
    result = compute_path_loss_series(_toy_dataset())

    assert result["distanceM"] == [10.0, 20.0]
    expected0 = 10.0 * math.log10((1.0**2 + 0.5**2) + 1e-30)
    expected1 = 10.0 * math.log10((0.25**2 + 0.25**2) + 1e-30)
    assert math.isclose(result["measuredDb"][0], expected0, rel_tol=1e-9)
    assert math.isclose(result["measuredDb"][1], expected1, rel_tol=1e-9)


def test_fit_log_distance_curve_returns_residuals_matching_input_length():
    fit = fit_log_distance_curve([10.0, 20.0, 40.0], [-30.0, -36.0, -42.0])

    assert fit["model"] == "log_distance_linear_fit"
    assert len(fit["xDistanceM"]) == 3
    assert len(fit["yFitDb"]) == 3
    assert len(fit["residualDb"]) == 3
    assert set(fit["params"]) >= {"beta0", "beta1", "rmse", "r2"}


def test_rms_delay_and_doppler_spread_use_power_weights():
    peaks = [
        {"delayNs": 10.0, "dopplerHz": -2.0, "amplitudeReal": 1.0, "amplitudeImag": 0.0},
        {"delayNs": 30.0, "dopplerHz": 2.0, "amplitudeReal": 1.0, "amplitudeImag": 0.0},
    ]

    assert math.isclose(rms_delay_spread_ns(peaks), 10.0, rel_tol=1e-9)
    assert math.isclose(rms_doppler_spread_hz(peaks), 2.0, rel_tol=1e-9)


def test_build_module_b_payload_contains_all_required_sections():
    payload = build_module_b_payload(_toy_dataset())

    assert set(payload) >= {
        "meta",
        "pathLoss",
        "shadowFading",
        "multipathFading",
        "kFactor",
        "rmsDelaySpread",
        "rmsDopplerSpread",
    }
    assert payload["meta"]["datasetName"] == "toy.bin"
    assert payload["pathLoss"]["distanceM"] == [10.0, 20.0]
    assert payload["shadowFading"]["pdf"]["model"] == "gaussian"
    assert payload["multipathFading"]["defaultModel"] == "nakagami"
