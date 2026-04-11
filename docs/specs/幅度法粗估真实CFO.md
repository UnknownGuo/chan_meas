# 幅度法粗估真实CFO（M=2,3,5,13）

> 基于多个平均数 M 下的主径功率比，通过非线性拟合反解真实 CFO。
> 适用条件：$f_{CFO} \gtrsim 3$ kHz（幅度差异明显）；$f_{CFO} \lesssim 1$ kHz 时精度差。

---

## 0. 硬件参数与数据说明

### 0.1 硬件参数

| 参数 | 值 | 单位 |
|------|-----|------|
| 信号带宽 $BW$ | 50 | MHz |
| FPGA时钟 | 100 | MHz |
| ZC序列长度 $U$ | 1024 | 样点 |
| $T_{ZC} = U / BW$ | **20.48** | μs |
| $T_{frame}$ | 10 | ms |
| 载波频率 $f_c$ | 1.4 / 3.6 / 4.9 | GHz |

### 0.2 数据路径

```
/mnt/win_data/data_mea/data_save/Cali_data/20260402_cfo_mea/
```

### 0.3 文件命名规则

```
CFO_B2B_20260407_M{M}_{设备}_{线缆}_{频段}.bin
```

示例：
```
CFO_B2B_20260407_M2_Black01_081cable_1400M.bin
CFO_B2B_20260407_M13_Black01_081cable_4900M.bin
```

频段标识：`1400M` / `3600M` / `4900M`  
M值：`M2` / `M3` / `M5` / `M13`

---

## 1. 理论基础

### 1.1 频率偏移下的功率衰减

平均数为 M 时，主径功率为：

$$\bar{P}^{(M)} = P_0 \cdot g^2(M, \Delta\phi)$$

其中 $\Delta\phi = 2\pi f_{CFO} T_{ZC}$，$g$ 函数为：

$$g(M, \Delta\phi) = \frac{\sin(M\Delta\phi/2)}{M\sin(\Delta\phi/2)}$$

$P_0$ 是未知的系统功率（不受频偏影响的部分）。

### 1.2 功率比消去未知量 $P_0$

两个不同 M 的功率之比：

$$\rho(M_i, M_j) = \frac{\bar{P}^{(M_j)}}{\bar{P}^{(M_i)}} = \frac{M_i^2 \cdot g^2(M_j, \Delta\phi)}{M_j^2 \cdot g^2(M_i, \Delta\phi)}$$

**关键性质**：
- 只依赖于 $\Delta\phi$（未知）和 $M_i, M_j$（已知）
- 与 $P_0$ 无关（被约掉）

---

## 2. 数据处理流程（以 M=2, 3, 5, 13 为例）

### 步骤1：加载并处理各M的数据

对每个 M 值，处理 6 分钟的 B2B 数据（调用 `src/io/bin_read.py` 完成前两步）。

```
输入：M=2, 3, 5, 13 各 6 分钟 B2B .bin 数据
      （每10ms一帧，共 6×60×100 = 36000 帧）

处理流程（参考 bin_read_compact）：
  1. bin_read.read_bin_to_cir(path) → CIR (36000, 1024) complex64
  2. 非相干 PDP（沿帧方向平均）：
       pdp = mean(|CIR|², axis=0)   → shape (1024,)
       axis=0：对36000帧做平均，保留1024个时延bin
       pdp[n] 表示第n个时延bin的平均功率
  3. 找主径：peak_bin = argmax(pdp)   → 标量（1024个bin中功率最大处）
  4. 主径功率：P_main = pdp[peak_bin]   → 标量
  5. 扣除热噪声：noise_floor = percentile(pdp, 10)
                 P_corrected = P_main - noise_floor
```

**输出**：$\hat{P}^{(2)}, \hat{P}^{(3)}, \hat{P}^{(5)}, \hat{P}^{(13)}$（各为标量，线性功率单位）
  
### 步骤2：计算功率比（6组方程）

给定4个M值，可得 $\binom{4}{2} = 6$ 个比值：

$$\hat{\rho}(M_i, M_j) = \frac{\hat{P}^{(M_j)}}{\hat{P}^{(M_i)}}$$

列表：

| 比值 | 公式 |
|------|------|
| $\hat{\rho}(2, 3)$ | $\hat{P}^{(3)} / \hat{P}^{(2)}$ |
| $\hat{\rho}(2, 5)$ | $\hat{P}^{(5)} / \hat{P}^{(2)}$ |
| $\hat{\rho}(2, 13)$ | $\hat{P}^{(13)} / \hat{P}^{(2)}$ |
| $\hat{\rho}(3, 5)$ | $\hat{P}^{(5)} / \hat{P}^{(3)}$ |
| $\hat{\rho}(3, 13)$ | $\hat{P}^{(13)} / \hat{P}^{(3)}$ |
| $\hat{\rho}(5, 13)$ | $\hat{P}^{(13)} / \hat{P}^{(5)}$ |

---

## 3. 非线性拟合求解 $\Delta\phi$

### 3.1 目标函数

定义残差平方和：

