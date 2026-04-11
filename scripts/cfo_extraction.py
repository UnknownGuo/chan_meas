"""
幅度法粗估真实 CFO

规范文档: docs/specs/幅度法粗估真实CFO.md

数据说明:
  每个 .bin 文件对应一个 M 值，FPGA 内已完成 M 帧滑动平均，
  输出的每帧 IQ 就是 M 个 ZC 平均后的结果。
  文件格式: 标准 4132 B/帧 = 32 B 帧头 + 1024×4 B IQ

流程:
  1. bin_read.read_bin_to_cir() → CIR (n_frames, 1024)
  2. 非相干 PDP → 主径功率 P_bar[M]
  3. 6 组功率比 → 网格搜索 Δφ → 真实 CFO
  4. 生成 7 张 PNG
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_SCRIPT_DIR   = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.io.bin_read import read_bin_to_cir   # CIR 加载

# ---------------------------------------------------------------------------
# 物理常数
# ---------------------------------------------------------------------------
BW_HZ          = 50e6            # 信号带宽
U              = 1024            # ZC 序列长度 / CIR bin 数
T_ZC           = U / BW_HZ      # 20.48e-6 s
T_FRAME        = 10e-3           # 帧周期 10 ms
M_LIST         = [2, 3, 5, 13]
FRAME_ANALYSIS = 1000            # 单帧 PDP 分析用的帧号

FC_HZ = {'1400M': 1.4e9, '3600M': 3.6e9, '4900M': 4.9e9}

DATA_ROOT  = Path('/mnt/win_data/data_mea/data_save/Cali_data/20260402_cfo_mea')
OUTPUT_DIR = _PROJECT_ROOT / 'outputs'

BAND_M_FILES: dict[str, dict[int, str]] = {
    '1400M': {
        2:  'CFO_B2B_20260407_M2_Black01_081cable_1400M.bin',
        3:  'CFO_B2B_20260407_M3_Black01_081cable_1400M.bin',
        5:  'CFO_B2B_20260407_M5_Black01_081cable_1400M.bin',
        13: 'CFO_B2B_20260407_M13_Black01_081cable_1400M.bin',
    },
    '3600M': {
        2:  'CFO_B2B_20260407_M2_Black01_081cable_3600M.bin',
        3:  'CFO_B2B_20260407_M3_Black01_081cable_3600M.bin',
        5:  'CFO_B2B_20260407_M5_Black01_081cable_3600M.bin',
        13: 'CFO_B2B_20260407_M13_Black01_081cable_3600M.bin',
    },
    '4900M': {
        2:  'CFO_B2B_20260407_M2_Black01_081cable_4900M.bin',
        3:  'CFO_B2B_20260407_M3_Black01_081cable_4900M.bin',
        5:  'CFO_B2B_20260407_M5_Black01_081cable_4900M.bin',
        13: 'CFO_B2B_20260407_M13_Black01_081cable_4900M.bin',
    },
}

_COLOR = {2: 'steelblue', 3: 'forestgreen', 5: 'tomato', 13: 'darkorange'}

# ---------------------------------------------------------------------------
# 功率提取  →  §2 步骤2-5
# ---------------------------------------------------------------------------

def find_peak_bin(cir: np.ndarray) -> int:
    """平均 PDP 中功率最大的 bin → 主径位置。"""
    pdp = (np.abs(cir) ** 2).mean(axis=0)   # (1024,)
    return int(np.argmax(pdp))


def extract_peak_power(cir: np.ndarray) -> tuple[float, int]:
    """
    主径功率（线性）和主径 bin。

    Returns
    -------
    P_bar   : float  — 主径 bin 的平均功率（扣除噪底）
    peak_bin: int
    """
    pdp         = (np.abs(cir) ** 2).mean(axis=0)      # (1024,)
    peak_bin    = int(np.argmax(pdp))
    noise_floor = float(np.percentile(pdp, 10))
    P_bar       = float(pdp[peak_bin]) - noise_floor
    return P_bar, peak_bin

# ---------------------------------------------------------------------------
# CFO 估计  →  §1.1, §2 步骤2, §3, §4
# ---------------------------------------------------------------------------

def _g_sq(M: int | np.ndarray, dphi: np.ndarray) -> np.ndarray:
    """
    幅度保留因子平方 g²(M, Δφ)。  §1.1

    g(M, Δφ) = sin(M·Δφ/2) / (M·sin(Δφ/2))

    用 np.sinc 等价形式避免 Δφ→0 奇异：
      g = sinc(M·Δφ/(2π)) / sinc(Δφ/(2π))
    """
    return (np.sinc(M * dphi / (2 * np.pi)) / np.sinc(dphi / (2 * np.pi))) ** 2


def estimate_cfo_amplitude(P_bar: dict[int, float]) -> dict:
    """
    幅度法：6 组功率比 → 网格搜索 → 真实 Δφ → f_CFO。  §2步骤2 + §3 + §4

    Parameters
    ----------
    P_bar : {M: mean_power_linear}

    Returns
    -------
    dict: f_cfo_hz, dphi_hat, residual, rho_meas, rho_fit
    """
    if any(p <= 0 or np.isnan(p) for p in P_bar.values()):
        nan = float('nan')
        return {'f_cfo_hz': nan, 'dphi_hat': nan, 'residual': nan,
                'rho_meas': {}, 'rho_fit': {}}

    pairs    = [(2, 3), (2, 5), (2, 13), (3, 5), (3, 13), (5, 13)]
    rho_meas = {(mi, mj): P_bar[mj] / P_bar[mi] for mi, mj in pairs}

    dphi_grid = np.linspace(1e-6, np.pi - 1e-6, 10_000)
    loss = np.zeros_like(dphi_grid)
    for mi, mj in pairs:
        rho_theory = _g_sq(mj, dphi_grid) / _g_sq(mi, dphi_grid)
        loss += (rho_theory - rho_meas[(mi, mj)]) ** 2

    best     = int(np.argmin(loss))
    dphi_hat = float(dphi_grid[best])
    f_cfo_hz = dphi_hat / (2 * np.pi * T_ZC)   # §4

    rho_fit = {
        (mi, mj): float(_g_sq(mj, dphi_hat) / _g_sq(mi, dphi_hat))
        for mi, mj in pairs
    }
    return {
        'f_cfo_hz': f_cfo_hz,
        'dphi_hat': dphi_hat,
        'residual': float(loss[best]),
        'rho_meas': rho_meas,
        'rho_fit':  rho_fit,
    }


def estimate_residual_cfo(cir: np.ndarray) -> np.ndarray:
    """
    相邻帧相位差法 → 余数 CFO 时序（不模糊范围 ±50 Hz）。  §7.1

    Returns
    -------
    cfo_hz : (n_frames-1,) float64
    """
    peak_bin = find_peak_bin(cir)
    peak     = cir[:, peak_bin]
    cross    = peak[1:] * np.conj(peak[:-1])
    return (np.angle(cross) / (2 * np.pi * T_FRAME)).astype(np.float64)

# ---------------------------------------------------------------------------
# 绘图  →  §7
# ---------------------------------------------------------------------------

def plot_cfo_timeseries(
    cfo_ts: dict[str, dict[int, np.ndarray]],
    output_path: Path,
) -> None:
    """PNG 1: 3行×4列 余数CFO时序。  §7.1"""
    bands = [b for b in ['1400M', '3600M', '4900M'] if b in cfo_ts]
    fig, axes = plt.subplots(len(bands), len(M_LIST),
                             figsize=(4 * len(M_LIST), 3.5 * len(bands)),
                             squeeze=False)
    fig.suptitle('Residual CFO time series  (adjacent-frame phase, ±50 Hz range)',
                 fontsize=13)

    for row, band in enumerate(bands):
        for col, M in enumerate(M_LIST):
            ax = axes[row][col]
            if M not in cfo_ts[band]:
                ax.set_visible(False)
                continue
            cfo_hz = cfo_ts[band][M]
            ax.plot(np.arange(len(cfo_hz)), cfo_hz,
                    linewidth=0.5, color=_COLOR[M])
            ax.axhline(0, color='r', linestyle='--', alpha=0.5, linewidth=0.8)
            ax.set_title(f'{band}  M={M}', fontsize=11)
            ax.set_ylim(-60, 60)
            if row == len(bands) - 1:
                ax.set_xlabel('Frame index', fontsize=9)
            if col == 0:
                ax.set_ylabel('CFO (Hz)', fontsize=9)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f'  → {output_path}')


def plot_pdp_heatmap(
    cir_dict: dict[int, np.ndarray],
    band: str,
    output_dir: Path,
) -> None:
    """PNG 2-4: 2×2 PDP 热力图（per 频段）。  §7.2"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'PDP heatmap — {band}', fontsize=13)

    pos = {2: (0, 0), 3: (0, 1), 5: (1, 0), 13: (1, 1)}
    for M, (r, c) in pos.items():
        ax = axes[r][c]
        if M not in cir_dict:
            ax.set_visible(False)
            continue
        pdp_db = 10 * np.log10(np.abs(cir_dict[M]) ** 2 + 1e-10)  # (n, 1024)
        im = ax.imshow(pdp_db.T, aspect='auto', origin='lower',
                       cmap='viridis', interpolation='none')
        plt.colorbar(im, ax=ax, label='Power (dB)')
        ax.set_title(f'M={M}  ({cir_dict[M].shape[0]} frames)', fontsize=11)
        ax.set_xlabel('Frame index', fontsize=10)
        ax.set_ylabel('Delay bin', fontsize=10)

    fig.tight_layout()
    out = output_dir / f'PDP_heatmap_{band}.png'
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  → {out}')


