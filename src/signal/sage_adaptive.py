"""Adaptive SAGE termination based on reconstructed PDP energy coverage.

This module provides an alternative SAGE estimator that does not rely on a
hard min_peak_relative_db threshold.  Instead it keeps adding MPCs until the
reconstructed PDP energy (first 300 delay bins) reaches a target fraction of
the original PDP energy, or the per-path coverage gain drops below a floor.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from src.signal.delay_doppler_sage import (
    SagePathEstimate,
    SageWindowEstimate,
    _complex_tone,
    _fft_spectrum,
    _fit_atom,
    _initial_candidates_from_fft,
    _kernel_for_delay,
    _local_delay_prominence_db,
    _local_maxima_1d,
    _path_reconstruction,
    _prepare_delay_kernel,
    _select_diverse_candidates,
    _window_delay_power,
)


def _initial_candidates_unthresholded(
    segment: np.ndarray,
    *,
    n_doppler_bins: int,
    frame_rate_hz: float,
    min_delay_separation_bins: int,
    use_hann_window: bool,
    use_gpu: bool,
) -> list[dict[str, Any]]:
    """Return candidate seeds without a hard PDP peak threshold.

    We take *all* PDP local maxima (no relative-dB cutoff) and merge them
    with FFT candidates that are above a very loose floor (-30 dB).  The
    ranking still favours strong peaks, but weak peaks are not discarded
    upfront.
    """
    power = np.abs(segment.astype(np.complex128)) ** 2
    robust_power = np.median(power, axis=0)
    if segment.shape[0] >= 8:
        robust_power = 0.7 * robust_power + 0.3 * np.percentile(power, 75, axis=0)

    # PDP peaks: all local maxima, no relative-dB gate.
    if robust_power.size >= 3:
        rank_power = robust_power.copy()
        rank_power[1:-1] = 0.25 * robust_power[:-2] + 0.5 * robust_power[1:-1] + 0.25 * robust_power[2:]
    else:
        rank_power = robust_power
    robust_power_db = 10.0 * np.log10(rank_power + 1e-30)
    rel_pdp_db = robust_power_db - float(np.max(robust_power_db))

    peak_idx = _local_maxima_1d(rank_power)
    # If no local maxima, fall back to the global maximum.
    if peak_idx.size == 0:
        peak_idx = np.array([int(np.argmax(rank_power))], dtype=np.int64)

    _, fft_rel_db = _fft_spectrum(
        segment,
        n_doppler_bins=n_doppler_bins,
        use_hann_window=use_hann_window,
        use_gpu=use_gpu if use_gpu else False,
        normalize=True,
    )
    pdp_cands: list[dict[str, Any]] = []
    for delay_col in peak_idx:
        dop_idx = int(np.argmax(fft_rel_db[:, int(delay_col)]))
        rank = float(rel_pdp_db[int(delay_col)] + 0.15 * fft_rel_db[dop_idx, int(delay_col)])
        pdp_cands.append(
            {
                "delay_col": int(delay_col),
                "dop_idx": dop_idx,
                "pdp_relative_db": float(rel_pdp_db[int(delay_col)]),
                "fft_relative_db": float(fft_rel_db[dop_idx, int(delay_col)]),
                "rank_score_db": rank,
                "source": "pdp",
            }
        )

    # FFT candidates with a very loose floor so we do not miss weak coherent peaks.
    fft_cands = _initial_candidates_from_fft(
        segment,
        n_doppler_bins=n_doppler_bins,
        max_paths=30,
        min_peak_relative_db=30.0,  # loose: -30 dB relative to FFT peak
        min_delay_separation_bins=min_delay_separation_bins,
        min_doppler_separation_bins=0,
        use_hann_window=use_hann_window,
        use_gpu=use_gpu if use_gpu else False,
    )

    # Merge PDP first, then FFT, without a hard count cap yet.
    merged = list(pdp_cands)
    delay_sep = max(1, int(min_delay_separation_bins))
    for cand in fft_cands:
        if any(abs(int(cand["delay_col"]) - int(old["delay_col"])) <= delay_sep for old in merged):
            continue
        merged.append(cand)

    # Sort by composite rank so we try strong candidates first.
    merged.sort(key=lambda c: float(c["rank_score_db"]), reverse=True)
    return merged


def estimate_window_paths_adaptive(
    segment: np.ndarray,
    *,
    delay_bins: np.ndarray,
    bandwidth_hz: float,
    frame_rate_hz: float,
    n_doppler_bins: int = 128,
    max_iter: int = 3,
    min_delay_separation_bins: int = 2,
    use_hann_window: bool = True,
    use_gpu: bool = False,
    pulse_half_width_bins: int = 4,
    delay_search_bins: int = 8,
    doppler_search_half_span_hz: float = 3.0,
    doppler_search_points: int = 81,
    pulse_kernel: np.ndarray | None = None,
    coverage_target: float = 0.90,
    min_coverage_gain: float = 0.005,
    max_paths_hard: int = 30,
    coverage_delay_bins: int = 300,
    enable_weak_nonprominent_prune: bool = True,
) -> SageWindowEstimate:
    """Adaptive SAGE: add paths until reconstructed PDP coverage is met.

    Parameters
    ----------
    coverage_target :
        Stop when sum(|s_sum|²[:coverage_delay_bins]) / sum(|segment|²[:coverage_delay_bins])
        reaches this fraction (e.g. 0.90).
    min_coverage_gain :
        Also stop if the last added path improved coverage by less than this
        fraction (e.g. 0.005 = 0.5 %).
    max_paths_hard :
        Safety cap so we never spin forever.
    coverage_delay_bins :
        Number of leading delay bins used for the coverage metric.
    """
    if segment.ndim != 2:
        raise ValueError(f"segment must be 2D, got shape={segment.shape}")
    n_slow, n_delay = segment.shape
    if n_slow == 0 or n_delay == 0:
        return SageWindowEstimate(raw_candidates=[], raw_metadata=[], pruned_candidates=[], final_paths=[])

    doppler_axis = np.fft.fftshift(np.fft.fftfreq(int(n_doppler_bins), d=1.0 / float(frame_rate_hz)))
    kernel = _prepare_delay_kernel(pulse_half_width_bins, pulse_kernel)
    x = segment.astype(np.complex128)
    robust_delay_power = _window_delay_power(x)

    # Original PDP energy (non-coherent average over slow-time).
    pdp_orig = np.mean(np.abs(x) ** 2, axis=0)
    n_cov = min(int(coverage_delay_bins), n_delay)
    orig_energy = float(np.sum(pdp_orig[:n_cov]))
    orig_energy = max(orig_energy, 1e-30)

    # Candidate pool.
    candidates = _initial_candidates_unthresholded(
        x,
        n_doppler_bins=n_doppler_bins,
        frame_rate_hz=frame_rate_hz,
        min_delay_separation_bins=min_delay_separation_bins,
        use_hann_window=use_hann_window,
        use_gpu=use_gpu,
    )
    if not candidates:
        return SageWindowEstimate(raw_candidates=[], raw_metadata=[], pruned_candidates=[], final_paths=[])

    path_states: list[dict[str, Any]] = []
    s_list: list[np.ndarray] = []
    s_sum = np.zeros_like(x, dtype=np.complex128)
    coverage = 0.0

    for path_id, cand in enumerate(candidates, start=1):
        if path_id > max_paths_hard:
            break
        delay_col0 = int(cand["delay_col"])
        dop_idx = int(cand.get("dop_idx", int(n_doppler_bins) // 2))
        dop_idx = max(0, min(int(n_doppler_bins) - 1, dop_idx))
        fd0 = float(doppler_axis[dop_idx])

        delay_col, fd, amp, score = _fit_atom(
            x - s_sum,
            frame_rate_hz=frame_rate_hz,
            init_delay_col=delay_col0,
            init_doppler_hz=fd0,
            kernel=kernel,
            delay_search_bins=delay_search_bins,
            doppler_search_half_span_hz=doppler_search_half_span_hz,
            doppler_search_points=doppler_search_points,
        )
        s_path = _path_reconstruction(
            n_slow,
            n_delay,
            frame_rate_hz=frame_rate_hz,
            delay_col=delay_col,
            doppler_hz=fd,
            amplitude=amp,
            kernel=kernel,
        )
        s_sum += s_path
        s_list.append(s_path)
        path_states.append(
            {
                "path_id": path_id,
                "delay_col": int(delay_col),
                "doppler_hz": float(fd),
                "amplitude": complex(amp),
                "score": float(score),
                "score_db": float(cand.get("rank_score_db", 0.0)),
                "source": str(cand.get("source", "unknown")),
            }
        )

        # Coverage check.
        pdp_recon = np.mean(np.abs(s_sum) ** 2, axis=0)
        new_coverage = float(np.sum(pdp_recon[:n_cov]) / orig_energy)
        gain = new_coverage - coverage
        coverage = new_coverage

        if coverage >= coverage_target:
            break
        if gain < min_coverage_gain and path_id >= 2:
            # The last path contributed almost nothing; back it out.
            s_sum -= s_path
            s_list.pop()
            path_states.pop()
            break

    # SAGE iterations over the kept paths.
    for _ in range(int(max_iter)):
        for idx, state in enumerate(path_states):
            x_l = x - (s_sum - s_list[idx])
            delay_col, fd, amp, score = _fit_atom(
                x_l,
                frame_rate_hz=frame_rate_hz,
                init_delay_col=int(state["delay_col"]),
                init_doppler_hz=float(state["doppler_hz"]),
                kernel=kernel,
                delay_search_bins=delay_search_bins,
                doppler_search_half_span_hz=max(1.0, doppler_search_half_span_hz / 2.0),
                doppler_search_points=doppler_search_points,
            )
            s_new = _path_reconstruction(
                n_slow,
                n_delay,
                frame_rate_hz=frame_rate_hz,
                delay_col=delay_col,
                doppler_hz=fd,
                amplitude=amp,
                kernel=kernel,
            )
            s_sum = s_sum - s_list[idx] + s_new
            s_list[idx] = s_new
            state["delay_col"] = int(delay_col)
            state["doppler_hz"] = float(fd)
            state["amplitude"] = complex(amp)
            state["score"] = float(score)

    # Build raw results.
    raw_results: list[SagePathEstimate] = []
    raw_meta: list[dict[str, float | str]] = []
    strongest_power_db = -np.inf
    for state in path_states:
        delay_col = int(state["delay_col"])
        if delay_col < 0 or delay_col >= len(delay_bins):
            continue
        delay_bin = int(delay_bins[delay_col])
        amp = complex(state["amplitude"])
        power_db = 10.0 * np.log10(abs(amp) ** 2 + 1e-30)
        score_db = 10.0 * np.log10(float(state.get("score", 0.0)) + 1e-30)
        strongest_power_db = max(strongest_power_db, float(power_db))
        raw_results.append(
            SagePathEstimate(
                delay_col=delay_col,
                delay_bin=delay_bin,
                delay_ns=float(delay_bin / float(bandwidth_hz) * 1e9),
                doppler_hz=float(state["doppler_hz"]),
                amplitude=amp,
                power_db=float(power_db),
                score_db=float(score_db),
                path_id=int(state["path_id"]),
            )
        )
        raw_meta.append(
            {
                "local_prominence_db": _local_delay_prominence_db(
                    robust_delay_power,
                    delay_col=delay_col,
                    exclusion_radius=max(2, int(pulse_half_width_bins)),
                    neighborhood_radius=max(6, int(delay_search_bins) + int(pulse_half_width_bins)),
                )
            }
        )

    # Prune: keep delay-diverse, drop very weak / non-prominent duplicates.
    raw_pairs = list(zip(raw_results, raw_meta, strict=False))
    raw_pairs.sort(key=lambda pair: pair[0].power_db, reverse=True)
    pruned: list[SagePathEstimate] = []
    final_sep = max(1, int(min_delay_separation_bins))
    for item, meta in raw_pairs:
        if any(abs(item.delay_col - old.delay_col) <= final_sep for old in pruned):
            continue
        rel_power_db = float(item.power_db - strongest_power_db)
        local_prominence_db = float(meta["local_prominence_db"])
        if pruned and enable_weak_nonprominent_prune and local_prominence_db < 3.0 and rel_power_db < -15.0:
            continue
        pruned.append(item)
        if len(pruned) >= max_paths_hard:
            break
    for idx, item in enumerate(pruned, start=1):
        item.path_id = idx

    return SageWindowEstimate(
        raw_candidates=raw_results,
        raw_metadata=raw_meta,
        pruned_candidates=pruned,
        final_paths=pruned,
    )
