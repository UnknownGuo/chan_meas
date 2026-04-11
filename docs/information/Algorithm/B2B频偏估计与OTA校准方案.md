# B2B 频偏估计与 OTA 校准方案

## 背景

收发两端各自使用独立 TCXO（温补晶振，标称精度 ±2.5 ppm），导致两台设备之间存在载波频率偏移（CFO）。CFO 在帧间表现为 CIR 主径相位的线性累积旋转，阻碍跨帧相干叠加。

本文档描述如何利用 B2B（背靠背，线缆直连）测量数据估计 CFO，并将其用于对实测 OTA 数据的相位校准。

---

## 核心结论

相邻帧相位差法（10 ms 帧率）测到的**表观 CFO** $f_{app}$ 与**真实 CFO** $f_{true}$ 的关系：

$$f_{true} = f_{app} + \frac{n}{T_{frame}}, \quad n \in \mathbb{Z}$$

其中 $T_{frame} = 10\ \text{ms}$，$1/T_{frame} = 100\ \text{Hz}$。

**关键洞察**：校准时只需 $f_{app}$，无需解整数模糊 $n$。

**证明**：用 $f_{app}$ 补偿后，每帧残差相位为

$$\Delta\phi_{residual} = 2\pi \cdot n \cdot T_{frame} \cdot \frac{1}{T_{frame}} = 2\pi n \equiv 0 \pmod{2\pi}$$

整数倍 $2\pi$ 对帧间相位对齐无影响，因此 $f_{app}$ 已足够实现完整的相干叠加。

---

## 三步流程

### Step 1：从 B2B 数据估计 $f_{app}$

**为何用 B2B 而非 OTA 来估计**：B2B 线缆直连，单一确定性路径，无多径干扰，相位测量信噪比高、线性度好；OTA 数据存在多径波动和环境噪声，相位跳变多，估计结果不可靠。

**算法**：

1. 加载 B2B `.bin` 文件，做滑动相关得到 CIR：

$$h^{B2B}[k, \tau] \in \mathbb{C}^{N_{frames} \times U}$$

2. 对非相干平均功率延迟谱（PDP）定位主径 bin：

$$\tau^* = \arg\max_{\tau} \frac{1}{N}\sum_k |h^{B2B}[k, \tau]|^2$$

3. 提取每帧主径复数峰值，计算相邻帧相位差：

$$\Delta\phi[k] = \angle\!\left( h^{B2B}[k, \tau^*] \cdot \overline{h^{B2B}[k-1, \tau^*]} \right), \quad k = 1, \ldots, N-1$$

4. 对累积相位做**线性最小二乘拟合**（比直接取均值更鲁棒，自动抑制 unwrap 失败帧）：

$$\hat{\phi}_{acc}[k] = \sum_{i=1}^{k} \Delta\phi[i] \approx \alpha \cdot k + \beta$$

$$\alpha = \text{slope (rad/frame)} \quad \Rightarrow \quad f_{app} = \frac{\alpha}{2\pi T_{frame}}\ [\text{Hz}]$$

> **建议**：拟合前用鲁棒方法（如 RANSAC 或 Theil-Sen 中位数斜率）剔除相位跳变点，避免 unwrap 失败污染斜率估计。

**每个频段独立估计一个** $f_{app}$，输出为单个标量（Hz）。

---

### Step 2：对 OTA 每帧做相位补偿

$$\tilde{h}_{OTA}[k, \tau] = h_{OTA}[k, \tau] \cdot e^{-j \cdot 2\pi f_{app} \cdot k \cdot T_{frame}}$$

将所有帧"转回"第 0 帧的相位参考，消除帧间累积旋转。此操作逐帧逐延迟 bin 均匀施加，不改变 CIR 的幅度和时延结构。

---

### Step 3：相干叠加

$$\bar{h}[\tau] = \frac{1}{N}\sum_{k=0}^{N-1} \tilde{h}_{OTA}[k, \tau]$$

**SNR 增益**：$10\log_{10}(N)$ dB（理想相干平均）。

对于 V2V 动态测量，信道非平稳，须将数据切成短块（如每块 $N_{block}$ 帧，对应信道相干时间），在块内做相干叠加，块间做非相干叠加（功率平均）。

---

## 实测数据验证（2026-04-02 静态 OTA）

| 频段      | B2B 累积相位斜率           | 表观 CFO $f_{app}$           |
| ------- | -------------------- | -------------------------- |
| 1.4 GHz | ~$-0.0056$ rad/frame | $\approx -0.09\ \text{Hz}$ |
| 3.6 GHz | ~$-0.049$ rad/frame  | $\approx -0.78\ \text{Hz}$ |
| 4.9 GHz | ~$-0.020$ rad/frame  | $\approx -0.32\ \text{Hz}$ |

- B2B 相位漂移均呈清晰线性趋势，线性拟合置信度高。
- OTA 数据因多径噪声，相位跳变更多，不适合直接用于 $f_{app}$ 估计。
- 三个频段的 $f_{app}$ 数值均远小于 1 Hz，但这不代表真实 CFO 就这么小（见局限一节）。

---

## 前置条件

| 条件 | 说明 |
|------|------|
| B2B 与 OTA 时间相近 | TCXO 频率随温度缓慢漂移；同一天内同一地点的估计可直接复用 |
| 同一套收发硬件 | B2B 和 OTA 使用同一台 TX、同一台 RX，频偏符号一致 |
| 线性拟合时剔除跳变点 | unwrap 失败点会在累积相位上留下 $\pm\pi$ 台阶，须识别并排除后再拟合 |
| 每个频段独立估计 | 不同频段 $f_{app}$ 不同，不可混用 |
| 信道稳定性（相干叠加块长） | 对静态 OTA：整段数据均可；对 V2V 动态：须根据多普勒估计选取块长 |

---

## 局限性

1. **无法得知真实 ppm 值**：$f_{app}$ 仅实现帧间对齐，不反映两振荡器的绝对频差大小；若需 ppm 量级的 CFO 表征，须借助频谱仪或共享时钟源外部测量。

2. **帧内 15 次硬件平均已不可逆**：FPGA 在帧内对 15 个 ZC 序列做了相干平均。若帧内 CFO 导致的相位旋转较大（$2\pi \times f_{true} \times 15 \times T_{ZC}$ 接近 $\pi$），帧输出幅度本身已被压低，此校准方案只能恢复帧间相干性，无法补救帧内的幅度损失。

3. **$f_{app}$ 估计精度要求**：估计误差须远小于 $1/T_{frame} = 100\ \text{Hz}$，否则补偿后引入新偏差。由目前 B2B 数据线性趋势清晰，满足此条件。

---

## 相关文档

- [[相位偏差的影响]]：CFO 对 IQ 域相干平均的数学影响
