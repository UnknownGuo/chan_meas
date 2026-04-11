# src/io/cali.py 脱水版

## 核心逻辑 (1行)

将原始CIR（时域）与B2B校准向量（频域）结合，移除系统频响并补偿硬件增益，输出校准后的CIR（时域）。

## 物理常数

$BW = 50\text{ MHz}$（决定频率轴分辨率）  
$U = 1024$（FFT点数）  
$\text{ATT} = 40\text{ dB}$（B2B衰减器，由 bin_read 导出）

## 校准公式

$$H_{\text{corrected}}(f) = \frac{\text{FFT}(\text{CIR})}{H_{\text{B2B}}(f)} \times 10^{\frac{-\text{att\_db} - G_{\text{PA}}(f) - 2G_{\text{ant}}(f)}{20}}$$

含义：
- $\div H_{\text{B2B}}$：移除 B2B 频响（系统硬件 + 衰减器）
- $\times$ 增益补偿：补偿 PA、TX天线、RX天线的幅度影响

## 关键函数的数据契约与核心变换

### 1. 核心校准：`apply_fr_calibration(cir, cali_vec, fc_hz, att_db, ...) → (n, U) complex64`
```
FFT(cir) / cali_vec           [移除B2B频响，频域除法]
    ↓
freqs = fftfreq(U, 1/BW) + fc_hz  [各bin的实际频率]
    ↓
pa   = interp(freqs, PA_datasheet)      [ZHL-2W-63-S+，线性插值]
ant  = interp(freqs, ANT_datasheet) × 2  [MA802P，TX+RX两端]
correction = 10^((-att_db - pa - ant) / 20)  [幅度修正系数]
    ↓
CIR_f × correction
    ↓
IFFT  [回时域]
```
**输出** : calibrated CIR (n_frames, U) complex64

### 2. PA增益插值：`_interp_pa_gain(freqs_hz) → (U,) float64`
```
数据源 : ZHL-2W-63-S+ Mini-Circuits 数据手册（600 MHz ~ 6 GHz，12个频点）
方法   : np.interp（线性插值）
```

### 3. 天线增益插值：`_interp_ant_gain(freqs_hz) → (U,) float64`
```
数据源 : MA802P（30 MHz ~ 8 GHz，13个频点）
         <200 MHz: ~−20 dBi；≥200 MHz: 0 dBi
方法   : np.interp（线性插值）
应用   : × 2（TX + RX 同型天线）
```

## 参数选择逻辑

| 参数 | None | 标量 | 数组 |
|------|------|------|------|
| `pa_gain_db` | 用 ZHL-2W-63-S+ 数据手册 | 全频段统一值 | 自定义逐bin |
| `ant_gain_dbi` | 用 MA802P 数据手册 | 全频段统一值（×2） | 自定义逐bin（×2） |

**跳过天线校正** : 传 `ant_gain_dbi=0.0`

## 与上下游的接口

```
b2b_extract.extract_cali_vec()  →  cali_vec (U,) complex128
bin_read.read_bin_to_cir()      →  cir_raw  (n_frames, U) complex64
                                          ↓
                          cali.apply_fr_calibration(cir_raw, cali_vec, ...)
                                          ↓
                               cir_cal  (n_frames, U) complex64
```
