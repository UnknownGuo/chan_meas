from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io.bin_read import BW_HZ, FRAME_RATE_HZ, _load_frames, _parse_iq, _sliding_correlate
from src.signal.delay_doppler_sage import _complex_tone, _fft_spectrum, _fit_path

RX_PATH = Path("/mnt/win_data/data_mea/0121campus_test/0121mea/接收数据帧_20260121115358435.bin")
OUT_DIR = Path("/mnt/win_data/data_mea/0121campus_test/sage_quicklook_420mhz_lastgroup_first_second/adaptive_window_test")
WINDOWS = [20, 50, 100]
MAX_DELAY_BINS = 300
MAX_PATHS = 32
N_DOPPLER_BINS = 256
MAX_REFINE_ITER = 5
STOP_IMPROVEMENT_DB = 0.08
STOP_RELATIVE_INIT_SCORE_DB = -28.0
MIN_DELAY_SEPARATION_BINS = 1
MIN_DOPPLER_SEPARATION_HZ = 0.35


def metric(segment: np.ndarray, recon: np.ndarray, initial_sse: float) -> dict[str, float]:
    residual = segment - recon
    sse = float(np.sum(np.abs(residual) ** 2))
    return {
        "sse": sse,
        "residualReductionDb": float(10.0 * np.log10(max(initial_sse, 1e-30) / max(sse, 1e-30))),
        "normalizedSse": float(sse / max(initial_sse, 1e-30)),
    }


def choose_residual_peak(
    residual: np.ndarray,
    existing: list[dict[str, Any]],
    *,
    n_doppler_bins: int,
) -> tuple[float, int, int, float] | None:
    _, power_db = _fft_spectrum(residual, n_doppler_bins=n_doppler_bins, use_hann_window=True, use_gpu=False)
    doppler_axis = np.fft.fftshift(np.fft.fftfreq(n_doppler_bins, d=1.0 / float(FRAME_RATE_HZ)))
    order = np.argsort(power_db.ravel())[::-1]
    for flat in order:
        dop_idx, delay_col = np.unravel_index(int(flat), power_db.shape)
        score_db = float(power_db[dop_idx, delay_col])
        if score_db < STOP_RELATIVE_INIT_SCORE_DB:
            return None
        fd = float(doppler_axis[dop_idx])
        too_close = False
        for st in existing:
            if abs(int(st["delay_col"]) - int(delay_col)) <= MIN_DELAY_SEPARATION_BINS and abs(float(st["doppler_hz"]) - fd) <= MIN_DOPPLER_SEPARATION_HZ:
                too_close = True
                break
        if too_close:
            continue
        return score_db, int(dop_idx), int(delay_col), fd
    return None


def path_reconstruction(n_slow: int, n_delay: int, delay_col: int, doppler_hz: float, amp: complex) -> np.ndarray:
    s = np.zeros((n_slow, n_delay), dtype=np.complex128)
    s[:, delay_col] = amp * _complex_tone(FRAME_RATE_HZ, doppler_hz, n_slow)
    return s


