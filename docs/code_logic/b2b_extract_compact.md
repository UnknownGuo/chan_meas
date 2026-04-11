# src/io/b2b_extract.py 脱水版

## 核心逻辑 (1行)

将B2B .bin文件转换为频域校准向量：与bin_read相同的前3步（加载→IQ解析→滑动相关），最后FFT得到频响 $H_{\text{sys}} \times H_{\text{att}}$，保存为 cali_vec（频域FR）。

## 与bin_read的区别

| 项目 | bin_read | b2b_extract |
|------|----------|-------------|
| 输入 | A2A测量数据 | B2B背靠背数据 |
| 输出 | CIR（时域） | cali_vec（**频域**） |
| 帧数 | 全部帧 | 通常单帧（见陷阱） |
| 后续 | → cali.py校准 | → cali.py除法 |

## 关键函数的数据契约与核心变换

### 1. 校准向量提取：`extract_cali_vec(b2b_path, n_avg, mag_avg) → (U,) complex128`
```
B2B .bin
    ↓
_load_frames → _parse_iq → _sliding_correlate  [同bin_read]
    ↓
[单帧模式 n_avg=1]  FFT(cir[0])  → cali_vec
    ↓
[幅度平均 mag_avg=True]
    H_frames = FFT(cir[:n])          # (n, U)
    H_mag_avg = mean(|H_frames|)     # (U,)  幅度稳定
    H_phase = angle(H_frames[0])     # (U,)  相位取第0帧
    cali_vec = H_mag_avg × e^(jH_phase)
```
**为什么单帧** : 独立TCXO系统中，帧间相位漂移 ~440 rad/frame（7 kHz偏移），多帧相干平均导致相位抵消

**为什么幅度平均保留第0帧相位** : 幅度 N 帧平均可抑制噪声；相位取单帧以保留硬件群延迟，使校准后CIR峰值对齐 ~0 ns

**输出** : cali_vec = $H_{\text{sys}} \cdot H_{\text{att}}$，shape (U,)，complex128

### 2. B2B诊断：`diagnose_b2b_delay(cir_b2b) → dict`
```
|mean(cir_b2b)|² → argmax(power) → peak_bin × (10⁹/BW)
```
**陷阱** : 峰值位置（~bin 65，~1300 ns）为硬件处理延迟（ADC流水线+数字滤波器群延迟），**非频率偏移**

## 频率偏移陷阱（重点）

| 认知 | 现实 |
|------|------|
| B2B峰值 = 频偏 | B2B峰值 = 硬件延迟(1300 ns) |
| TCXO频偏 ≈ 3.2 MHz（原估计） | TCXO精度 ±2.5 ppm = ±3.5 kHz @ 1.4 GHz |
| 应用频偏校正 | **禁用**（`estimate_freq_offset_hz` 返回0并警告） |
