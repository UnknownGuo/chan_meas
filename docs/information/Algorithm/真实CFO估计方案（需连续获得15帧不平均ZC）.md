# 新软件（1s 帧，15 ZC 不平均）真实 CFO 估计方案

## 1. 新软件的数据结构

```
每隔 1s 触发一次测量
    └─ 连续收发 15 个 ZC 序列（不做平均，全部保存原始 IQ）
           持续时间：15 × T_ZC = 15 × 1024/100MHz ≈ 153.6 μs
```

关键参数：

| 符号 | 数值 | 说明 |
|------|------|------|
| $T_{ZC}$ | $1024 / 100\text{MHz} = 10.24\ \mu\text{s}$ | 单个 ZC 序列持续时间 |
| $T_{burst}$ | $15 \times T_{ZC} \approx 153.6\ \mu\text{s}$ | 一次 burst 总持续时间 |
| $T_{rep}$ | $1\ \text{s}$ | burst 重复间隔 |
| $M$ | $15$ | 每次 burst 内的 ZC 数量 |

---

## 2. 测量**真实** CFO


### 2.1 新帧内时间基准

新方案在一个 burst 内保存 15 个独立 ZC 的 CIR，相邻 ZC 的时间间隔为 $T_{ZC} = 10.24\ \mu\text{s}$，对应 Nyquist 极限：

$$|f_{CFO}| < \frac{1}{2 T_{ZC}} = \frac{1}{2 \times 10.24\ \mu\text{s}} \approx 48.8\ \text{kHz}$$

TCXO 最大差频 24.5 kHz $\ll$ 48.8 kHz，**不存在模糊，可直接测量真实 CFO**。

---

## 3. 测量策略

### 3.1 推荐：B2B 模式（线缆直连）

**原因**：线缆连接为单一确定性路径，CIR 主径相位只受 CFO 影响，无多径干扰。OTA 测量中多径会引入额外相位噪声，降低 CFO 估计精度。

**步骤**：
1. TX / RX 通过 40 dB 衰减器线缆直连（与现有 B2B 校准链路相同）
2. 在任一工作频段（推荐 3.6 GHz，SNR 适中）运行新软件
3. 持续录制至少 5 分钟，获取 $\geq 300$ 个 burst

### 3.2 也可用静态 OTA（备选）

若 B2B 无法操作，静态 OTA（固定架设，强 LoS）也可使用。153.6 μs 内信道完全静止，主径相位变化纯粹由 CFO 导致，与 B2B 等价。但估计方差略大（多径噪声）。

---

## 4. CFO 估计算法

### 4.1 数据准备

对第 $t$ 次 burst，得到 $M = 15$ 个单独 CIR：

$$h_m^{(t)}[\tau] \in \mathbb{C}^{U},\quad m = 0, 1, \ldots, 14$$

每个 CIR 由对应 ZC 序列的原始 IQ 做滑动相关（匹配滤波）得到，计算方式与原流水线相同，但**不做跨序列平均**。

### 4.2 单次 Burst 内的 CFO 估计

**相位模型**：

在静止信道中，第 $m$ 个 ZC 的主径复数峰值为：

$$h_m[\tau^*] = A \cdot e^{j\phi_0} \cdot e^{j 2\pi f_{CFO} \cdot m \cdot T_{ZC}} + w_m$$

其中 $A$ 为信道幅度，$\phi_0$ 为初始相位，$w_m$ 为噪声。

**Step 1**：定位主径 bin（对整个 burst 的非相干平均 PDP 取最大值）

$$\tau^* = \arg\max_{\tau} \frac{1}{M} \sum_{m=0}^{M-1} |h_m[\tau]|^2$$

**Step 2**：提取 $M$ 个主径复数峰值，计算相邻差分相位

$$\delta\phi[m] = \angle\!\left( h_{m+1}[\tau^*] \cdot \overline{h_m[\tau^*]} \right), \quad m = 0, \ldots, M-2$$

共 $M-1 = 14$ 个相位差。

**Step 3**：线性拟合（比直接取均值更鲁棒）

对 $m \times T_{ZC}$ vs. 累积相位 $\phi[m] = \sum_{i=1}^m \delta\phi[i]$ 做最小二乘线性回归：

$$\phi[m] \approx \alpha \cdot m + \beta \quad \Rightarrow \quad \hat{f}_{CFO}^{(t)} = \frac{\alpha}{2\pi \cdot T_{ZC}}$$