def adaptive_sage(segment: np.ndarray, delay_bins: np.ndarray) -> dict[str, Any]:
    n_slow, n_delay = segment.shape
    initial_sse = float(np.sum(np.abs(segment) ** 2))
    s_sum = np.zeros_like(segment, dtype=np.complex128)
    s_list: list[np.ndarray] = []
    states: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = [{"step": 0, "phase": "empty", "paths": 0, **metric(segment, s_sum, initial_sse)}]

    # Greedy birth: add one residual peak at a time; stop if improvement is too small.
    for birth_idx in range(1, MAX_PATHS + 1):
        residual = segment.astype(np.complex128) - s_sum
        peak = choose_residual_peak(residual, states, n_doppler_bins=N_DOPPLER_BINS)
        if peak is None:
            history.append({"step": len(history), "phase": "stop_no_peak", "paths": len(states), **metric(segment, s_sum, initial_sse)})
            break
        score_db, _, delay_col, fd0 = peak
        fd, amp, _ = _fit_path(residual[:, delay_col], frame_rate_hz=FRAME_RATE_HZ, init_doppler_hz=fd0, search_half_span_hz=2.0, search_points=81)
        candidate = path_reconstruction(n_slow, n_delay, delay_col, fd, amp)
        before = metric(segment, s_sum, initial_sse)["residualReductionDb"]
        after = metric(segment, s_sum + candidate, initial_sse)["residualReductionDb"]
        improvement = after - before
        if improvement < STOP_IMPROVEMENT_DB:
            history.append({
                "step": len(history),
                "phase": "stop_low_improvement",
                "paths": len(states),
                "candidateScoreDb": score_db,
                "candidateImprovementDb": improvement,
                **metric(segment, s_sum, initial_sse),
            })
            break
        states.append({"delay_col": int(delay_col), "doppler_hz": float(fd), "amplitude": complex(amp), "init_score_db": float(score_db)})
        s_list.append(candidate)
        s_sum = s_sum + candidate
        history.append({
            "step": len(history),
            "phase": f"birth_{birth_idx}",
            "paths": len(states),
            "candidateScoreDb": score_db,
            "candidateImprovementDb": improvement,
            **metric(segment, s_sum, initial_sse),
        })

    # SAGE-style local refinement over accepted paths.
    for it in range(1, MAX_REFINE_ITER + 1):
        if not states:
            break
        start_reduction = metric(segment, s_sum, initial_sse)["residualReductionDb"]
        for idx, st in enumerate(states):
            x_l = segment.astype(np.complex128) - (s_sum - s_list[idx])
            old_delay = int(st["delay_col"])
            best: tuple[float, int, float, complex] | None = None
            for delay_col in range(max(0, old_delay - 1), min(n_delay, old_delay + 2)):
                fd, amp, score = _fit_path(
                    x_l[:, delay_col],
                    frame_rate_hz=FRAME_RATE_HZ,
                    init_doppler_hz=float(st["doppler_hz"]),
                    search_half_span_hz=1.0,
                    search_points=61,
                )
                if best is None or float(score) > best[0]:
                    best = (float(score), int(delay_col), float(fd), complex(amp))
            if best is None:
                continue
            _, new_delay, new_fd, new_amp = best
            new_s = path_reconstruction(n_slow, n_delay, new_delay, new_fd, new_amp)
            s_sum = s_sum - s_list[idx] + new_s
            s_list[idx] = new_s
            st["delay_col"] = int(new_delay)
            st["doppler_hz"] = float(new_fd)
            st["amplitude"] = complex(new_amp)
        end_reduction = metric(segment, s_sum, initial_sse)["residualReductionDb"]
        history.append({
            "step": len(history),
            "phase": f"refine_{it}",
            "paths": len(states),
            "iterationImprovementDb": float(end_reduction - start_reduction),
            **metric(segment, s_sum, initial_sse),
        })
        if abs(end_reduction - start_reduction) < 0.01:
            break

    residual = segment.astype(np.complex128) - s_sum
    residual_floor = float(np.mean(np.abs(residual) ** 2) + 1e-30)
    peaks = []
    for i, st in enumerate(states, start=1):
        delay_col = int(st["delay_col"])
        delay_bin = int(delay_bins[delay_col])
        amp = complex(st["amplitude"])
        peaks.append({
            "pathId": i,
            "delayCol": delay_col,
            "delayBin": delay_bin,
            "delayNs": float(delay_bin / float(BW_HZ) * 1e9),
            "dopplerHz": float(st["doppler_hz"]),
            "amplitudeReal": float(amp.real),
            "amplitudeImag": float(amp.imag),
            "powerDb": float(10.0 * np.log10(abs(amp) ** 2 + residual_floor)),
            "initScoreDb": float(st.get("init_score_db", np.nan)),
        })
    peaks.sort(key=lambda x: x["powerDb"], reverse=True)
    for i, p in enumerate(peaks, start=1):
        p["pathId"] = i
    return {"reconstruction": s_sum, "history": history, "peaks": peaks, "final": metric(segment, s_sum, initial_sse)}


