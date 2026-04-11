# src/io/bin_read.py 脱水版

## 核心逻辑 (1行)

将原始二进制文件（.bin）转换为原始CIR：解析帧 → 提取IQ和GPS → 滑动相关生成CIR。

## 物理常数

$F_s = 100\text{ MHz}$（采样率）  
$BW = 50\text{ MHz}$（信号带宽，时延分辨率 = 20 ns/bin）  
$U = 1024$（LFM长度 / CIR bin数）

## 关键函数的数据契约与核心变换

### 1. 帧加载：`_load_frames(path) → (n, 4132) uint8`
```
文件或目录 → np.fromfile → 按 FRAME_LEN=4132 切割 → (n_frames, 4132)
```
**陷阱** : 目录模式按文件名排序拼接，确保采集顺序正确

### 2. IQ解析：`_parse_iq(frames) → (n, U) complex64`
```
字节序列 [Q_hi, Q_lo, I_hi, I_lo] → 组合int16 → 除以32767 → I + jQ
```

### 3. GPS解析：`_parse_gps(frames) → dict`
```
Big-endian int32 → ×1e-7 → DDMM格式转十进制度
```
**返回** : lat, lon, alt, hour, minute, second（逐帧）

### 4. 滑动相关：`_sliding_correlate(iq) → (n, U) complex64`
```
IQ - mean(IQ)   [DC移除]
    ↓
tile(·, 3)      [避免循环混淆]
    ↓
FFT · H_matched · IFFT   [频域相关，H_matched = conj(LFM reversed)]
    ↓
extract[2U-1 : 3U-1] / U  [提取有效窗口，幅度归一化]
```
**原理** : 与LFM matched filter相关，峰值位置对应多径延迟

### 5. 公开接口：`read_bin_to_cir(path) → (cir_raw, gps)`
```
_load_frames → _parse_gps + _parse_iq → _sliding_correlate
```
**输出** : cir_raw (n_frames, U) complex64，gps dict  
**注意** : CIR为原始未校准结果，需经 cali.py 校准后使用
