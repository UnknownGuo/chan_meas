# chan_meas 项目代码导读目录

## 项目概览

`chan_meas` 是一个无线信道测量数据处理系统，主要负责：
1. **原始二进制数据读取** - 支持标准格式和洛阳格式
2. **信号处理** - LFM matched filter、相干平均、CIR生成
3. **频率偏移估计** - 从CIR相位轨迹估计载波频偏（CFO）
4. **系统校准** - B2B校准向量、频响校正、系统增益补偿

## 文件导读清单

### 核心模块

| 文件 | 功能 | 位置 |
|------|------|------|
| **paths.py** | 项目路径配置，管理原始数据和处理后数据的存储位置 | [paths.md](paths.md) |
| **bin_reader.py** | 标准格式二进制文件读取与处理，支持B2B校准和频响校正 | [bin_reader.md](bin_reader.md) |
| **bin_reader_luoyang.py** | 洛阳格式二进制文件读取（10ms帧格式，15个LFM序列/帧） | [bin_reader_luoyang.md](bin_reader_luoyang.md) |
| **cfo_estimator.py** | 载波频偏估计、LFM matched filter构建、信号处理 | [cfo_estimator.md](cfo_estimator.md) |

## 模块依赖关系

```
paths.py (配置)
    ↓
[数据源]
    ├─→ bin_reader.py (标准格式)
    │      ├─→ sliding correlate → CIR
    │      └─→ FR calibration
    │
    └─→ bin_reader_luoyang.py (洛阳格式)
          ├─→ coherent_average (from cfo_estimator)
          ├─→ LFM matched filter (from cfo_estimator)
          └─→ CFO估计 (from cfo_estimator)

cfo_estimator.py (信号处理)
    ├─→ build_lfm_matched_filter()
    ├─→ generate_cir_from_iq()
    ├─→ CFOEstimator 类
    └─→ calculate_cfo_statistics()
```

## 数据处理流程

### 标准格式（bin_reader.py）
```
.bin文件 → 帧解析 → IQ提取 → 滑动相关 → CIR（原始）
                                          ↓
                                      B2B校准向量
                                          ↓
                                      频响校正 → CIR（校准）
```

### 洛阳格式（bin_reader_luoyang.py）
```
.bin文件 → 帧解析 → IQ按序列提取(n_frames, 15, 1024)
                    ↓
            帧间相干平均（可选）
                    ↓
            LFM matched filter + sliding correlation
                    ↓
                  CIR + CFO估计
```

### 载波频偏估计（cfo_estimator.py）
```
CIR(n_frames, U) → 找峰值bin → 相位轨迹分析
                                ↓
                        ├─→ 相邻帧相位差 (±1/(2T_frame) 范围)
                        └─→ 累积相位展开 (全局估计，容错强)
```

## 关键概念

### 硬件常数
- **FS_HZ** = 100 MHz (ADC采样率)
- **BW_HZ** = 50 MHz (信号带宽)
- **U** = 1024 (每个LFM序列的采样点数)
- **ATT_B2B_DB** = 40 dB (标准B2B衰减器)
- **T_FRAME** = 10 ms (洛阳格式帧周期)

### 核心数据结构
- **CIR** : Channel Impulse Response, 形状 (n_frames, U) or (n_frames, P_SEQS, U)
- **IQ** : 复数I/Q采样，形状 (n_frames, U) 或 (n_frames, P_SEQS, U)
- **cali_vec** : 频域校准向量，形状 (U,) complex128

### 关键信号处理
- **LFM** : Linear Frequency Modulation (线性调频)
- **Matched Filter** : 最大似然检测，使用FFT加速的滑动相关
- **Coherent Averaging** : 相干平均（要求频偏小，相位稳定）
- **Incoherent Averaging** : 功率平均（对频偏鲁棒，用于独立TCXO系统）

## 使用示例

### 标准格式完整处理
```python
from pathlib import Path
from bin_reader import process_band

cir, gps, diag = process_band(
    a2a_path=Path("1400_A2A.bin"),
    b2b_path=Path("1400_B2B.bin"),
    fc_hz=1.4e9,
    att_db=40.0
)
# cir: (n_frames, 1024) complex64
# gps: dict with lat, lon, alt, hour, minute, second
# diag: B2B诊断信息（峰值、延迟、功率）
```

### 洛阳格式处理流程
```python
from pathlib import Path
from bin_reader_luoyang import LuoyangBinReader
from cfo_estimator import build_lfm_matched_filter, generate_cir_from_iq, CFOEstimator

reader = LuoyangBinReader()
iq_seqs = reader.read_iq_sequences(Path("luoyang.bin"))  # (n_frames, 15, 1024)

# 帧间平均
iq_avg = iq_seqs.mean(axis=1)  # (n_frames, 1024)

# 生成CIR
h_match = build_lfm_matched_filter(1024)
cir = np.array([generate_cir_from_iq(iq_avg[i], h_match) for i in range(len(iq_avg))])

# CFO估计
estimator = CFOEstimator(cir)
cfo_hz, dphi = estimator.estimate_by_adjacent_frames()
```

## 注意事项

### 频率偏移陷阱（重要！）
- **误解** : B2B相关峰位置 (bin~65, ~1300ns) 代表频偏
- **真相** : 这是硬件处理延迟（ADC流水线 + 数字滤波器群时延），不是振荡器频偏
- **TCXO精度** : ±2.5 ppm = ±3.5 kHz @ 1.4 GHz（远小于1300ns对应的频偏）
- **正确做法** : 用`diagnose_b2b_delay()`诊断硬件延迟，不用B2B推导频偏

### 频域校准陷阱
- **频偏校正已禁用** 默认状态下，`process_band(..., correct_freq_offset=False)`
- **原因** : B2B峰值反映硬件延迟，不是频偏
- **独立TCXO系统** : 用`incoherent_average_pdp()`做功率平均而非相干平均

### 天线和PA增益
- **PA** : ZHL-2W-63-S+，来自Mini-Circuits数据手册，频点插值
- **天线** : MA802P，两端各应用一次（TX + RX），30～8000 MHz频段
- **自定义** : 可传入标量或per-bin数组，设0.0跳过

## 文档结构

每个模块的详细导读包含：
1. **模块概述** - 功能、职责、依赖
2. **数据结构** - 关键类和函数签名
3. **执行流程** - 逐步处理步骤
4. **代码细节** - 关键算法和参数

---

**最后更新** : 2026-04-08  
**版本** : 基于 chan_meas 主分支