def compute_fft_map(segment: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, power_db = _fft_spectrum(segment, n_doppler_bins=N_DOPPLER_BINS, use_hann_window=True, use_gpu=False)
    doppler_axis = np.fft.fftshift(np.fft.fftfreq(N_DOPPLER_BINS, d=1.0 / float(FRAME_RATE_HZ)))
    return power_db, doppler_axis, np.arange(segment.shape[1], dtype=np.int64)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    max_n = max(WINDOWS)
    frames = _load_frames(RX_PATH, max_frames=max_n)
    iq = _parse_iq(frames)
    cir = _sliding_correlate(iq)
    delay_bins = np.arange(0, min(MAX_DELAY_BINS, cir.shape[1]), dtype=np.int64)
    delay_ns = delay_bins.astype(np.float64) / float(BW_HZ) * 1e9

    results = []
    for win in WINDOWS:
        segment = cir[:win, :][:, delay_bins].astype(np.complex128)
        res = adaptive_sage(segment, delay_bins)
        recon = np.asarray(res["reconstruction"])
        raw_avg = np.mean(np.abs(segment) ** 2, axis=0)
        rec_avg = np.mean(np.abs(recon) ** 2, axis=0)
        residual_avg = np.mean(np.abs(segment - recon) ** 2, axis=0)
        ref = float(np.max(raw_avg) + 1e-30)
        raw_db = 10.0 * np.log10(raw_avg / ref + 1e-30)
        rec_db = 10.0 * np.log10(rec_avg / ref + 1e-30)
        residual_db = 10.0 * np.log10(residual_avg / ref + 1e-30)
        power_map_db, doppler_axis, _ = compute_fft_map(segment)
        np.savetxt(
            OUT_DIR / f"avg_pdp_{win}frames.csv",
            np.column_stack([delay_bins, delay_ns, raw_db, rec_db, residual_db]),
            delimiter=",",
            header="delay_bin,delay_ns,raw_avg_db_ref_raw_peak,reconstructed_avg_db_ref_raw_peak,residual_avg_db_ref_raw_peak",
            comments="",
        )
        results.append({
            "windowFrames": win,
            "windowSec": float(win / FRAME_RATE_HZ),
            "numPaths": int(len(res["peaks"])),
            "finalResidualReductionDb": float(res["final"]["residualReductionDb"]),
            "finalNormalizedSse": float(res["final"]["normalizedSse"]),
            "rawPeakDelayNs": float(delay_ns[int(np.argmax(raw_avg))]),
            "reconPeakDelayNs": float(delay_ns[int(np.argmax(rec_avg))]) if np.max(rec_avg) > 0 else None,
            "rawDb": raw_db.tolist(),
            "recDb": rec_db.tolist(),
            "residualDb": residual_db.tolist(),
            "history": res["history"],
            "peaks": res["peaks"],
            "powerMapDb": power_map_db.tolist(),
            "dopplerHz": doppler_axis.tolist(),
        })

    # Summary plot: convergence and metrics.
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.8))
    for r in results:
        steps = [h["step"] for h in r["history"]]
        red = [h["residualReductionDb"] for h in r["history"]]
        axs[0].plot(steps, red, marker="o", ms=3, lw=1.3, label=f"{r['windowFrames']} frames ({r['windowSec']:.1f}s), {r['numPaths']} paths")
    axs[0].set_title("Adaptive SAGE convergence")
    axs[0].set_xlabel("Update / refinement step")
    axs[0].set_ylabel("Residual reduction (dB)")
    axs[0].grid(alpha=0.25)
    axs[0].legend(fontsize=8)
    x = np.arange(len(results))
    red = [r["finalResidualReductionDb"] for r in results]
    paths = [r["numPaths"] for r in results]
    labels = [f"{r['windowFrames']}f" for r in results]
    axs[1].bar(x - 0.18, red, width=0.36, color="#1f77b4", label="Residual reduction (dB)")
    ax2 = axs[1].twinx()
    ax2.bar(x + 0.18, paths, width=0.36, color="#d62728", alpha=0.75, label="Accepted paths")
    axs[1].set_xticks(x, labels)
    axs[1].set_title("Window-length comparison")
    axs[1].set_ylabel("Residual reduction (dB)")
    ax2.set_ylabel("Accepted path count")
    axs[1].grid(axis="y", alpha=0.25)
    lines, labs = axs[1].get_legend_handles_labels()
    lines2, labs2 = ax2.get_legend_handles_labels()
    axs[1].legend(lines + lines2, labs + labs2, loc="upper left", fontsize=8)
    fig.tight_layout()
    summary_png = OUT_DIR / "01_adaptive_sage_window_summary.png"
    fig.savefig(summary_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # PDP comparison plot for each window.
    fig, axs = plt.subplots(len(results), 2, figsize=(12.5, 3.5 * len(results)), sharex="col")
    if len(results) == 1:
        axs = np.asarray([axs])
    for row, r in enumerate(results):
        raw_db = np.asarray(r["rawDb"])
        rec_db = np.maximum(np.asarray(r["recDb"]), -95.0)
        resid_db = np.asarray(r["residualDb"])
        ax = axs[row, 0]
        ax.plot(delay_ns, raw_db, color="#1f77b4", lw=1.4, label="Raw avg PDP")
        ax.plot(delay_ns, rec_db, color="#d62728", lw=1.2, label="Adaptive SAGE recon")
        ax.plot(delay_ns, resid_db, color="#9467bd", lw=0.9, alpha=0.8, label="Residual PDP")
        ax.set_title(f"{r['windowFrames']} frames ({r['windowSec']:.1f}s): full 0–6000 ns")
        ax.set_ylim(-95, 5)
        ax.set_ylabel("Power (dB)")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, loc="lower right")
        ax = axs[row, 1]
        mask = (delay_ns >= 2200) & (delay_ns <= 2850)
        ax.plot(delay_ns[mask], raw_db[mask], color="#1f77b4", lw=1.7, marker=".", ms=3, label="Raw")
        ax.plot(delay_ns[mask], rec_db[mask], color="#d62728", lw=1.5, marker="o", ms=2.5, label="Recon")
        ax.plot(delay_ns[mask], resid_db[mask], color="#9467bd", lw=1.0, alpha=0.85, label="Residual")
        for p in r["peaks"][:12]:
            if 2200 <= p["delayNs"] <= 2850:
                ax.axvline(p["delayNs"], color="#d62728", alpha=0.12, lw=0.7)
        ax.set_title(f"Zoom dominant region; paths={r['numPaths']}, Δ={r['finalResidualReductionDb']:.2f} dB")
        ax.set_ylim(-45, 5)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, loc="lower right")
    axs[-1, 0].set_xlabel("Delay (ns)")
    axs[-1, 1].set_xlabel("Delay (ns)")
    fig.tight_layout()
    pdp_png = OUT_DIR / "02_adaptive_sage_avg_pdp_windows.png"
    fig.savefig(pdp_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # Delay-Doppler maps.
    fig, axs = plt.subplots(1, len(results), figsize=(5.2 * len(results), 4.6), sharey=True)
    if len(results) == 1:
        axs = np.asarray([axs])
    im = None
    for ax, r in zip(axs, results):
        pm = np.asarray(r["powerMapDb"])
        doppler = np.asarray(r["dopplerHz"])
        im = ax.imshow(
            pm,
            origin="lower",
            aspect="auto",
            extent=(float(delay_ns[0]), float(delay_ns[-1]), float(doppler[0]), float(doppler[-1])),
            cmap="turbo",
            vmin=-42,
            vmax=0,
        )
        for p in r["peaks"][:12]:
            ax.scatter([p["delayNs"]], [p["dopplerHz"]], c="white", edgecolors="black", s=24, linewidths=0.6)
        ax.set_title(f"{r['windowFrames']} frames, paths={r['numPaths']}")
        ax.set_xlabel("Delay (ns)")
        ax.grid(alpha=0.12)
    axs[0].set_ylabel("Doppler (Hz)")
    if im is not None:
        cbar = fig.colorbar(im, ax=axs.ravel().tolist(), shrink=0.85)
        cbar.set_label("Relative amplitude (dB)")
    dd_png = OUT_DIR / "03_adaptive_sage_delay_doppler_windows.png"
    fig.savefig(dd_png, dpi=180, bbox_inches="tight")
    plt.close(fig)

    compact = []
    for r in results:
        compact.append({k: r[k] for k in ["windowFrames", "windowSec", "numPaths", "finalResidualReductionDb", "finalNormalizedSse", "rawPeakDelayNs", "reconPeakDelayNs"]})
        compact[-1]["topPeaks"] = r["peaks"][:8]
    summary = {
        "rxPath": str(RX_PATH),
        "bandwidthHz": float(BW_HZ),
        "frameRateHz": float(FRAME_RATE_HZ),
        "delayGateBins": [int(delay_bins[0]), int(delay_bins[-1])],
        "delayGateNs": [float(delay_ns[0]), float(delay_ns[-1])],
        "adaptiveSettings": {
            "maxPaths": MAX_PATHS,
            "stopImprovementDb": STOP_IMPROVEMENT_DB,
            "stopRelativeInitScoreDb": STOP_RELATIVE_INIT_SCORE_DB,
            "minDelaySeparationBins": MIN_DELAY_SEPARATION_BINS,
            "minDopplerSeparationHz": MIN_DOPPLER_SEPARATION_HZ,
            "maxRefineIter": MAX_REFINE_ITER,
        },
        "results": compact,
        "outputs": {
            "summaryPlot": str(summary_png),
            "pdpPlot": str(pdp_png),
            "delayDopplerPlot": str(dd_png),
        },
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
