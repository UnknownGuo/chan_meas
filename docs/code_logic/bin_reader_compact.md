# src/io/bin_reader.py 脱水版

## 核心逻辑 (3行)

将原始二进制文件（.bin）转换为校准CIR：先滑动相关生成CIR，再用B2B频响校准向量除以CIR（频域），最后乘以系统增益补偿（衰减器、PA、天线）。

## 物理常数

$F_s = 100\text{ MHz}$（采样率）  
$BW = 50\text{ MHz}$（信号带宽，时延分辨率 = 20 ns/bin）  
$U = 1024$（LFM长度）  
$\text{ATT} = 40\text{ dB}$（B2B衰减器）

## 关键函数的数据契约与核心变换

### 1. IQ解析：`_parse_iq(frames: (n, 4132)→(n, U))`
```
字节序列 [Q_hi, Q_lo, I_hi, I_lo] → 组合int16 → 除以32767 → I + jQ
```

### 2. GPS解析：`_parse_gps(frames)→dict`
```
Big-endian int32 → 乘以1e-7 → DDMM格式转十进制度
```

### 3. 滑动相关：`_sliding_correlate(iq)→CIR`
```
IQ - mean(IQ)  [DC移除]
    ↓
tile(·, 3)  [避免循环混淆]
    ↓
FFT · matched_filter · IFFT  [频域相关]
    ↓
extract[U:2U]  [提取有效窗口]
```
**原理** : 与LFM matched filter相关，峰值表示多径延迟

### 4. B2B诊断：`diagnose_b2b_delay(cir_b2b)→peak_bin, delay_ns, power_db`
```
|mean(cir_b2b)| ² → argmax(power) → 峰值位置 × (10⁹/BW)
```
**陷阱** : 峰值(~bin65, ~1300ns)反映硬件延迟，非频偏

### 5. 校准向量提取：`compute_cali_from_b2b(b2b_path)→cali_vec`
```
单帧B2B CIR → FFT(real/imag) → (H_sys · H_att)
```
**为什么单帧** : 独立TCXO系统中多帧相干平均会相位抵消

### 6. 频响校正：`_fr_calibrate(cir, cali_vec, fc, att_db, PA_gain, ant_gain)`
```
FFT(cir) / cali_vec  [移除B2B频响]
    ↓
× 10^(-(att_db + PA(f) + ant(f))/20)  [补偿系统增益]
    ↓
IFFT  [回时域]
```
**校准公式** :
$$H_{\text{corrected}}(f) = \frac{H_{\text{raw}}(f)}{H_{\text{B2B}}(f)} \times \frac{H_{\text{att}}}{H_{\text{PA}}(f) \cdot G_{\text{ant}}(f)}$$

### 7. 完整流程：`process_band(a2a_path, b2b_path, fc_hz)`
```
B2B: read → sliding_correlate → diagnose & extract_cali_vec
      ↓
A2A: read → parse_gps → sliding_correlate → fr_calibrate → CIR_final
```
**返回** : (n_frames, U) complex64 CIR, gps dict, b2b_diag dict

## 频率偏移陷阱（重点）

| 认知 | 现实 |
|------|------|
| B2B峰值 = 频偏 | B2B峰值 = 硬件延迟(1300ns) |
| TCXO频偏 ≈ 3.2 MHz（原估计） | TCXO精度 ±2.5ppm = ±3.5kHz @ 1.4GHz |
| 应用频偏校正 | **禁用**（返回0或警告） |

## PA/天线增益查表

- **PA** : ZHL-2W-63-S+, 600MHz~6GHz, 线性插值
- **天线** : MA802P, 30MHz~8GHz, 双端应用(TX+RX)

