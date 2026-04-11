# IQ 求平均方式分析报告

**分析工程：** `channel_air_v4` 和 `channel_ground_v4`  
**结论：两个工程涉及 IQ 求平均的模块完全相同，均采用直接平均，不去掉首个或末尾 IQ。**

---

## 一、涉及 IQ 求平均的模块清单

| 模块文件 | 功能 | 平均方式 |
|---|---|---|
| `rt_aver_calc.v` | 实时滑动平均（对 IQ 幅值/符号直接平均） | **直接平均（滑动窗口）** |
| `inPower.v` | 计算 IQ 信号平均功率（`I²+Q²` 平均） | **直接平均（固定块）** |
| `snr_burst.v` | SNR 估计（含多帧平均） | 非 IQ 本身求均，是功率累积 |

---

## 二、`rt_aver_calc.v` — 主体 IQ 滑动平均模块

**文件路径：**  
`IP/SCFDE/xilinx.gpp.com_user_phy_demodulation_2.0/src/rt_aver_calc.v`

### 关键参数

```verilog
parameter IN_BW   = 16        // 输入位宽
parameter RAM_DEPT = 2048     // 内部 RAM 深度
// 窗口长度 = RAM_DEPT / 2 = 1024 个采样点
// ACC_BW = clogb2(1024-1) = 10，即除以 1024 用右移 10 位实现
```

### 算法流程（两阶段）

**第一阶段：预积累（前 1024 个有效 IQ 样本）**

```verilog
// acc_din_sel == 0 时
data_in_acc <= data_in_acc + rt_ram_dina;
```

- 逐点累加所有输入，直到写入第 1024 个样本（`rt_ram_addra == RAM_DEPT/2-1`）。
- 此阶段 `o_data_out_valid = 0`，不输出结果。

**第二阶段：稳态滑动窗口（1024 点之后）**

```verilog
// acc_din_sel == 1 时
din_dif        <= i_data_in - rt_ram_doutb;   // 新值 − 1024 拍前的旧值
data_in_acc    <= data_in_acc + din_dif;       // 滑动更新累加器
o_data_out     = data_in_acc[IN_BW+ACC_BW-1 : ACC_BW];  // 累加器 >> 10 = ÷ 1024
```

- RAM 作循环缓冲，每次读出的是 1024 拍前存入的旧值。
- 累加器始终维持"最近 1024 个 IQ 值之和"，输出为其除以 1024 的平均值。

### 结论

> **直接对最近 1024 个 IQ 采样做等权平均，不去掉首个，不去掉末尾，每个样本权重相同。**

数学表达式：

$$\bar{x}[n] = \frac{1}{1024} \sum_{k=0}^{1023} x[n-k]$$

---

## 三、`inPower.v` — IQ 功率平均模块

**文件路径：**  
`IP/SCFDE/xilinx.gpp.com_user_phy_demodulation_2.0/src/inPower.v`

### 关键参数

```verilog
parameter nINTEG = 64;   // 积分点数
parameter CUT    = 6;    // 2^6 = 64，用右移实现除法
```

### 算法流程

```verilog
powerIQ <= powerI[2*W1-1:2] + powerQ[2*W1-1:2];  // 瞬时功率 = (I²+Q²)/4

// 累加 64 次后输出
if(cnt == nINTEG) begin
    o_sig_power <= power_sum[W2+CUT-1:CUT];  // sum / 64
    power_sum   <= 0;
end else begin
    power_sum <= power_sum + powerIQ;
end
```

- 计数器从 0 数到 64，共积累 64 个瞬时功率值。
- 第 64 拍输出均值并清零，周而复始。

### 结论

> **直接对连续 64 个 IQ 功率点（`I²+Q²`）等权平均，不去掉首个，不去掉末尾。**

$$P_{avg} = \frac{1}{64} \sum_{k=0}^{63} \left(\frac{I_k^2 + Q_k^2}{4}\right)$$

---

## 四、`snr_burst.v` — SNR 估计中的均值处理

该模块对 IQ 做的不是简单幅值平均，而是：
1. 将导频序列（ZC序列）分两半，分别与接收 IQ 进行相关（`re = I₁I₂ + Q₁Q₂`），累加后作为信号功率估计。
2. 对两半差值（`I₁-I₂, Q₁-Q₂`）平方累加作为噪声功率估计。
3. 对上述结果再做 `SNR_ACC_NUM=8` 帧的多帧平均，直接累加 8 帧后除以 8。

> **多帧 SNR 估计也是直接平均，不去掉首帧或末帧。**

---

## 五、总结

| 问题 | 答案 |
|---|---|
| 是去掉首个 IQ 和最后一个 IQ 后求平均？ | **否** |
| 是去掉首个 IQ 后求平均？ | **否** |
| 是直接平均？ | **是** |

两个工程（`channel_air_v4` 和 `channel_ground_v4`）中所有 IQ 求平均相关模块，代码完全一致，均采用**直接等权平均**策略：

- `rt_aver_calc.v`：滑动窗口 1024 点直接平均
- `inPower.v`：固定块 64 点直接平均
- `snr_burst.v`：多帧 8 次直接平均（针对功率估计）

无任何"去头去尾"的截断处理。