$$\text{cost}(\Delta\phi) = \sum_{i,j} \left[\hat{\rho}(M_i, M_j) - \rho_{\text{theory}}(M_i, M_j; \Delta\phi)\right]^2$$

其中理论值为：

$$\rho_{\text{theory}}(M_i, M_j; \Delta\phi) = \frac{M_i^2 \cdot g^2(M_j, \Delta\phi)}{M_j^2 \cdot g^2(M_i, \Delta\phi)}$$

$$g(M, \Delta\phi) = \frac{\sin(M\Delta\phi/2)}{M\sin(\Delta\phi/2)}$$

### 3.2 搜索范围

$\Delta\phi \in [0, \pi]$ 对应 $f_{CFO} \in [0, f_{CFO, \text{max}}]$

其中：
$$f_{CFO, \text{max}} = \frac{\pi}{2\pi T_{ZC}} = \frac{1}{2T_{ZC}}$$

以 $T_{ZC} = 20.48$ μs（$U=1024$，$BW=50$ MHz）为例：
$$f_{CFO, \text{max}} = \frac{1}{2 \times 20.48 \times 10^{-6}} \approx 24.4 \text{ kHz}$$

### 3.3 求解方法

**方法A：网格搜索（粗估）**
```python
delta_phi_range = np.linspace(0, np.pi, 10000)  # 0.3 rad/kHz 分辨率
cost = []
for dp in delta_phi_range:
    c = sum([
        (rho_measured(Mi, Mj) - rho_theory(Mi, Mj, dp))**2 
        for Mi, Mj in all_pairs
    ])
    cost.append(c)

delta_phi_opt = delta_phi_range[np.argmin(cost)]
```

**方法B：非线性拟合（精细）**
```python
from scipy.optimize import minimize

def cost_func(delta_phi):
    return sum([
        (rho_measured(Mi, Mj) - rho_theory(Mi, Mj, delta_phi[0]))**2 
        for Mi, Mj in all_pairs
    ])

result = minimize(cost_func, x0=[0.3], bounds=[(0, np.pi)], method='L-BFGS-B')
delta_phi_opt = result.x[0]
```

---

## 4. 反解真实 CFO

$$f_{CFO} = \frac{\Delta\phi}{2\pi T_{ZC}}$$

代入 $T_{ZC} = 20.48 \times 10^{-6}$ s（$U=1024$，$BW=50$ MHz）：

$$f_{CFO} = \frac{\Delta\phi}{2\pi \times 20.48 \times 10^{-6}} = \frac{\Delta\phi}{1.287 \times 10^{-4}}$$

**单位转换**：
- $\Delta\phi$（弧度）→ $f_{CFO}$（Hz）
- 若需ppm：$\text{ppm} = f_{CFO} / f_c \times 10^6$（$f_c$ 为载频，如 1.4 GHz）

---

## 5. 精度与可靠性评估

### 5.1 拟合残差

检查 $\min(\text{cost})$ 的大小：
- **小**（$< 10^{-3}$）：拟合优秀，$\Delta\phi$ 估计可信
- **中**（$10^{-3} \sim 10^{-2}$）：拟合可接受，但噪声较大
- **大**（$> 10^{-2}$）：拟合失败，可能真实 $f_{CFO} < 3$ kHz（方法失效）

### 5.2 幅度法有效范围

| $f_{CFO}$ | 有效性 | 典型误差 |
|-----------|--------|---------|
| $< 1$ kHz | 失效（$\Delta\rho < 2\%$） | — |
| 1~3 kHz | 弱（中等SNR可行） | 数百 Hz |
| > 3 kHz | 有效 | 数百 Hz ~ 1 kHz |
| > 7 kHz | 非常明显 | 百 Hz 级 |

### 5.3 验证步骤

1. **绘图检查**：
   ```
   plot(measured rho vs theoretical rho for all (Mi, Mj) pairs)
   ```
   应该靠近 45° 线

2. **对比余数 CFO**：
   用 [[B2B频偏估计与OTA校准方案]] 的相位法测出余数 CFO $f_{CFO, \text{rem}}$
   - 若粗估 $f_{CFO}$ 满足 $f_{CFO} \bmod (1/(2 T_{frame})) \approx f_{CFO, \text{rem}}$，则一致✓
   - 否则可能陷入局部极值或数据质量差

3. **重复性**：
   重新采集 M=2,3,5,13 数据，重复步骤1~4，结果应稳定在 ±100 Hz 以内

---

## 6. 实现建议

### 6.1 代码框架

