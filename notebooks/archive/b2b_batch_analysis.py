"""
B2B Batch Analysis by Frequency Group
=====================================
分组分析1400M/3600M/4900M三个频段的B2B数据，按M=2,3,5,13,15排序输出统计和绘图。

Author: 
Date:   2026-04-21
Path:   /home/guo/project/chan_meas/notebooks/archive/b2b_batch_analysis.py
"""

import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.io.bin_read import (
    _load_frames, _parse_iq, BW_HZ, U, _S_MATCHED, _N_FFT,
    FRAME_LEN, FS_HZ,
)
from src.io.b2b_extract import extract_cali_vec, diagnose_b2b_delay
from src.paths import RAW_CALI_DIR
import src.io.bin_read as _bin_read_mod
import src.io.b2b_extract as _b2b_mod

# Force CPU numpy FFT to avoid GPU OOM - faster parallel loading
def _sliding_correlate_cpu(iq: np.ndarray) -> np.ndarray:
    x = iq - iq.mean(axis=1, keepdims=True)
    ext = np.tile(x, (1, 3))
    S_f = np.fft.fft(_S_MATCHED, n=_N_FFT)
    F = np.fft.fft(ext, n=_N_FFT, axis=1) * S_f
    corr = np.fft.ifft(F, axis=1)
    return (corr[:, 2 * U - 1 : 3 * U - 1] / U).astype(np.complex64)

_bin_read_mod._sliding_correlate = _sliding_correlate_cpu
_b2b_mod._sliding_correlate = _sliding_correlate_cpu

matplotlib.rcParams['font.family'] = 'Times New Roman'
matplotlib.rcParams['font.size'] = 12

print(f"Project root : {PROJECT_ROOT}")
print(f"FRAME_LEN={FRAME_LEN}, U={U}, FS_HZ={FS_HZ/1e6:.0f} MHz, BW={BW_HZ/1e6:.0f} MHz")
print("_sliding_correlate → CPU/numpy (patched for parallel loading)\n")

# =============================================================================
# 2  Select B2B files and group by frequency
# =============================================================================

b2b_files = sorted(RAW_CALI_DIR.rglob("*.bin"))
print(f"RAW_CALI_DIR = {RAW_CALI_DIR}")
print(f"exists       = {RAW_CALI_DIR.exists()}")
print()
print(f"B2B .bin files ({len(b2b_files)} found):")
for i, f in enumerate(b2b_files):
    size_mb = f.stat().st_size / 1e6
    rel = f.relative_to(RAW_CALI_DIR)
    print(f"[{i}] {rel}  ({size_mb:.1f} MB)")
print()

# Grouping as required:
# group 1400M: indices 0,3,6,9,13 → M = 13, 2, 3, 5, 15 → sorted by M=2,3,5,13,15
# group 3600M: indices 1,4,7,10,14 → M = 13, 2, 3, 5, 15
# group 4900M: indices 2,5,8,11,15 → M = 13, 2, 3, 5, 15

groups = {
    1400: [b2b_files[i] for i in [0, 3, 6, 9, 13]],
    3600: [b2b_files[i] for i in [1, 4, 7, 10, 14]],
    4900: [b2b_files[i] for i in [2, 5, 8, 11, 15]],
}

# M values in order: 2, 3, 5, 13, 15
m_order = [2, 3, 5, 13, 15]

# Reorder each group according to m_order to match M values
# Because:
#  index 0,3,6,9,13 → M = 13(M13), 2(M2), 3(M3), 5(M5), 15(M=15)
#  need reorder to [2,3,5,13,15]
for freq_mhz in groups:
    files = groups[freq_mhz]
    # original order: [M13, M2, M3, M5, M15] → reorder to M 2,3,5,13,15
    groups[freq_mhz] = [files[1], files[2], files[3], files[0], files[4]]

print("Grouping done:")
for freq_mhz, files in groups.items():
    print(f"  {freq_mhz} MHz: {len(files)} files, ordered by M = {m_order}")
    for f, m in zip(files, m_order):
        rel = f.relative_to(RAW_CALI_DIR)
        print(f"    M={m}: {rel.name}")
print()

# =============================================================================
# Precompute: delay axis
# =============================================================================

delay_ns = np.arange(U) / BW_HZ * 1e9

# =============================================================================
# Batch processing
# =============================================================================

results = []
num = 100  # which PDP to plot (user can change this)

print("=" * 80)
print("Batch processing started\n")

