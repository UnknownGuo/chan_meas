"""Module B analysis: measured path loss + statistical PDFs from SAGE windows."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


EPS = 1e-30


@dataclass(frozen=True)
class ExportArtifacts:
    json_path: Path
    csv_paths: list[Path]
    png_paths: list[Path]


def _complex_amp(peak: dict[str, Any]) -> complex:
    return complex(float(peak.get("amplitudeReal", 0.0)), float(peak.get("amplitudeImag", 0.0)))


def _linear_power(peak: dict[str, Any]) -> float:
    amp = _complex_amp(peak)
    return float(abs(amp) ** 2)


SOURCE_KEYS = {"sage": "sageDelayDoppler", "music": "musicDelay"}


def _source_key(source: str) -> str:
    try:
        return SOURCE_KEYS[source]
    except KeyError:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(SOURCE_KEYS)}") from None


def _valid_windows(dataset: dict[str, Any], source: str = "sage") -> list[dict[str, Any]]:
    windows = ((dataset.get(_source_key(source)) or {}).get("windowTracks") or [])
    return [w for w in windows if (w.get("peaks") or [])]


def _nearest_distance(window: dict[str, Any], frame_stats: list[dict[str, Any]]) -> float | None:
    if not frame_stats:
        return None
    target_frame = float(window.get("frame", 0.0))
    target_time = float(window.get("timeSec", 0.0))

    best = None
    best_key = None
    for item in frame_stats:
        dval = item.get("distanceM")
        if dval is None:  # 无 TX 时 distanceM 为 None，跳过
            continue
        key = (
            abs(float(item.get("frame", target_frame)) - target_frame),
            abs(float(item.get("timeSec", target_time)) - target_time),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = float(dval)
    return best


def compute_path_loss_series(dataset: dict[str, Any], source: str = "sage") -> dict[str, Any]:
    """Path loss per SAGE window, as a non-coherent sum of MPC powers.

    Uses sum(|amplitude|^2) across a window's resolved paths, not a coherent
    complex-amplitude sum (20*log10(|sum(amplitude)|)). The coherent-sum
    definition was the original sage-ui-merge-plan.md spec, but it depends on
    SAGE's per-path phase estimate being accurate, which was never validated;
    the non-coherent sum matches PL_results_new.m / K_factor_cal.m in
    matlab_code_reference and is what was validated against this dataset.
    """
    frame_stats = dataset.get("frameStats") or []
    distances: list[float] = []
    measured_db: list[float] = []
    time_sec: list[float] = []
    window_frames: list[int] = []
    for window in _valid_windows(dataset, source):
        peaks = window.get("peaks") or []
        power_sum = sum((_linear_power(p) for p in peaks), 0.0)
        dist = _nearest_distance(window, frame_stats)
        if dist is None or not math.isfinite(dist) or dist <= 0:
            continue
        distances.append(float(dist))
        measured_db.append(float(10.0 * math.log10(power_sum + EPS)))
        time_sec.append(float(window.get("timeSec", 0.0)))
        window_frames.append(int(window.get("frame", 0)))
    return {
        "distanceM": distances,
        "measuredDb": measured_db,
        "timeSec": time_sec,
        "frame": window_frames,
    }


def fit_log_distance_curve(distance_m: list[float] | np.ndarray, measured_db: list[float] | np.ndarray) -> dict[str, Any]:
    x = np.asarray(distance_m, dtype=float)
    y = np.asarray(measured_db, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y) & (x > 0)
    x = x[mask]
    y = y[mask]
    if x.size < 2:
        raise ValueError("need at least 2 valid points for log-distance fit")
    lx = np.log10(x)
    beta1, beta0 = np.polyfit(lx, y, 1)
    y_fit = beta0 + beta1 * lx
    residual = y - y_fit
    rmse = float(np.sqrt(np.mean((residual) ** 2)))
    ss_res = float(np.sum((y - y_fit) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "model": "log_distance_linear_fit",
        "xDistanceM": x.round(6).tolist(),
        "yFitDb": y_fit.round(6).tolist(),
        "residualDb": residual.round(6).tolist(),
        "params": {
            "beta0": float(beta0),
            "beta1": float(beta1),
            "ple": float(-beta1 / 10.0),
            "rmse": rmse,
            "r2": float(r2),
        },
    }


def rms_delay_spread_ns(peaks: list[dict[str, Any]]) -> float:
    weights = np.array([_linear_power(p) for p in peaks], dtype=float)
    delays = np.array([float(p.get("delayNs", 0.0)) for p in peaks], dtype=float)
    total = float(np.sum(weights))
    if total <= 0 or delays.size == 0:
        return 0.0
    mean = float(np.sum(weights * delays) / total)
    return float(np.sqrt(np.sum(weights * (delays - mean) ** 2) / total))


def rms_doppler_spread_hz(peaks: list[dict[str, Any]]) -> float:
    weights = np.array([_linear_power(p) for p in peaks], dtype=float)
    dopplers = np.array([float(p.get("dopplerHz", 0.0)) for p in peaks], dtype=float)
    total = float(np.sum(weights))
    if total <= 0 or dopplers.size == 0:
        return 0.0
    mean = float(np.sum(weights * dopplers) / total)
    return float(np.sqrt(np.sum(weights * (dopplers - mean) ** 2) / total))


def _moving_average(values: np.ndarray, window: int = 21) -> np.ndarray:
    if values.size == 0:
        return values
    window = max(1, min(window, values.size))
    kernel = np.ones(window, dtype=float) / window
    padded = np.pad(values, (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _sample_pdf(samples: np.ndarray, model: str, x: np.ndarray, y: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "x": x.round(6).tolist(),
        "y": y.round(12).tolist(),
        "params": {k: float(v) for k, v in params.items()},
        "sampleCount": int(samples.size),
    }


def _fit_gaussian_pdf(samples: np.ndarray) -> dict[str, Any]:
    mu = float(np.mean(samples))
    sigma = float(np.std(samples, ddof=1)) if samples.size > 1 else 0.0
    sigma = max(sigma, 1e-9)
    x = np.linspace(mu - 4 * sigma, mu + 4 * sigma, 400)
    y = stats.norm.pdf(x, loc=mu, scale=sigma)
    return _sample_pdf(samples, "gaussian", x, y, {"mu": mu, "sigma": sigma})


def _fit_positive_distributions(samples: np.ndarray, models: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    s = samples[np.isfinite(samples)]
    s = s[s > 0]
    if s.size == 0:
        return {name: None for name in models}
    x = np.linspace(max(np.min(s) * 0.8, 1e-9), np.max(s) * 1.2, 400)
    for name in models:
        try:
            if name == "rayleigh":
                loc, scale = stats.rayleigh.fit(s, floc=0)
                y = stats.rayleigh.pdf(x, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"loc": loc, "scale": scale})
            elif name == "rice":
                b, loc, scale = stats.rice.fit(s, floc=0)
                y = stats.rice.pdf(x, b, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"b": b, "loc": loc, "scale": scale})
            elif name == "nakagami":
                nu, loc, scale = stats.nakagami.fit(s, floc=0)
                y = stats.nakagami.pdf(x, nu, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"nu": nu, "loc": loc, "scale": scale})
            elif name == "lognormal":
                shape, loc, scale = stats.lognorm.fit(s, floc=0)
                y = stats.lognorm.pdf(x, shape, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"shape": shape, "loc": loc, "scale": scale})
            elif name == "gamma":
                a, loc, scale = stats.gamma.fit(s, floc=0)
                y = stats.gamma.pdf(x, a, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"a": a, "loc": loc, "scale": scale})
            elif name == "weibull":
                c, loc, scale = stats.weibull_min.fit(s, floc=0)
                y = stats.weibull_min.pdf(x, c, loc=loc, scale=scale)
                out[name] = _sample_pdf(s, name, x, y, {"c": c, "loc": loc, "scale": scale})
            else:
                out[name] = None
        except Exception:
            out[name] = None
    return out


def _multipath_fading_samples(windows: list[dict[str, Any]]) -> np.ndarray:
    strongest = []
    for window in windows:
        peaks = window.get("peaks") or []
        if not peaks:
            continue
        strongest.append(max(abs(_complex_amp(p)) for p in peaks))
    s = np.asarray(strongest, dtype=float)
    if s.size == 0:
        return s
    baseline = _moving_average(s, 21)
    baseline = np.maximum(baseline, 1e-9)
    return s / baseline


def _k_factor_samples_db(windows: list[dict[str, Any]]) -> np.ndarray:
    vals = []
    for window in windows:
        powers = sorted((_linear_power(p) for p in (window.get("peaks") or [])), reverse=True)
        if len(powers) < 2:
            continue
        strongest = powers[0]
        scatter = sum(powers[1:])
        if strongest > 0 and scatter > 0:
            vals.append(10.0 * math.log10(strongest / scatter))
    return np.asarray(vals, dtype=float)


def _moment_k_from_samples(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    m2 = float(np.mean(samples ** 2))
    var = float(np.var(samples ** 2))
    if var <= 1e-12:
        return 0.0
    k = max((m2 ** 2 - var) / max(var - m2 ** 2, 1e-12), 0.0)
    return float(k)


def _extract_window_spreads(
    windows: list[dict[str, Any]], *, delay_eps_ns: float = 0.0, doppler_eps_hz: float = 0.0
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """RMS delay/Doppler spread per window, excluding windows whose computed
    spread is at or below the given epsilon. A near-zero spread there reflects
    "SAGE didn't resolve enough distinct paths" (single path, or multiple
    paths landing on the same delay/Doppler bin — including sub-bin
    floating-point noise from path estimates a tiny fraction of a bin apart)
    rather than "this window truly has no multipath dispersion", so it's
    excluded rather than plotted as a real sample. The epsilon defaults
    should be set to roughly half a delay/Doppler bin's physical resolution:
    values below that are not resolvable by the estimator and corrupt
    log-domain fits (lognormal/gamma) far more than they'd corrupt a robust
    statistic like the median.
    """
    delay = []
    doppler = []
    excluded_delay = 0
    excluded_doppler = 0
    for w in windows:
        peaks = w.get("peaks") or []
        if not peaks:
            continue
        d = rms_delay_spread_ns(peaks)
        f = rms_doppler_spread_hz(peaks)
        if d > delay_eps_ns:
            delay.append(d)
        else:
            excluded_delay += 1
        if f > doppler_eps_hz:
            doppler.append(f)
        else:
            excluded_doppler += 1
    return np.asarray(delay, dtype=float), np.asarray(doppler, dtype=float), excluded_delay, excluded_doppler


def build_module_b_payload(dataset: dict[str, Any], source: str = "sage") -> dict[str, Any]:
    source_key = _source_key(source)
    windows = _valid_windows(dataset, source)
    if not windows:
        raise ValueError(f"dataset has no non-empty {source_key}.windowTracks")
    meta = dataset.get("meta") or {}
    sage_meta = dataset.get(source_key) or {}
    doppler_available = source != "music"

    path_loss = compute_path_loss_series(dataset, source)
    # TX 距离可选：有距离才算路损/阴影拟合，否则这两项留空、其余分析照常。
    has_distance = len(path_loss["distanceM"]) >= 2
    if has_distance:
        fit = fit_log_distance_curve(path_loss["distanceM"], path_loss["measuredDb"])
        shadow_samples = np.asarray(fit["residualDb"], dtype=float)
    else:
        fit = None
        shadow_samples = np.array([], dtype=float)
    fading_samples = _multipath_fading_samples(windows)
    k_samples_db = _k_factor_samples_db(windows)

    # Half a delay/Doppler bin's physical resolution: spreads below this are
    # sub-resolution floating-point noise, not a real measurement (see
    # conversation: ~27/480 windows had RMS delay "spread" of ~1e-6 ns, which
    # blew up the lognormal fit's shape parameter to ~12).
    bandwidth_hz = float(meta.get("bandwidthHz", 0.0)) or None
    frame_rate_hz = float(meta.get("frameRateHz", 0.0)) or None
    window_size_frames = float(sage_meta.get("windowSizeFrames", 0.0)) or None
    delay_eps_ns = (1.0 / bandwidth_hz * 1e9 / 2.0) if bandwidth_hz else 0.0
    doppler_eps_hz = (frame_rate_hz / window_size_frames / 2.0) if (frame_rate_hz and window_size_frames) else 0.0
    delay_spread, doppler_spread, excluded_delay_windows, excluded_doppler_windows = _extract_window_spreads(
        windows, delay_eps_ns=delay_eps_ns, doppler_eps_hz=doppler_eps_hz
    )

    rice_fit = _fit_positive_distributions(np.power(10.0, k_samples_db / 10.0), ["rice"]) if k_samples_db.size else {"rice": None}
    k_linear = np.power(10.0, k_samples_db / 10.0) if k_samples_db.size else np.array([], dtype=float)

    payload = {
        "meta": {
            "datasetName": str(meta.get("name", "unknown")),
            "sourceBin": str(meta.get("name", "unknown")),
            "source": source,
            "dopplerAvailable": doppler_available,
            "frameRateHz": float(meta.get("frameRateHz", 0.0)),
            "bandwidthHz": float(meta.get("bandwidthHz", 0.0)),
            "windowSizeFrames": int(sage_meta.get("windowSizeFrames", 0)),
            "stepFrames": int(sage_meta.get("stepFrames", 0)),
            "nWindows": len(windows),
            "hasDistance": has_distance,
            "fitModels": {
                "fading": ["rayleigh", "rice", "nakagami"],
                "kFactor": ["moment", "rice_fit"],
                "rmsDelay": ["lognormal", "gamma", "weibull"],
                "rmsDoppler": ["lognormal", "gamma", "weibull"],
            },
        },
        "pathLoss": {
            **path_loss,
            "hasDistance": has_distance,
            "fit": ({
                "model": fit["model"],
                "xDistanceM": fit["xDistanceM"],
                "yFitDb": fit["yFitDb"],
                "params": fit["params"],
            } if fit is not None else None),
            "shadowResidualDb": (fit["residualDb"] if fit is not None else []),
        },
        "shadowFading": {
            "samplesDb": shadow_samples.round(6).tolist(),
            "pdf": (_fit_gaussian_pdf(shadow_samples) if shadow_samples.size else None),
        },
        "multipathFading": {
            "samples": fading_samples.round(6).tolist(),
            "models": _fit_positive_distributions(fading_samples, ["rayleigh", "rice", "nakagami"]),
            "defaultModel": "nakagami",
        },
        "kFactor": {
            "samplesDb": k_samples_db.round(6).tolist(),
            "pdf": _fit_gaussian_pdf(k_samples_db) if k_samples_db.size else None,
            "models": {
                "moment": {
                    "model": "moment",
                    "kLinear": _moment_k_from_samples(k_linear),
                    "sampleCount": int(k_linear.size),
                },
                "rice_fit": rice_fit.get("rice"),
            },
            "defaultModel": "moment",
        },
        "rmsDelaySpread": {
            "samplesNs": delay_spread.round(6).tolist(),
            "models": _fit_positive_distributions(delay_spread, ["lognormal", "gamma", "weibull"]),
            "defaultModel": "lognormal",
            "excludedZeroSpreadWindows": excluded_delay_windows,
        },
        "rmsDopplerSpread": {
            "samplesHz": doppler_spread.round(6).tolist(),
            "models": _fit_positive_distributions(doppler_spread, ["lognormal", "gamma", "weibull"]),
            "defaultModel": "lognormal",
            "excludedZeroSpreadWindows": excluded_doppler_windows,
        },
    }
    return payload


def _write_csv(path: Path, header: list[str], rows: list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(str(x) for x in row) + "\n")
    return path


def _plot_hist_with_pdf(samples: np.ndarray, pdf: dict[str, Any] | None, title: str, x_label: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), dpi=160)
    if samples.size:
        ax.hist(samples, bins=min(30, max(10, samples.size // 3)), density=True, alpha=0.35, color="#2474d2", label="samples")
    if pdf is not None:
        ax.plot(pdf["x"], pdf["y"], color="#d24724", linewidth=2.0, label=pdf["model"])
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel("PDF")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _plot_path_loss(distance: np.ndarray, measured: np.ndarray, fit_x: np.ndarray, fit_y: np.ndarray, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), dpi=160)
    ax.scatter(distance, measured, s=18, color="#2474d2", alpha=0.85, label="measured")
    ax.plot(fit_x, fit_y, color="#d24724", linewidth=2.0, label="fit")
    ax.set_title("Measured Path Loss from SAGE Complex-Sum")
    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Power / Path loss (dB)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def export_module_b_results(dataset_path: str | Path, out_dir: str | Path) -> ExportArtifacts:
    dataset_path = Path(dataset_path)
    out_dir = Path(out_dir)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload = build_module_b_payload(dataset)
    stem = dataset_path.stem.replace(".json", "")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{stem}_module_b.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_paths = [
        _write_csv(
            out_dir / f"{stem}_path_loss.csv",
            ["distanceM", "measuredDb", "fittedDb", "shadowResidualDb"],
            list(zip(payload["pathLoss"]["distanceM"], payload["pathLoss"]["measuredDb"], payload["pathLoss"]["fit"]["yFitDb"], payload["pathLoss"]["shadowResidualDb"], strict=False)),
        ),
        _write_csv(out_dir / f"{stem}_shadow_fading_samples.csv", ["shadowResidualDb"], [[x] for x in payload["shadowFading"]["samplesDb"]]),
        _write_csv(out_dir / f"{stem}_multipath_fading_samples.csv", ["sample"], [[x] for x in payload["multipathFading"]["samples"]]),
        _write_csv(out_dir / f"{stem}_k_factor_samples.csv", ["kFactorDb"], [[x] for x in payload["kFactor"]["samplesDb"]]),
        _write_csv(out_dir / f"{stem}_rms_delay_spread_samples.csv", ["rmsDelayNs"], [[x] for x in payload["rmsDelaySpread"]["samplesNs"]]),
        _write_csv(out_dir / f"{stem}_rms_doppler_spread_samples.csv", ["rmsDopplerHz"], [[x] for x in payload["rmsDopplerSpread"]["samplesHz"]]),
    ]

    png_paths = [
        _plot_path_loss(
            np.asarray(payload["pathLoss"]["distanceM"], dtype=float),
            np.asarray(payload["pathLoss"]["measuredDb"], dtype=float),
            np.asarray(payload["pathLoss"]["fit"]["xDistanceM"], dtype=float),
            np.asarray(payload["pathLoss"]["fit"]["yFitDb"], dtype=float),
            out_dir / f"{stem}_path_loss.png",
        ),
        _plot_hist_with_pdf(np.asarray(payload["shadowFading"]["samplesDb"], dtype=float), payload["shadowFading"]["pdf"], "Shadow Fading PDF", "Residual (dB)", out_dir / f"{stem}_shadow_fading_pdf.png"),
        _plot_hist_with_pdf(np.asarray(payload["multipathFading"]["samples"], dtype=float), payload["multipathFading"]["models"].get(payload["multipathFading"]["defaultModel"]), "Multipath Fading PDF", "Normalized amplitude", out_dir / f"{stem}_multipath_fading_pdf.png"),
        _plot_hist_with_pdf(np.asarray(payload["kFactor"]["samplesDb"], dtype=float), None, "Rice K-factor Samples", "K (dB)", out_dir / f"{stem}_k_factor_pdf.png"),
        _plot_hist_with_pdf(np.asarray(payload["rmsDelaySpread"]["samplesNs"], dtype=float), payload["rmsDelaySpread"]["models"].get(payload["rmsDelaySpread"]["defaultModel"]), "RMS Delay Spread PDF", "Delay spread (ns)", out_dir / f"{stem}_rms_delay_spread_pdf.png"),
        _plot_hist_with_pdf(np.asarray(payload["rmsDopplerSpread"]["samplesHz"], dtype=float), payload["rmsDopplerSpread"]["models"].get(payload["rmsDopplerSpread"]["defaultModel"]), "RMS Doppler Spread PDF", "Doppler spread (Hz)", out_dir / f"{stem}_rms_doppler_spread_pdf.png"),
    ]

    return ExportArtifacts(json_path=json_path, csv_paths=csv_paths, png_paths=png_paths)