```python
import numpy as np
from scipy.optimize import minimize
from scipy.signal import correlate

def g_function(M, delta_phi):
    """sinc 衰减函数"""
    num = np.sin(M * delta_phi / 2)
    den = M * np.sin(delta_phi / 2)
    return np.where(np.abs(den) < 1e-10, 1.0, num / den)

def rho_theory(Mi, Mj, delta_phi):
    """理论功率比"""
    gi = g_function(Mi, delta_phi)
    gj = g_function(Mj, delta_phi)
    return (Mi**2 * gj**2) / (Mj**2 * gi**2)

def cost_func(delta_phi, measured_ratios, M_pairs):
    """最小二乘成本函数"""
    cost = 0
    for idx, (Mi, Mj) in enumerate(M_pairs):
        rho_meas = measured_ratios[idx]
        rho_theo = rho_theory(Mi, Mj, delta_phi[0])
        cost += (rho_meas - rho_theo)**2
    return cost

# 主流程
M_list = [2, 3, 5, 13]
P_measured = {M: extract_power(M) for M in M_list}  # 步骤1

# 步骤2：功率比
M_pairs = [(2,3), (2,5), (2,13), (3,5), (3,13), (5,13)]
measured_ratios = [P_measured[Mj] / P_measured[Mi] for Mi, Mj in M_pairs]

# 步骤3：拟合
result = minimize(cost_func, x0=[0.3], args=(measured_ratios, M_pairs),
                  bounds=[(0, np.pi)], method='L-BFGS-B')
delta_phi_opt = result.x[0]

# 步骤4：反解 CFO
T_ZC = 20.48e-6  # U=1024 / BW=50MHz
f_CFO = delta_phi_opt / (2 * np.pi * T_ZC)
print(f"估计 CFO: {f_CFO:.1f} Hz")
```

### 6.2 数据预处理注意事项

- **热噪声扣除**：$P_{\text{corrected}} = P_{\text{main}} - \sigma_n^2 / M$
  （$\sigma_n^2$ 可从PDP的低功率bin估计）
- **主径对齐**：确保所有M下都使用同一 peak_bin（或手动对齐）
- **稳定性检查**：6分钟数据可分成6个1分钟段，逐段计算 $\hat{\rho}$ 看是否稳定

---

## 7. 输出图表规范

所有图表输出至脚本同目录的 `output/` 子文件夹。

### 7.1 PNG 1：余数CFO时序对比

**文件名**：`CFO_residual_timeseries.png`

**布局**：3行（频段）× 4列（M值），共12个子图

**单个子图**：
- X轴：帧号（0 ~ N_frames）
- Y轴：余数CFO（Hz），由相邻帧相位差计算：
  $$f_{CFO,\text{rem}}[k] = \frac{\angle(\text{CIR}_k \cdot \text{CIR}_{k-1}^*)}{2\pi T_{frame}}$$
  取主径 bin 处的相位
- 蓝色实线：逐帧余数CFO
- 红色虚线：y = 0
- 标题：`{频段} M={M}`（如 `1400M M=2`）

**行顺序**：1400M / 3600M / 4900M  
**列顺序**：M=2 / M=3 / M=5 / M=13

---

### 7.2 PNG 2-4：PDP热力图（3个频段）

**文件名**：
```
output/PDP_heatmap_1400M.png
output/PDP_heatmap_3600M.png
output/PDP_heatmap_4900M.png
```

**每个文件**：2×2子图（M=2左上，M=3右上，M=5左下，M=13右下）

**单个热力图**：
- X轴：帧号
- Y轴：时延 bin（0~1023）
- 颜色：功率（dB），`imshow` 以每帧 `|CIR[frame, :]|²` 转dB
- Colorbar 标签：`Power (dB)`
- 标题：`{频段} M={M}`

---

### 7.3 PNG 5-7：第1000帧PDP（3个频段）

**文件名**：
```
output/PDP_frame1000_1400M.png
output/PDP_frame1000_3600M.png
output/PDP_frame1000_4900M.png
```

**每个文件**：单折线图，4条曲线

| 曲线 | 颜色 |
|------|------|
| M=2  | 蓝色 |
| M=3  | 绿色 |
| M=5  | 红色 |
| M=13 | 橙色 |

**坐标**：
- X轴：时延 bin（0~1023）
- Y轴：功率（dB）
- 标题：`{频段} - Frame 1000 PDP`
- 图例：`M=2 / M=3 / M=5 / M=13`

---

## 8. 完整工作流示例

```
数据路径：/mnt/win_data/data_mea/data_save/Cali_data/20260402_cfo_mea/

Per 频段（1400M / 3600M / 4900M）:

  Step 1: 加载数据 → CIR
    bin_read.read_bin_to_cir(M=2,3,5,13 各文件)
    → CIR (36000, 1024) complex64，per M

  Step 2: 提取主径功率
    pdp = mean(|CIR|², axis=0)    → (1024,)
    peak_bin = argmax(pdp)
    P^(M) = pdp[peak_bin] - noise_floor

  Step 3: 计算功率比（6组）
    ρ̂(2,3), ρ̂(2,5), ρ̂(2,13), ρ̂(3,5), ρ̂(3,13), ρ̂(5,13)

  Step 4: 非线性拟合
    cost(Δφ) → min  →  Δφ_opt
    f_CFO = Δφ_opt / (2π × 20.48 μs)

  Step 5: 输出图表
    output/CFO_residual_timeseries.png
    output/PDP_heatmap_{频段}.png
    output/PDP_frame1000_{频段}.png

验证：
  - 拟合残差 < 1e-2
  - 粗估 f_CFO mod 50Hz ≈ 余数 CFO（相位法）
  - 精度目标：|Δφ| 误差 ~0.01 rad → f_CFO 误差 ~100 Hz
```

---
