# src/io/bin_reader_luoyang.py 脱水版

## 核心逻辑 (1行)

将61476字节/帧的洛阳格式二进制数据解析为(n_frames, P_SEQS=15, U=1024) complex64 IQ立方体。

## 物理参数

$P_{\text{SEQS}} = 15$（帧内LFM序列数）  
$U = 1024$（每个LFM采样点数）  
$L_{\text{frame}} = 61476$字节  
$\text{IQ_offset} = 32$字节  
$\text{bytes/sample} = 4$ (Q_hi, Q_lo, I_hi, I_lo)

## 数据流向

```
.bin文件 (单个文件或多个)
    ↓
fromfile(uint8) → 1D数组
    ↓
reshape(n_frames, L_frame) → 2D帧数组
    ↓
提取IQ字节 [32 : 32+61440]
    ↓
reshape(n_frames, 15×1024, 4)
    ↓
逐byte解码: [hi, lo] → 16bit整数 → 除以32767 → float32
    ↓
组合复数 I + jQ
    ↓
reshape(n_frames, 15, 1024) complex64
```

## 关键函数

### 帧长解析：`_parse_frame_len(raw_bytes)→int`
```python
frame_len = raw_bytes[5] × 256 + raw_bytes[6]  # big-endian uint16
```
**物理含义** : 从帧头字段读取（若为0则用标称值61476）

### IQ解码：`_decode_int16(hi, lo)→float32`
```python
raw = hi × 256 + lo
if raw > 32767:  raw -= 65536  # 补码处理
return raw / 32767.0  # 归一化到[-1, 1]
```

### 完整解析：`read_iq_sequences(path, max_frames)→(n, 15, 1024)`
```
reshape into frames
    ↓
extract iq_bytes[32:32+61440]
    ↓
reshape(n, 15360, 4)  # 15×1024×4
    ↓
解码I, Q通道 (字节2,3)和(字节0,1)
    ↓
组合复数 & reshape(n, 15, 1024)
```

## 关键设计

✅ **单一职责** : 仅负责I/O和字节解析，不进行信号处理  
✅ **容错性** : 帧长为0时使用标称值；帧长不符时警告但继续  
✅ **灵活性** : 支持帧数限制(max_frames)，避免OOM

## 与标准格式的差异

| 特性 | bin_reader.py | bin_reader_luoyang.py |
|------|------|------|
| 帧长 | 4132 B | 61476 B |
| LFM/帧 | 1 | 15 |
| 输出形状 | (n, 1024) | (n, 15, 1024) |
| 帧周期 | 未定 | 10 ms |
| 处理管道 | CIR生成 + 校正 | 仅解析，后接cfo_estimator |