> 也可直接用 $\hat{f}_{CFO}^{(t)} = \text{mean}(\delta\phi) / (2\pi T_{ZC})$，在 SNR 较高时两者等价。

### 4.3 多 Burst 聚合（提升精度）

将 $N_{burst}$ 次 burst 的估计结果取平均：

$$\hat{f}_{CFO} = \frac{1}{N_{burst}} \sum_{t=1}^{N_{burst}} \hat{f}_{CFO}^{(t)}$$

**注意**：burst 间的 1s 间隔不参与估计（1s 间隔的相位完全混叠，不能用于 CFO 计算），只有 burst 内的 $T_{ZC}$ 时间基准有效。

---

## 5. 精度分析

单次 burst 内 15 个 ZC 做线性拟合，CFO 估计标准差：

$$\sigma_{f_{CFO}}^{(single)} = \frac{\sigma_\phi}{2\pi \cdot T_{ZC} \cdot \sqrt{\sum_{m=0}^{14}(m - \bar{m})^2}}$$

其中 $\sum(m - \bar{m})^2 = 280$（$M=15$ 均匀间隔），$\sigma_\phi \approx 1/\sqrt{2 \cdot \text{SNR}_{linear}}$。

| 场景 | SNR | $\sigma_\phi$ | 单 burst 精度 | 300 burst 聚合精度 |
|------|-----|---------------|---------------|-------------------|
| B2B，40 dB 衰减 | ~20 dB | 0.071 rad | ~66 Hz | **~3.8 Hz** |
| 静态 OTA，LoS | ~15 dB | 0.126 rad | ~117 Hz | ~6.8 Hz |

在 1.4 GHz 时，3.8 Hz 对应约 **2.7 ppb**，远优于 TCXO 标称精度（2500 ppb），足够用于相干叠加校准。

---

## 6. 与原 10ms 方案的对比

| 维度        | 原 10ms 帧（已平均）               | 新 1s 帧（15 ZC 未平均）                      |
| --------- | --------------------------- | -------------------------------------- |
| 时间基准      | $T_{frame} = 10\ \text{ms}$ | $T_{ZC} = 10.24\ \mu\text{s}$          |
| 不模糊范围     | ±50 Hz                      | ±48.8 kHz                              |
| 能否测真实 CFO | **否**（TCXO 差频 >> 50 Hz）     | **是**（TCXO 差频 < 12.25 kHz << 48.8 kHz） |
| 每次观测数据量   | 1 帧（已平均，信息损失）               | 15 × 原始 CIR（完整保留）                      |
| 帧间相位用途    | 只能观测余数 CFO                  | 可追踪 CFO 随时间的缓慢漂移                       |

---

## 7. 用估得的 $\hat{f}_{CFO}$ 校准原 10ms 帧数据

一旦用新软件估到真实 $\hat{f}_{CFO}$，可直接按 [[B2B频偏估计与OTA校准方案]] 中 Step 2 施加相位补偿：

$$\tilde{h}_{OTA}[k, \tau] = h_{OTA}[k, \tau] \cdot e^{-j \cdot 2\pi \hat{f}_{CFO} \cdot k \cdot T_{frame}}$$

此时 $\hat{f}_{CFO}$ 是真实值而非余数值，补偿后帧间相位完全对齐，可做任意帧数的相干叠加。

---

## 8. 注意事项

1. **1s 间隔的相位不要用于估计**：$T_{rep} = 1\ \text{s}$ 远大于 $1/(2 f_{CFO})$，burst 间相位完全混叠，只有 burst 内的 $T_{ZC}$ 序列有意义。

2. **两台设备需同时开始录制**：CFO 是 TX 与 RX 振荡器的相对频差，需确保同一对设备（同一次测量的 TX/RX）的数据一起分析。

3. **温度稳定后再录制**：TCXO 在上电后需数分钟稳频，建议开机预热 10 分钟后再做正式录制。

4. **B2B 与 OTA 用同一频段同一天完成**：TCXO 频率随环境温度缓变，跨天或温差大时需重新标定。

---

## 相关文档

- [[B2B频偏估计与OTA校准方案]]：基于余数 CFO 的原方案（10ms 帧）
- [[相位偏差的影响]]：CFO 对 IQ 域相干平均的数学影响
