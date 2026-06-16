from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


@dataclass(frozen=True)
class DelayDopplerSageConfig:
    bandwidth_hz: float
    frame_rate_hz: float
    max_paths: int = 8
    max_iter: int = 5
    n_doppler_bins: int = 128
    min_peak_relative_db: float = 18.0
    min_delay_separation_bins: int = 1
    min_doppler_separation_bins: int = 2
    use_hann_window: bool = True
    use_gpu: bool = False
    # The fields below are deliberately kept optional at the public API level.
    # They fix the original single-bin CLEAN-like implementation by using a
    # finite delay response and PDP-assisted SAGE initialization.
    pulse_half_width_bins: int = 4
    delay_search_bins: int = 8
    doppler_search_half_span_hz: float = 3.0
    doppler_search_points: int = 81
    init_strategy: Literal["hybrid", "pdp", "fft"] = "pdp"


@dataclass
class SagePathEstimate:
    delay_col: int
    delay_bin: int
    delay_ns: float
    doppler_hz: float
    amplitude: complex
    power_db: float
    score_db: float
    path_id: int


@dataclass
class SageWindowEstimate:
    raw_candidates: list[SagePathEstimate]
    raw_metadata: list[dict[str, float | str]]
    pruned_candidates: list[SagePathEstimate]
    final_paths: list[SagePathEstimate]


def _window_delay_power(segment: np.ndarray) -> np.ndarray:
    power = np.abs(segment.astype(np.complex128)) ** 2
    robust = np.median(power, axis=0)
    if segment.shape[0] >= 8:
        robust = 0.7 * robust + 0.3 * np.percentile(power, 75, axis=0)
    return robust.astype(np.float64)


def _local_delay_prominence_db(
    robust_delay_power: np.ndarray,
    *,
    delay_col: int,
    exclusion_radius: int,
    neighborhood_radius: int,
) -> float:
    if robust_delay_power.size == 0:
        return 0.0
    idx = int(delay_col)
    ex = max(0, int(exclusion_radius))
    rad = max(ex + 1, int(neighborhood_radius))
    lo = max(0, idx - rad)
    hi = min(robust_delay_power.size, idx + rad + 1)
    mask = np.ones(hi - lo, dtype=bool)
    ex_lo = max(lo, idx - ex)
    ex_hi = min(hi, idx + ex + 1)
    mask[(ex_lo - lo):(ex_hi - lo)] = False
    neigh = robust_delay_power[lo:hi][mask]
    if neigh.size == 0:
        floor = np.median(robust_delay_power)
    else:
        floor = np.median(neigh)
    peak = float(robust_delay_power[idx])
    return float(10.0 * np.log10((peak + 1e-30) / (floor + 1e-30)))


def _complex_tone(frame_rate_hz: float, doppler_hz: float, n_samples: int) -> np.ndarray:
    n = np.arange(n_samples, dtype=np.float64)
    return np.exp(1j * 2.0 * np.pi * doppler_hz * n / float(frame_rate_hz))


