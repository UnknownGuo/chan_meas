# src/calibration/cfo_estimator.py 脱水版

## 核心逻辑 (2行)

LFM信号与接收IQ做匹配滤波生成CIR；从多帧CIR峰值的相位轨迹提取频率旋转，推断载波频偏。**原理** : 频偏Δf导致相邻帧间相位旋转 $2\pi \Delta f T_{\text{frame}}$。

## 物理参数

$U = 1024$（LFM长度）  
$T_{\text{frame}} = 0.01$ s（帧周期）  
$f_s = 100$ MHz（采样率）

## 关键函数

### 1. LFM Matched Filter：`build_lfm_matched_filter(U)→(3U,)`
```python
# 时域LFM
lfm(t) = exp(j·π·t·(t/U - 0.5))  # 线性调频，占满[-fs/2, +fs/2]

# 扩展3倍避免循环混淆
lfm_tiled = tile(lfm, 3)

# 频域matched filter（用于FFT相关）
h_match = conj(FFT(lfm_tiled))  # (3U,) complex64
```

### 2. 相干平均：`coherent_average(iq, axis)→mean(iq, axis)`
**陷阱** : 独立TCXO系统频偏~7kHz，10ms帧内相位旋转~440rad(70圈)→相位抵消  
**解决** : 用功率平均替代相干平均

### 3. CIR生成：`generate_cir_from_iq(iq:(U,), h_match:(3U,))→(U,)`
```python
# DC移除
iq_dc = iq - mean(iq)

# 时域扩展
iq_tiled = tile(iq_dc, 3)  # (3U,)

# FFT相关（频域乘法）
corr_full = IFFT(FFT(iq_tiled) × h_match)  # (3U,) complex128

# 提取有效窗口
CIR = corr_full[U:2U]  # (U,) complex64
```
**原理** : 相关峰位置反映多径延迟，峰值幅度反映功率

### 4. CFO估计（方法1）：`estimate_by_adjacent_frames()→(cfo_hz, dphi)`
```python
# 峰值追踪（选择功率最大的bin）
peak_bin = argmax(mean(|CIR|²))

# 相邻帧相位差
peak = CIR[:, peak_bin]  # (n_frames,)
Δφ_k = angle(peak[k+1] × conj(peak[k]))  # (n_frames-1,)

# 频偏估计
Δf_k = Δφ_k / (2π·T_frame)  # (n_frames-1,)
```
**可观测范围** : ±1/(2T_frame) Hz  
**局限** : 相位折叠（>±π时失效）

### 5. CFO估计（方法2）：`estimate_by_cumulative_phase()→(φ_unwrap, cfo_per_frame, cfo_slope)`
```python
# 相对第0帧的累积相位
φ_raw = angle(peak × conj(peak[0]))  # (n_frames,)

# 相位展开（消除2π跳变）
φ_unwrap = unwrap(φ_raw)

# 线性拟合（最小二乘）
t = [T_frame, 2·T_frame, ..., (n-1)·T_frame]
slope, _ = polyfit(t, φ_unwrap[1:], 1)  # 一次多项式

# 全局频偏
cfo_slope = slope / (2π)  # Hz
```
**优势** : 
- ✅ 处理相位折叠（超过±π）
- ✅ 全局最小二乘拟合（抗异常值）
- ✅ 物理含义清晰：$\Delta f = \frac{1}{2\pi} \frac{d\phi}{dt}$

### 6. 统计汇总：`calculate_cfo_statistics(cfo_hz)→dict`
```python
{
    "mean_hz": mean(cfo_hz),
    "std_hz": std(cfo_hz),
    "min_hz": min(cfo_hz),
    "max_hz": max(cfo_hz),
}
```
**解读** : std反映频偏稳定性（TCXO应<1Hz）

## 完整处理链

```
洛阳格式:
read_iq_sequences(path)  # (n, 15, 1024)
    ↓
coherent_average(axis=1)  # (n, 1024)
    ↓
build_lfm_matched_filter(1024)  # (3072,)
    ↓
generate_cir_from_iq(...)×n  # (n, 1024)
    ↓
CFOEstimator(cir)  # 初始化
    ↓
estimate_by_cumulative_phase()  # cfo_hz

标准格式:
process_band(...)  # 内含sliding_correlate → CIR (n, 1024)
    ↓
CFOEstimator(cir)
    ↓
estimate_by_cumulative_phase()  # cfo_hz
```

## 关键数学恒等式

**相位旋转与频偏的映射** :
$$\phi(t) = 2\pi \Delta f \cdot t$$

**相邻帧相位差** :
$$\Delta\phi = \phi(kT + T) - \phi(kT) = 2\pi \Delta f \cdot T_{\text{frame}}$$

**累积相位线性性** :
$$\phi_{\text{cumul}}(k) = 2\pi \Delta f \cdot k \cdot T_{\text{frame}}$$
$$\Rightarrow \text{slope from polyfit} = 2\pi \Delta f$$

