import numpy as np

from src.calibration.b2b_frequency import regularized_frequency_calibrate
from src.signal.delay_doppler_sage import estimate_window_paths, estimate_window_paths_detailed


def test_regularized_frequency_calibrate_recovers_sparse_channel_without_blowup():
    n = 64
    system = np.zeros(n, dtype=np.complex128)
    system[0] = 1.0
    system[1] = 0.35
    system[2] = -0.15j
    channel = np.zeros(n, dtype=np.complex128)
    channel[5] = 1.0 + 0.2j
    channel[19] = 0.45 - 0.1j
    measured = np.fft.ifft(np.fft.fft(channel) * np.fft.fft(system))

    calibrated = regularized_frequency_calibrate(measured, system, regularization=1e-6)

    assert np.max(np.abs(calibrated - channel)) < 1e-5


def test_regularized_frequency_calibrate_handles_deep_notch_with_finite_output():
    n = 64
    system_freq = np.ones(n, dtype=np.complex128)
    system_freq[17] = 1e-8
    system = np.fft.ifft(system_freq)
    measured = np.ones(n, dtype=np.complex128) * 0.01

    calibrated = regularized_frequency_calibrate(measured, system, regularization=1e-3)

    assert np.all(np.isfinite(calibrated.real))
    assert np.all(np.isfinite(calibrated.imag))
    assert np.max(np.abs(calibrated)) < 100.0


def test_estimate_window_paths_accepts_external_complex_pulse_kernel():
    n_frames = 64
    n_delay = 64
    frame_rate_hz = 64.0
    bandwidth_hz = 50e6
    t = np.arange(n_frames) / frame_rate_hz
    pulse_kernel = np.array([0.2j, 1.0 + 0.0j, -0.25j], dtype=np.complex128)
    cir = np.zeros((n_frames, n_delay), dtype=np.complex128)
    tone = np.exp(1j * 2 * np.pi * 9.0 * t)
    for offset, val in enumerate(pulse_kernel):
        cir[:, 20 + offset - 1] += val * tone

    estimates = estimate_window_paths(
        cir,
        delay_bins=np.arange(n_delay, dtype=np.int64),
        bandwidth_hz=bandwidth_hz,
        frame_rate_hz=frame_rate_hz,
        max_paths=1,
        n_doppler_bins=64,
        max_iter=2,
        min_peak_relative_db=18.0,
        min_delay_separation_bins=1,
        min_doppler_separation_bins=2,
        use_hann_window=True,
        use_gpu=False,
        pulse_kernel=pulse_kernel,
        delay_search_bins=3,
    )

    assert len(estimates) == 1
    assert estimates[0].delay_bin == 20
    assert abs(estimates[0].doppler_hz - 9.0) <= 1.0


def test_estimate_window_paths_detailed_preserves_raw_and_pruned_candidates():
    n_frames = 64
    n_delay = 64
    frame_rate_hz = 64.0
    bandwidth_hz = 50e6
    t = np.arange(n_frames) / frame_rate_hz
    cir = np.zeros((n_frames, n_delay), dtype=np.complex128)
    cir[:, 12] = np.exp(1j * 2 * np.pi * 7.0 * t)
    cir[:, 32] = 0.5 * np.exp(1j * 2 * np.pi * -11.0 * t)

    detailed = estimate_window_paths_detailed(
        cir,
        delay_bins=np.arange(n_delay, dtype=np.int64),
        bandwidth_hz=bandwidth_hz,
        frame_rate_hz=frame_rate_hz,
        max_paths=4,
        n_doppler_bins=64,
        max_iter=2,
        min_peak_relative_db=18.0,
        min_delay_separation_bins=1,
        min_doppler_separation_bins=2,
        use_hann_window=True,
        use_gpu=False,
    )

    assert len(detailed.raw_candidates) >= len(detailed.pruned_candidates) >= 2
    assert [p.path_id for p in detailed.final_paths] == list(range(1, len(detailed.final_paths) + 1))
    assert all("local_prominence_db" in meta for meta in detailed.raw_metadata)