def _fft_spectrum(
    segment: np.ndarray,
    *,
    n_doppler_bins: int,
    use_hann_window: bool,
    use_gpu: bool,
    normalize: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Doppler FFT per delay column.

    Returns complex spectrum and dB magnitude.  Historically this function always
    normalized every call to its own maximum.  Keep that behavior by default for
    compatibility, but allow absolute dB for residual/likelihood diagnostics.
    """
    win = segment.shape[0]
    window = np.hanning(win).astype(np.float64) if use_hann_window and win > 1 else np.ones(win, dtype=np.float64)
    x = segment.astype(np.complex128) * window[:, None]
    if use_gpu and torch is not None and torch.cuda.is_available():
        xt = torch.as_tensor(x, device="cuda")
        spec = torch.fft.fftshift(torch.fft.fft(xt, n=n_doppler_bins, dim=0), dim=0)
        spec_np = spec.detach().cpu().numpy()
    else:
        spec_np = np.fft.fftshift(np.fft.fft(x, n=n_doppler_bins, axis=0), axes=0)
    power_db = 20.0 * np.log10(np.abs(spec_np).astype(np.float64) + 1e-30)
    if normalize:
        power_db -= float(np.max(power_db))
    return spec_np, power_db


def _local_maxima_1d(values: np.ndarray) -> np.ndarray:
    if values.size < 3:
        return np.arange(values.size, dtype=np.int64)
    mask = np.zeros(values.size, dtype=bool)
    mask[1:-1] = (values[1:-1] >= values[:-2]) & (values[1:-1] >= values[2:])
    if values[0] >= values[1]:
        mask[0] = True
    if values[-1] >= values[-2]:
        mask[-1] = True
    return np.flatnonzero(mask)


def _select_diverse_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_paths: int,
    min_delay_separation_bins: int,
    min_doppler_separation_bins: int,
) -> list[dict[str, Any]]:
    """Select candidates while enforcing delay diversity first.

    The previous implementation only rejected candidates if both delay and
    Doppler were close.  That allowed many paths to pile up around the strongest
    delay with slightly different Doppler bins.  For PDP waterfall MPCs we need
    delay-diverse initialization; otherwise SAGE never gets a chance to refine
    weaker ridges away from the main path.
    """
    if not candidates:
        return []
    candidates = sorted(candidates, key=lambda c: float(c["rank_score_db"]), reverse=True)
    chosen: list[dict[str, Any]] = []
    delay_sep = max(1, int(min_delay_separation_bins))
    dop_sep = max(0, int(min_doppler_separation_bins))
    for cand in candidates:
        delay_col = int(cand["delay_col"])
        dop_idx = int(cand.get("dop_idx", -10_000))
        # Strong rule: avoid several initial paths inside the same compressed
        # pulse / local ridge.  This is the main fix for main-path crowding.
        if any(abs(delay_col - int(old["delay_col"])) <= delay_sep for old in chosen):
            continue
        # Secondary guard for exact same delay-Doppler cell if caller requested it.
        if dop_sep > 0 and any(
            abs(delay_col - int(old["delay_col"])) <= delay_sep
            and abs(dop_idx - int(old.get("dop_idx", 10_000))) <= dop_sep
            for old in chosen
        ):
            continue
        chosen.append(cand)
        if len(chosen) >= max_paths:
            break
    return chosen


def _initial_candidates_from_pdp(
    segment: np.ndarray,
    *,
    n_doppler_bins: int,
    frame_rate_hz: float,
    max_paths: int,
    min_peak_relative_db: float,
    min_delay_separation_bins: int,
    use_hann_window: bool,
) -> list[dict[str, Any]]:
    """PDP-assisted initialization.

    SAGE should not be initialized only from coherent Doppler FFT peaks for this
    dataset: the UI waterfall shows several physically meaningful PDP ridges that
    may have weaker phase coherence than the main path.  We therefore seed SAGE
    from noncoherent average PDP peaks, then estimate Doppler for each seed.
    """
    power = np.abs(segment.astype(np.complex128)) ** 2
    # Use a robust PDP statistic for initialization.  Mean PDP is easily
    # dominated by vertical interference bands / one-frame bursts in the UI
    # waterfall; median/upper-median favours ridges that persist through the
    # window, which is exactly what SAGE should refine.
    robust_power = np.median(power, axis=0)
    if segment.shape[0] >= 8:
        robust_power = 0.7 * robust_power + 0.3 * np.percentile(power, 75, axis=0)
    # tiny 3-bin smoothing only for peak ranking; fitted delays still use the raw
    # complex data.
    if robust_power.size >= 3:
        rank_power = robust_power.copy()
        rank_power[1:-1] = 0.25 * robust_power[:-2] + 0.5 * robust_power[1:-1] + 0.25 * robust_power[2:]
    else:
        rank_power = robust_power
    robust_power_db = 10.0 * np.log10(rank_power + 1e-30)
    rel_pdp_db = robust_power_db - float(np.max(robust_power_db))
    # Do not let the PDP initializer seed very weak speckles simply because the
    # public threshold is loose for FFT display.  Weak extra paths can still be
    # added by FFT candidates in hybrid mode.
    init_threshold_db = min(float(min_peak_relative_db), 15.0)
    peak_idx = _local_maxima_1d(rank_power)
    peak_idx = peak_idx[rel_pdp_db[peak_idx] >= -init_threshold_db]
    if peak_idx.size == 0:
        peak_idx = np.array([int(np.argmax(rank_power))], dtype=np.int64)

    _, fft_rel_db = _fft_spectrum(
        segment,
        n_doppler_bins=n_doppler_bins,
        use_hann_window=use_hann_window,
        use_gpu=False,
        normalize=True,
    )
    candidates: list[dict[str, Any]] = []
    for delay_col in peak_idx:
        dop_idx = int(np.argmax(fft_rel_db[:, int(delay_col)]))
        # Rank primarily by PDP visibility; add a small coherent term so stable
        # paths beat noise peaks with the same PDP height.
        rank = float(rel_pdp_db[int(delay_col)] + 0.15 * fft_rel_db[dop_idx, int(delay_col)])
        candidates.append(
            {
                "delay_col": int(delay_col),
                "dop_idx": dop_idx,
                "pdp_relative_db": float(rel_pdp_db[int(delay_col)]),
                "fft_relative_db": float(fft_rel_db[dop_idx, int(delay_col)]),
                "rank_score_db": rank,
                "source": "pdp",
            }
        )
    return _select_diverse_candidates(
        candidates,
        max_paths=max_paths,
        min_delay_separation_bins=max(max(1, int(min_delay_separation_bins)), 4),
        min_doppler_separation_bins=0,
    )


def _initial_candidates_from_fft(
    segment: np.ndarray,
    *,
    n_doppler_bins: int,
    max_paths: int,
    min_peak_relative_db: float,
    min_delay_separation_bins: int,
    min_doppler_separation_bins: int,
    use_hann_window: bool,
    use_gpu: bool,
) -> list[dict[str, Any]]:
    _, power_db = _fft_spectrum(
        segment,
        n_doppler_bins=n_doppler_bins,
        use_hann_window=use_hann_window,
        use_gpu=use_gpu,
        normalize=True,
    )
    rows, cols = np.where(power_db >= -float(min_peak_relative_db))
    candidates: list[dict[str, Any]] = []
    for dop_idx, delay_col in zip(rows.tolist(), cols.tolist()):
        candidates.append(
            {
                "delay_col": int(delay_col),
                "dop_idx": int(dop_idx),
                "pdp_relative_db": np.nan,
                "fft_relative_db": float(power_db[int(dop_idx), int(delay_col)]),
                "rank_score_db": float(power_db[int(dop_idx), int(delay_col)]),
                "source": "fft",
            }
        )
    return _select_diverse_candidates(
        candidates,
        max_paths=max_paths,
        min_delay_separation_bins=max(max(1, int(min_delay_separation_bins)), 4),
        min_doppler_separation_bins=min_doppler_separation_bins,
    )


def _build_delay_kernel(half_width_bins: int) -> np.ndarray:
    """Return a compact fallback delay response kernel for one MPC.

    Use a measured B2B pulse kernel when available. This Gaussian-tapered kernel
    is only a safe fallback that is better than a one-bin delta for uncalibrated
    quicklook runs.
    """
    half = max(0, int(half_width_bins))
    if half == 0:
        return np.ones(1, dtype=np.complex128)
    x = np.arange(-half, half + 1, dtype=np.float64)
    sigma = max(1.0, half / 2.0)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel = kernel / float(np.max(kernel))
    return kernel.astype(np.complex128)


def _prepare_delay_kernel(pulse_half_width_bins: int, pulse_kernel: np.ndarray | None) -> np.ndarray:
    if pulse_kernel is None:
        return _build_delay_kernel(pulse_half_width_bins)
    kernel = np.asarray(pulse_kernel, dtype=np.complex128).ravel()
    if kernel.size == 0:
        raise ValueError("pulse_kernel must be non-empty")
    if kernel.size % 2 == 0:
        raise ValueError("pulse_kernel length must be odd so it has a well-defined center tap")
    peak = int(np.argmax(np.abs(kernel)))
    if peak != kernel.size // 2:
        shift = kernel.size // 2 - peak
        kernel = np.roll(kernel, shift)
    ref = kernel[kernel.size // 2]
    if abs(ref) <= 1e-30:
        raise ValueError("pulse_kernel center tap is zero after peak alignment")
    return (kernel / ref).astype(np.complex128)


def _kernel_for_delay(n_delay: int, delay_col: int, kernel: np.ndarray) -> np.ndarray:
    half = kernel.size // 2
    out = np.zeros(n_delay, dtype=np.complex128)
    start = max(0, int(delay_col) - half)
    end = min(n_delay, int(delay_col) + half + 1)
    k_start = start - (int(delay_col) - half)
    k_end = k_start + (end - start)
    out[start:end] = kernel[k_start:k_end]
    return out


def _make_atom(n_slow: int, n_delay: int, frame_rate_hz: float, delay_col: int, doppler_hz: float, kernel: np.ndarray) -> np.ndarray:
    tone = _complex_tone(frame_rate_hz, doppler_hz, n_slow)
    delay_vec = _kernel_for_delay(n_delay, delay_col, kernel)
    return tone[:, None] * delay_vec[None, :]


def _fit_atom(
    residual_like: np.ndarray,
    *,
    frame_rate_hz: float,
    init_delay_col: int,
    init_doppler_hz: float,
    kernel: np.ndarray,
    delay_search_bins: int,
    doppler_search_half_span_hz: float,
    doppler_search_points: int,
) -> tuple[int, float, complex, float]:
    """Joint local LS fit of delay, Doppler, and complex amplitude."""
    n_slow, n_delay = residual_like.shape
    best_score = -np.inf
    best_delay = int(init_delay_col)
    best_fd = float(init_doppler_hz)
    best_amp = 0.0 + 0.0j
    d0 = int(init_delay_col)
    d_lo = max(0, d0 - max(0, int(delay_search_bins)))
    d_hi = min(n_delay - 1, d0 + max(0, int(delay_search_bins)))
    grid = np.linspace(
        float(init_doppler_hz) - float(doppler_search_half_span_hz),
        float(init_doppler_hz) + float(doppler_search_half_span_hz),
        int(max(3, doppler_search_points)),
    )
    for delay_col in range(d_lo, d_hi + 1):
        delay_vec = _kernel_for_delay(n_delay, delay_col, kernel)
        delay_norm = float(np.vdot(delay_vec, delay_vec).real)
        if delay_norm <= 1e-30:
            continue
        # Project residual onto the delay kernel first, then fit Doppler on the
        # resulting slow-time series.  This is algebraically equivalent to using
        # the full rank-1 atom but avoids allocating many T×D arrays.
        projected = residual_like @ np.conj(delay_vec)
        for fd in grid:
            tone = _complex_tone(frame_rate_hz, float(fd), n_slow)
            denom = max(float(np.vdot(tone, tone).real) * delay_norm, 1e-30)
            inner = np.vdot(tone, projected)
            amp = inner / denom
            score = float(abs(inner) ** 2 / denom)
            if score > best_score:
                best_score = score
                best_delay = int(delay_col)
                best_fd = float(fd)
                best_amp = complex(amp)
    return best_delay, best_fd, best_amp, best_score


def _path_reconstruction(
    n_slow: int,
    n_delay: int,
    *,
    frame_rate_hz: float,
    delay_col: int,
    doppler_hz: float,
    amplitude: complex,
    kernel: np.ndarray,
) -> np.ndarray:
    return amplitude * _make_atom(n_slow, n_delay, frame_rate_hz, delay_col, doppler_hz, kernel)


def estimate_window_paths_detailed(
    segment: np.ndarray,
    *,
    delay_bins: np.ndarray,
    bandwidth_hz: float,
    frame_rate_hz: float,
    max_paths: int,
    n_doppler_bins: int,
    max_iter: int,
    min_peak_relative_db: float,
    min_delay_separation_bins: int,
    min_doppler_separation_bins: int,
    use_hann_window: bool,
    use_gpu: bool,
    pulse_half_width_bins: int = 4,
    delay_search_bins: int = 8,
    doppler_search_half_span_hz: float = 3.0,
    doppler_search_points: int = 81,
    init_strategy: Literal["hybrid", "pdp", "fft"] = "pdp",
    pulse_kernel: np.ndarray | None = None,
) -> SageWindowEstimate:
    """Estimate delay-Doppler MPCs in one window using SAGE refinement.

    This is still single-antenna delay-Doppler SAGE (no angle dimension), but it
    fixes the old CLEAN-like behavior that collapsed paths onto the dominant
    delay.  Key changes:

    1. PDP-assisted, delay-diverse initialization so visible waterfall ridges are
       represented before iterative refinement starts.
    2. Finite delay pulse kernel instead of a one-bin delta atom.
    3. Wider local delay search during M-steps.
    4. Path power reported from the fitted amplitude only; residual floor is not
       added into every path.
    """
    if segment.ndim != 2:
        raise ValueError(f"segment must be 2D, got shape={segment.shape}")
    if max_paths <= 0:
        return SageWindowEstimate(raw_candidates=[], raw_metadata=[], pruned_candidates=[], final_paths=[])
    n_slow, n_delay = segment.shape
    if n_slow == 0 or n_delay == 0:
        return SageWindowEstimate(raw_candidates=[], raw_metadata=[], pruned_candidates=[], final_paths=[])

    doppler_axis = np.fft.fftshift(np.fft.fftfreq(int(n_doppler_bins), d=1.0 / float(frame_rate_hz)))

    pdp_candidates: list[dict[str, Any]] = []
    fft_candidates: list[dict[str, Any]] = []
    if init_strategy in ("hybrid", "pdp"):
        pdp_candidates = _initial_candidates_from_pdp(
            segment,
            n_doppler_bins=n_doppler_bins,
            frame_rate_hz=frame_rate_hz,
            max_paths=max_paths,
            min_peak_relative_db=min_peak_relative_db,
            min_delay_separation_bins=min_delay_separation_bins,
            use_hann_window=use_hann_window,
        )
    if init_strategy in ("hybrid", "fft"):
        fft_candidates = _initial_candidates_from_fft(
            segment,
            n_doppler_bins=n_doppler_bins,
            max_paths=max_paths,
            min_peak_relative_db=min_peak_relative_db,
            min_delay_separation_bins=min_delay_separation_bins,
            min_doppler_separation_bins=min_doppler_separation_bins,
            use_hann_window=use_hann_window,
            use_gpu=use_gpu,
        )

    if init_strategy == "pdp":
        chosen = pdp_candidates
    elif init_strategy == "fft":
        chosen = fft_candidates
    else:
        # PDP seeds first because they correspond to visible waterfall ridges;
        # fill remaining slots from coherent FFT candidates.
        merged = list(pdp_candidates)
        for cand in fft_candidates:
            if len(merged) >= max_paths:
                break
            if any(abs(int(cand["delay_col"]) - int(old["delay_col"])) <= max(4, min_delay_separation_bins) for old in merged):
                continue
            merged.append(cand)
        chosen = merged[:max_paths]

    if not chosen:
        return SageWindowEstimate(raw_candidates=[], raw_metadata=[], pruned_candidates=[], final_paths=[])

    kernel = _prepare_delay_kernel(pulse_half_width_bins, pulse_kernel)
    path_states: list[dict[str, Any]] = []
    s_list: list[np.ndarray] = []
    s_sum = np.zeros_like(segment, dtype=np.complex128)
    x = segment.astype(np.complex128)
    robust_delay_power = _window_delay_power(x)

    for path_id, cand in enumerate(chosen, start=1):
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

    # SAGE iterations: update one path using data plus all other current path
    # estimates as the hidden complete-data estimate for that path.
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

    # Merge/keep delay-diverse final estimates. Iterative refinement may pull two
    # seeds together; report only the stronger one in a local delay neighbourhood.
    raw_results: list[SagePathEstimate] = []
    raw_meta: list[dict[str, float | str]] = []
    strongest_power_db = -np.inf
    for state in path_states:
        delay_col = int(state["delay_col"])
        if delay_col < 0 or delay_col >= len(delay_bins):
            continue
        delay_bin = int(delay_bins[delay_col])
        amp = complex(state["amplitude"])
        # Kernel peak is 1, so |amp|² is the peak power contribution.  Do not add
        # the residual floor; that hid true dynamic range in the old code.
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

    raw_pairs = list(zip(raw_results, raw_meta, strict=False))
    raw_pairs.sort(key=lambda pair: pair[0].power_db, reverse=True)
    pruned: list[SagePathEstimate] = []
    final_sep = max(1, int(min_delay_separation_bins))
    strongest_power_db = float(strongest_power_db)
    for item, meta in raw_pairs:
        if any(abs(item.delay_col - old.delay_col) <= final_sep for old in pruned):
            continue
        rel_power_db = float(item.power_db - strongest_power_db)
        local_prominence_db = float(meta["local_prominence_db"])
        if pruned and local_prominence_db < 3.0 and rel_power_db < -12.0:
            continue
        pruned.append(item)
        if len(pruned) >= max_paths:
            break
    for idx, item in enumerate(pruned, start=1):
        item.path_id = idx
    return SageWindowEstimate(
        raw_candidates=raw_results,
        raw_metadata=raw_meta,
        pruned_candidates=pruned,
        final_paths=pruned,
    )


def estimate_window_paths(
    segment: np.ndarray,
    *,
    delay_bins: np.ndarray,
    bandwidth_hz: float,
    frame_rate_hz: float,
    max_paths: int,
    n_doppler_bins: int,
    max_iter: int,
    min_peak_relative_db: float,
    min_delay_separation_bins: int,
    min_doppler_separation_bins: int,
    use_hann_window: bool,
    use_gpu: bool,
    pulse_half_width_bins: int = 4,
    delay_search_bins: int = 8,
    doppler_search_half_span_hz: float = 3.0,
    doppler_search_points: int = 81,
    init_strategy: Literal["hybrid", "pdp", "fft"] = "pdp",
    pulse_kernel: np.ndarray | None = None,
) -> list[SagePathEstimate]:
    """Backward-compatible wrapper returning the pruned/final path list."""
    detailed = estimate_window_paths_detailed(
        segment,
        delay_bins=delay_bins,
        bandwidth_hz=bandwidth_hz,
        frame_rate_hz=frame_rate_hz,
        max_paths=max_paths,
        n_doppler_bins=n_doppler_bins,
        max_iter=max_iter,
        min_peak_relative_db=min_peak_relative_db,
        min_delay_separation_bins=min_delay_separation_bins,
        min_doppler_separation_bins=min_doppler_separation_bins,
        use_hann_window=use_hann_window,
        use_gpu=use_gpu,
        pulse_half_width_bins=pulse_half_width_bins,
        delay_search_bins=delay_search_bins,
        doppler_search_half_span_hz=doppler_search_half_span_hz,
        doppler_search_points=doppler_search_points,
        init_strategy=init_strategy,
        pulse_kernel=pulse_kernel,
    )
    return detailed.final_paths