for freq_mhz, files in groups.items():
    print(f"\n>>> Processing {freq_mhz} MHz band")
    print("-" * 60)
    
    freq_results = []
    
    for m_val, b2b_path in zip(m_order, files):
        print(f"\n  M={m_val:2d} : {b2b_path.name}")
        
        # Load data - GPU acceleration enabled via CPU numpy (faster batch)
        frames = _load_frames(b2b_path)
        iq = _parse_iq(frames)
        del frames
        cir_b2b = _sliding_correlate_cpu(iq)
        del iq
        n_frames = cir_b2b.shape[0]
        
        # Diagnostics
        diag = diagnose_b2b_delay(cir_b2b)
        
        # Per-frame peak delay statistics
        peak_bins_per_frame = np.argmax(np.abs(cir_b2b), axis=1)
        peak_delay_per_frame_ns = peak_bins_per_frame * (1e9 / BW_HZ)
        
        delay_min_ns  = peak_delay_per_frame_ns.min()
        delay_max_ns  = peak_delay_per_frame_ns.max()
        delay_span_ns = delay_max_ns - delay_min_ns
        
        # Print statistics in one line
        print(f"    {n_frames:5d} frames | "
              f"Min: {delay_min_ns:5.1f} ns | "
              f"Max: {delay_max_ns:5.1f} ns | "
              f"Span: {delay_span_ns:5.1f} ns")
        
        # CFO estimation (keep data for summary, skip plotting)
        peak_bins_per_frame_cfo  = np.argmax(np.abs(cir_b2b), axis=1)
        frame_indices        = np.arange(n_frames)
        cir_at_dynamic_peak  = cir_b2b[frame_indices, peak_bins_per_frame_cfo]
        phase_at_peak         = np.angle(cir_at_dynamic_peak)
        phase_unwrapped       = np.unwrap(phase_at_peak)
        phase_drift_per_frame = np.diff(phase_unwrapped)
        
        # Outlier removal (MAD-based)
        median_drift = np.median(phase_drift_per_frame)
        mad          = np.median(np.abs(phase_drift_per_frame - median_drift))
        outlier_mask = np.abs(phase_drift_per_frame - median_drift) > 5 * mad
        drift_clean               = phase_drift_per_frame.copy()
        drift_clean[outlier_mask] = median_drift
        n_outliers = int(outlier_mask.sum())
        
        # CFO estimate
        T_frame_s      = FRAME_LEN / FS_HZ
        mean_drift_rad = drift_clean.mean()
        cfo_est_hz     = mean_drift_rad / (2 * np.pi * T_frame_s)
        
        freq_results.append({
            'm_val': m_val,
            'b2b_path': b2b_path,
            'n_frames': n_frames,
            'cir_b2b': cir_b2b,
            'diag': diag,
            'delay_min_ns': delay_min_ns,
            'delay_max_ns': delay_max_ns,
            'delay_span_ns': delay_span_ns,
            'cfo_est_hz': cfo_est_hz,
            'n_outliers': n_outliers,
            'drift_clean': drift_clean,
        })
        
    results.append({
        'freq_mhz': freq_mhz,
        'results': freq_results,
    })

print("\n" + "=" * 80)
print("\nPer-frame peak delay statistics summary:\n")
print(f"{'Frequency':>10} {'M':>3} {'Frames':>8} {'Min (ns)':>10} {'Max (ns)':>10} {'Span (ns)':>10} {'CFO (Hz)':>10}")
print("-" * 70)
for group in results:
    freq = group['freq_mhz']
    for res in group['results']:
        print(f"{freq:>10} {res['m_val']:>3} {res['n_frames']:>8} "
              f"{res['delay_min_ns']:>10.1f} {res['delay_max_ns']:>10.1f} "
              f"{res['delay_span_ns']:>10.1f} {res['cfo_est_hz']:>10.1f}")
print()

# =============================================================================
# Plot 1: Mean PDP for all M (1 figure, 5 subplots) - peak above noise for num-th PDP
# =============================================================================

print("\nGenerating Mean PDP plot (all M on one figure, 5 subplots)...")

fig, axes = plt.subplots(5, 1, figsize=(10, 4 * 5), sharex=True)
delay_ns_full = np.arange(U) / BW_HZ * 1e9

for ax, group_res, m_val in zip(axes, results[0]['results'], m_order):
    cir_b2b = group_res['cir_b2b']
    diag = group_res['diag']
    
    # Get the num-th PDP (as requested)
    pdp = np.abs(cir_b2b[num]) ** 2
    pdp_db = 10 * np.log10(pdp + 1e-30)
    pdp_db -= pdp_db.max()
    
    ax.plot(delay_ns_full, pdp_db)
    ax.axvline(diag['peak_delay_ns'], color='r', ls='--', lw=1,
               label=f"peak @ {diag['peak_delay_ns']:.0f} ns  ({diag['peak_power_db']:.1f} dB above noise)")
    ax.set_ylabel('Normalised PDP (dB)')
    ax.set_title(f'M = {m_val}, {freq} MHz, Frame #{num}', fontsize=11)
    ax.set_ylim([-60, 3])
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.4)

axes[-1].set_xlabel('Delay (ns)')
fig.tight_layout()
plt.show()

# =============================================================================
# Plot 2: Waterfall plots - 5 subplots
# =============================================================================

print("\nGenerating Waterfall plots (5 subplots)...")

fig, axes = plt.subplots(5, 1, figsize=(12, 5 * 5), sharex=True)

for ax, group_res, m_val in zip(axes, results[0]['results'], m_order):
    cir_b2b = group_res['cir_b2b']
    n_frames = group_res['n_frames']
    
    cir_pwr_db = 10 * np.log10(np.abs(cir_b2b) ** 2 + 1e-30)
    vmax = cir_pwr_db.max()
    
    im = ax.imshow(
        cir_pwr_db,
        aspect='auto', origin='lower', cmap='viridis',
        vmin=vmax - 40, vmax=vmax,
        extent=[delay_ns_full[0], delay_ns_full[-1], 0, n_frames],
    )
    fig.colorbar(im, ax=ax, label='Power (dB)')
    ax.set_ylabel('Frame index')
    ax.set_title(f'B2B CIR Waterfall - M = {m_val}', fontsize=11)
    ax.set_xlim(0, 5000)
    ax.grid(True, alpha=0.4)

axes[-1].set_xlabel('Delay (ns)')
fig.tight_layout()
plt.show()

# =============================================================================
# Plot 3: CFO estimation - skip time series, only keep statistics in summary
# CFO statistics already printed above
# =============================================================================

print("\nDone! All plots generated.")
print(f"\nSummary:")
print(f"  - 1× Mean PDP figure (5 subplots for M=2,3,5,13,15)")
print(f"  - 1× Waterfall figure (5 subplots for M=2,3,5,13,15)")
print(f"  - CFO estimates printed in statistics table above (frame-to-frame plot skipped as requested)")