def plot_pdp_frame(
    cir_dict: dict[int, np.ndarray],
    band: str,
    frame_idx: int,
    output_dir: Path,
) -> None:
    """PNG 5-7: 指定帧的 PDP 折线图（per 频段，4条曲线）。  §7.3"""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title(f'{band} — Frame {frame_idx} PDP', fontsize=13)

    for M in M_LIST:
        if M not in cir_dict or frame_idx >= cir_dict[M].shape[0]:
            continue
        pdp_db = 10 * np.log10(np.abs(cir_dict[M][frame_idx]) ** 2 + 1e-10)
        ax.plot(np.arange(U), pdp_db, label=f'M={M}',
                color=_COLOR[M], linewidth=1.2)

    ax.set_xlabel('Delay bin', fontsize=11)
    ax.set_ylabel('Power (dB)', fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    out = output_dir / f'PDP_frame{frame_idx}_{band}.png'
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  → {out}')


def plot_peak_power_timeseries(
    cir_dict: dict[int, np.ndarray],
    band: str,
    output_dir: Path,
) -> None:
    """主径功率时序（4个M值，4个子图）。"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'Main-path Power Timeseries — {band}', fontsize=13)

    pos = {2: (0, 0), 3: (0, 1), 5: (1, 0), 13: (1, 1)}

    for M, (r, c) in pos.items():
        ax = axes[r][c]
        if M not in cir_dict:
            ax.set_visible(False)
            continue

        cir = cir_dict[M]
        peak_bin = find_peak_bin(cir)
        power_linear = (np.abs(cir[:, peak_bin]) ** 2).astype(np.float64)
        power_db = 10 * np.log10(power_linear + 1e-10)

        frame_idx = np.arange(len(power_db))
        ax.plot(frame_idx, power_db, linewidth=0.8, color=_COLOR[M])
        ax.set_title(f'M={M}  (peak_bin={peak_bin})', fontsize=11)
        ax.set_xlabel('Frame index', fontsize=10)
        ax.set_ylabel('Power (dB)', fontsize=10)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out = output_dir / f'peak_power_timeseries_{band}.png'
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  → {out}')

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cfo_ts: dict[str, dict[int, np.ndarray]] = {}

    for band, m_files in BAND_M_FILES.items():
        print(f"\n{'='*52}")
        print(f"[{band}]  fc = {FC_HZ[band]/1e9:.1f} GHz")

        cir_dict: dict[int, np.ndarray] = {}
        P_bar:    dict[int, float]      = {}
        cfo_ts[band] = {}

        for M, filename in m_files.items():
            path = DATA_ROOT / filename
            try:
                # §2 步骤1: bin_read → CIR
                cir, _gps = read_bin_to_cir(path)   # (n_frames, 1024)

                # §2 步骤2-5: 主径功率
                P, peak_bin     = extract_peak_power(cir)
                P_bar[M]        = P
                cir_dict[M]     = cir
                cfo_ts[band][M] = estimate_residual_cfo(cir)

                print(f"  M={M:2d}: {cir.shape[0]:6d} frames | "
                      f"peak_bin={peak_bin:4d} | P_bar={P:.4e}")

            except FileNotFoundError:
                print(f"  M={M:2d}: [SKIP] 文件未找到: {filename}")
            except ValueError as e:
                print(f"  M={M:2d}: [SKIP] {e}")

        # §3 + §4: 幅度法 CFO 估计
        if len(P_bar) == len(M_LIST):
            res = estimate_cfo_amplitude(P_bar)
            fc  = FC_HZ[band]
            ppm = res['f_cfo_hz'] / fc * 1e6
            print(f"\n  [幅度法 CFO]")
            print(f"  f_CFO    = {res['f_cfo_hz']:.1f} Hz  ({ppm:.3f} ppm @ {fc/1e9:.1f} GHz)")
            print(f"  Δφ       = {res['dphi_hat']:.5f} rad")
            print(f"  residual = {res['residual']:.4e}")
            print(f"  rho_meas = { {k: f'{v:.4f}' for k, v in res['rho_meas'].items()} }")
            print(f"  rho_fit  = { {k: f'{v:.4f}' for k, v in res['rho_fit'].items()} }")
        else:
            print(f"\n  [WARN] 仅 {len(P_bar)}/{len(M_LIST)} 个 M 值，跳过幅度法")

        # §7.2 + §7.3: PDP 图 + 主径功率时序
        if cir_dict:
            plot_pdp_heatmap(cir_dict, band, OUTPUT_DIR)
            plot_pdp_frame(cir_dict, band, FRAME_ANALYSIS, OUTPUT_DIR)
            plot_peak_power_timeseries(cir_dict, band, OUTPUT_DIR)

    # §7.1: 余数 CFO 时序图（汇总所有频段）
    if any(cfo_ts[b] for b in cfo_ts):
        plot_cfo_timeseries(cfo_ts, OUTPUT_DIR / 'CFO_timeseries.png')

    print(f"\n{'='*52}")
    print(f"Done.  输出目录: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
