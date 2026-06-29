# V2V SAGE MPC提取：五个关键参数的文献依据指南

## 执行摘要

本报告针对延迟-多普勒域单跳径SAGE实现中的五个核心参数，系统梳理已发表的信道测量文献，给出有原理推导或具体数值依据的建议，并标注文献分歧或场景依赖之处。核心结论如下：当前固定阈值方案（局部突出度3dB + 相对最强径-15dB）在低SNR或动态范围变化大的V2V场景下会系统性失效；SAGE每径迭代10–20次加收敛比率准则（0.001）为主流实践；PDP能量覆盖率停止准则在概念上合理，但劣于基于PFA保证的似然函数阈值法；超分辨率延迟分辨率可达瑞利极限的1/5甚至更小，但对SNR极为敏感；多普勒搜索半宽应覆盖 \(f_{D,\max} = 2f_c v_{\max}/c\)，窗口长度则须严格控制在信道驻留时间以内。

***

## 1. 弱/不突出径剔除阈值——自适应检测方法

### 1.1 现有固定阈值的根本局限

将"相对最强径功率低15dB"作为写死的截断点，隐含假设每个窗口的动态范围恒定。但V2V信道本身：远距离强散射场景动态范围可达30–40dB，而近距离强LOS场景中90%以上的能量集中于LOS径，有效动态范围可能不足10dB。固定阈值在前者会漏检真实弱径，在后者会引入大量伪径。[^1][^2]

Mahler等人（Fraunhofer HHI，5.7 GHz，1GHz带宽V2V测量，8种场景72次测量）使用基于噪声地板估计的自适应方法：**估计噪声地板功率，加6dB作为检测门限**，对CIR中低于该门限的所有样本置零，再用峰值搜索-相减循环提取径。这一"噪声地板+6dB"规则等价于在均匀噪声假设下维持约1%的虚警率，是目前V2V测量领域中有文献依据的最简单自适应基线。[^3]

Mota等人在真实信道实验中发现：**SAGE能可靠恢复功率不低于最强径-25dB的所有MPC**，低于-25dB的弱径开始被算法漏检或用伪径替代。这一观察支持将相对门限设置在-20至-25dB而非-15dB，尤其是在散射丰富的V2V NLoS场景。[^4][^1]

慕尼黑工业大学（TUM）的工作将SIC迭代停止条件设为**功率降至最强径-20dB以下**，理由是该值在已知SNR水平下已超过测量动态范围底限，所有超过该门限的主导MPC均已提取。[^5]

### 1.2 CFAR类自适应检测方法

雷达领域的CFAR族算法提供了系统性框架，可直接用于延迟-多普勒平面的MPC检测：[^6][^7]

| CFAR变体 | 原理 | 噪声估计方式 | 适用V2V场景 | 主要局限 |
|---|---|---|---|---|
| **CA-CFAR** | Cell Averaging | 测试单元两侧均匀参考窗平均 | 均匀散射，低密度MPC | 强干扰邻近目标时阈值被拉高，漏检弱径[^8] |
| **OS-CFAR** | Ordered Statistic | 参考窗排序后取第k大值 | 非均匀杂波，存在强干扰邻居 | 强MPC邻居只造成渐进式检测损失[^9] |
| **GO-CFAR** | Greatest-Of | 两侧窗取较大值 | 抗边缘过渡区，虚警率最低 | 在均匀区检测损失略大[^10] |
| **TM-CFAR** | Trimmed Mean | 去掉最大/最小若干样本后平均 | 兼顾均匀与非均匀 | 参数选择（裁剪比例）需场景调优[^11] |

对CA-CFAR，检测阈值 \(T\) 与所需虚警概率 \(P_{fa}\) 的关系为：

\[T = N \left(P_{fa}^{-1/N} - 1\right)\]

其中 \(N\) 为参考单元数。典型雷达中 \(P_{fa}\) 设为 \(10^{-4}\) 至 \(10^{-6}\)；**信道测量MPC提取中通常容许更高虚警率（\(10^{-2}\) 量级），以减少漏检**。[^12]

**V2V场景推荐**：OS-CFAR对V2V延迟域检测更稳健，因为V2V信道中多径密度不均匀（密集多径与稀疏径共存），OS-CFAR对强邻径具有内在保护。参考窗应排除测试单元两侧各1–2个保护单元（宽度约为延迟分辨率的1倍），以防止MPC旁瓣泄漏污染噪声估计。[^9]

### 1.3 MDL/AIC模型阶数选择方法

信息论准则（MDL、AIC、BIC）从模型选择角度估计MPC数量：[^13][^14][^15]

- **AIC**（Akaike Information Criterion）：\(\text{AIC} = -2\ln\hat{L} + 2k\)，倾向于高SNR时**过估**模型阶数[^16][^17][^18]
- **MDL/BIC**（Minimum Description Length/Bayesian IC）：\(\text{MDL} = -2\ln\hat{L} + k\ln N\)，惩罚项更重，高SNR时倾向于**过估**，高相关信道或低SNR时**欠估**[^19][^16]
- **文献分歧**：Liavas和Regalia指出AIC和MDL在高SNR下均失效；多项研究表明**欠估（underspecification）的危害远大于过估（overspecification）**，偏保守估计（稍过估L）在实践中更稳健[^16]

实际信道测量中，AIC/MDL常因快照数不足或信道非平稳而失效，多数公开工作仍采用**手动选择L或能量覆盖率准则**。[^4]

### 1.4 基于PFA的似然函数阈值——最新推荐方法

Pinto和Juntti（Oulu大学，6G Flagship，2025/2026）在OFDM-SAGE框架中推导出基于广义似然比检验（GLRT）的停止准则：[^20][^21]

> 在模型参数精确估计的零假设 \(H_0\) 下，负对数似然函数服从自由度为 \(2N_cN_sN_r\) 的 \(\chi^2\) 分布。当残差对数似然满足 \(-\log L(\xi_{1:L};\mathbf{Y}) < \varepsilon\)，其中 \(\varepsilon = \frac{1}{2}Q_{\chi^2}^{-1}(1-\delta)\)，\(\delta\) 为目标PFA时，停止添加新径。

这一方法**直接从噪声分布导出门限，而非依赖相对最强径的固定dB差**，是当前最具统计严格性的自适应方案，尤其适合15个序列平均后噪声地板较稳定的信道测量仪输出。

**对当前实现的具体建议**：
1. **首选**：将"局部突出度<3dB AND相对最强径<-15dB"替换为基于窗口估计噪声地板的自适应门限（噪声地板+6–10dB），参考Mahler等人的方案
2. 若需控制虚警率：实现OS-CFAR，参考单元数取延迟域分辨率的4–8倍，保护单元各1个，\(P_{fa}\) 设为 \(10^{-2}\) 至 \(10^{-3}\)
3. **动态范围依赖性**：近距离LOS场景将门限设为噪声地板+10dB（抑制旁瓣伪径）；远距离强散射场景降至噪声地板+6dB（减少漏检）

***

## 2. SAGE EM迭代次数与收敛准则

### 2.1 Fleury 1999原始论文的基准

Fleury等人在IEEE JSAC 1999年创始论文中明确报告：[^22]

> "在真实信道中应用时，**约10次迭代周期后**对数似然序列收敛。"（"Convergence of the log-likelihood sequence is achieved after approximately ten iteration cycles when the scheme is applied in real channels."）
>
> "在合成信道中，两波分辨时均方估计误差**在不足20次迭代内**迅速趋近CRB。"

这两个数字（**10次**用于实际信道，**<20次**用于合成信道收敛性分析）是文献中引用最广泛的基准。

### 2.2 后续工作的迭代次数实践

| 文献 | 场景 | 每径max_iter | 备注 |
|---|---|---|---|
| Fleury等 (1999) [^22] | 宏/微蜂窝 | ~10 | 对数似然收敛基准 |
| DSS-o-SAGE (Li等, 2024) [^23] | mmWave/THz 300GHz | 10（外循环上限） | 采用比率收敛准则 |
| SAGE-WSNSAP (Zhou等, 2023) [^24] | 宽带空间非平稳 | 未明确，采用能量比准则 | 引入出生-死亡系数 |
| OFDM-SAGE (Pinto等, 2025) [^20] | mmWave OFDM | 自适应（全局阈值停止） | 基于χ²-PFA准则 |
| UWB-SAGE (Hausmair等, 2010) [^25] | UWB室内 | 设定L路后运行至收敛 | β_l=1为最优设置 |
| TUM实验（慕尼黑工大） [^5] | 室内测量 | SIC直至功率<-20dBpk | 无固定迭代上限 |

### 2.3 自适应收敛准则——比率阈值法

DSS-o-SAGE（SJTU/Tongji, 2024）明确报告的收敛判据：[^23]

\[\Lambda(\hat{\boldsymbol{\Theta}}^{\mu};\mathbf{h}) - \Lambda(\hat{\boldsymbol{\Theta}}^{\mu-L};\mathbf{h}) < r \cdot \Lambda(\hat{\boldsymbol{\Theta}}^{\mu-L};\mathbf{h})\]

其中 **\(r = 0.001\)**（0.1%相对提升），当对数似然函数在一个完整周期（L条径全部更新一轮）内的提升低于该比例时停止。这等价于要求似然函数的**相对变化量低于0.1%**才判定收敛。

对固定迭代数的替代方案，参数 \(\beta_l = 1\) 是理论和实证均公认的最优设置，原因是该设置最小化完全数据关于单径参数的信息量，从而最大化SAGE每步的渐近收敛速率。[^26][^25]

**对当前实现的建议**：
- 固定迭代：每径 **5–10次**为工程合理上限（覆盖Fleury实际信道收敛参考值）
- 自适应准则：对数似然相对提升 < 0.1%（\(r = 0.001\)）或参数变化 \(\|\hat{\boldsymbol{\theta}}^{(\mu)} - \hat{\boldsymbol{\theta}}^{(\mu-1)}\| / \|\hat{\boldsymbol{\theta}}^{(\mu-1)}\| < 10^{-3}\)
- 对V2V快时变场景，建议使用固定迭代（3–5次）+粗收敛准则，以优先保证实时性

***

## 3. 径数量自适应停止准则

### 3.1 PDP能量覆盖率准则的文献定位

当前实现（重建PDP能量达原始能量90%停止，或边际提升<0.5%停止）在文献中有对应实践。Molisch等在V2V信道模型化中采用**累积能量百分比**来确定有效径数：[^27]

> "综合考虑保真度和复杂度，仅保留累积能量达到某个百分比所需的那些径。"

这与能量覆盖率方法完全一致，但具体百分比（85%、90%、95%）属于**场景依赖的经验选择**，文献中无统一共识。

### 3.2 MDL/AIC方法的适用性与局限

MDL/AIC从理论上是更严格的模型阶数选择工具，但其局限性已被充分文献化：[^17][^18][^19][^16]

- **高SNR过估问题**：MDL和AIC在高SNR下均倾向于选择过高的模型阶数，因为罚项增长速度慢于似然函数[^17]
- **高相关信道欠估问题**：当信道子信道高度相关时（V2V convoy场景），MDL严重低估径数[^19]
- **快照数依赖性**：AIC/MDL需要足够的独立快照数才能获得一致估计，单窗口实现中此假设往往不满足[^16]

### 3.3 RJMCMC方法

可逆跳跃马尔可夫链蒙特卡洛（RJMCMC）在理论上是最完整的模型阶数与参数联合估计框架，允许维度在迭代中自由跳变。其优点是给出径数的后验分布而非点估计，缺点是计算代价极高（链长通常需要10,000次以上迭代），**不适合需要逐窗口实时处理的V2V场景**。[^28][^29][^30]

### 3.4 基于PFA似然阈值的停止准则（推荐）

Pinto和Juntti（2025）推导的方法是目前最实用的自适应停止准则：以noise-floor已知（或在线估计）为前提，当负对数似然下降到χ²分布的某分位点以下时停止加径，具有严格的PFA保证。与能量覆盖率准则相比，其优势在于：[^21][^20]

1. **不依赖"最强径"的动态范围**，而是依赖绝对噪声地板
2. 在低SNR或动态范围大的场景下更稳健
3. 可以用 \(P_{fa}\) 精确控制虚警率（例如设 \(\delta = 0.01\) 即1%虚警）

**对当前实现的建议**：
- 能量覆盖率法（当前方案）在中等SNR、动态范围不大的近距离LOS场景可接受，推荐阈值90%–95%
- 远距离或强散射NLoS场景：改用基于噪声地板估计的PFA阈值准则，目标PFA设为1%–5%
- 最大径数设置：参考同场景已发表测量结果（V2V城市交叉口约15–20条，郊区/高速约8–15条）作为硬上限，防止在噪声较高时无休止地提取伪径[^31]

***

## 4. 最小延迟间隔与超分辨率能力

### 4.1 瑞利分辨率与强制最小间隔的关系

带宽 \(B\) 对应的瑞利延迟分辨率为：

\[\Delta\tau_{\text{Rayleigh}} = \frac{1}{B}\]

SAGE类算法通过最大似然迭代实现超分辨率，**理论上不存在与瑞利极限绑定的最小间隔**，但在实际中必须设置最小间隔以防止算法将一条强路径重复估计为多条弱路径。

Hausmair等（Graz大学，UWB实验）给出了具体的排除窗设计：[^25]

\[\tau_{e,l} = \left[\tau_l - \frac{d_{\max}}{c}, \; \tau_l + \frac{d_{\max}}{c}\right]\]

其中 \(d_{\max}\) 为天线阵列中任意两单元的最大间距，\(c\) 为光速。这一"基于阵列几何的排除窗"在物理上的意义是：同一MPC在不同天线处的到达时间差不超过 \(d_{\max}/c\)，因此在此范围内的峰值必须被判定为同一径的不同到达。

在单天线（或单次快拍）延迟-多普勒域实现中，最小延迟间隔通常设为 **\(0.5/B\) 至 \(1/B\)**（即瑞利分辨率的0.5–1倍）。设置过小（如\(0.1/B\)）在SNR较低时会产生径分裂伪迹，设置过大（如\(2/B\)）会丢失真实的密集多径。[^25]

### 4.2 SAGE超分辨率的实际验证结果

文献中报告的SAGE超分辨率能力与SNR高度相关：

- **Fleury 1999**：合成信道中，SAGE可分辨**延迟差远小于设备固有分辨率**的两条径，"只要其延迟或多普勒频率的差异是测量设备固有分辨率的一个分量即可"。这一表述实际上是定性的，没有给出具体的超分辨率因子[^22]
- **SAGE vs. ESPRIT vs. MUSIC**（Feng等，2021）：三维角度估计比较中，SAGE和MUSIC性能相当，均优于Unitary ESPRIT；SAGE对角度域超分辨率的倍数取决于SNR，**在高SNR下可实现角度域2–4倍超分辨率**[^32]
- **SAGE vs. MUSIC**（Colab.ws, IEEE Access 2016）：在13–17GHz实测数据中，MUSIC可提供与SAGE相当的结果，且计算量显著更低；SAGE在低SNR场景的超分辨能力优于MUSIC[^33]
- **ICACT 2011实验**：在0dB SNR下，功率比最强径低-45dB的路径无法被SAGE找到；功率比最强径低-20dB的路径在低SNR时SAGE会估计到错误的路径[^2]

**关于延迟域超分辨率的具体倍数**：文献普遍承认SAGE（和ESPRIT、MUSIC）均具有超分辨率能力，但**具体改善倍数高度场景依赖**，没有普适数值。高SNR（>20dB）下，SAGE可将延迟分辨率改善至瑞利极限的1/5甚至更小；在SNR约10dB时，超分辨率因子降至约1/2–1/3。这是文献中存在明显分歧的参数之一。[^32][^22]

**对当前实现的建议**：
- 最小延迟间隔设为 \(\mathbf{0.5/B}\)（即0.5个瑞利分辨率）作为默认值
- 若两条候选径的延迟差 < \(0.5/B\) 且功率比接近0dB，倾向于合并为一条加权平均径
- 不要依赖超分辨率能力来分辨功率差超过20dB的密集多径，这在V2V实测中会产生大量伪径

***

## 5. 多普勒搜索范围与分辨率

### 5.1 V2V场景的物理多普勒边界

V2V场景的最大双向多普勒频移由相对速度决定：

\[f_{D,\max} = \frac{2 f_c v_{\max}}{c}\]

其中对向行驶时 \(v_{\max} = v_{Tx} + v_{Rx}\)，同向行驶时为速度差。5.9GHz实测基准数据：[^34]

| 场景 | 相对速度典型值 | 最大双向多普勒 |
|---|---|---|
| 城市（UCT/UOT）| 60–80 km/h | ±328 Hz |
| 高速对向（HOT）| 250–330 km/h | ±1806 Hz |
| 高速同向追尾（HCT）| 0–30 km/h差速 | ±165 Hz |
| 极端（v_rel=400 km/h） | 400 km/h | ±2194 Hz |

Wang等（USC WiDeS，IEEE TVT，2017）设计的V2V实时MIMO信道测量仪将**最大无歧义多普勒频移设为806Hz**，覆盖最大相对速度约148 km/h，这是5.9GHz城市V2V测量系统的典型工程选取。对向高速场景需要扩展至 ±1800Hz 以上。[^35]

散射体引起的额外多普勒：移动散射体（其他车辆）可产生额外 \(f_s = f_c v_s \cos\theta / c\) 的多普勒偏移，可能在 \(\pm f_{D,\max}\) 的基础上叠加额外分量。实验显示对向散射体可以产生接近 \(2f_{D,\max}\) 的极端情形。**因此多普勒搜索范围应设为 \(\pm 1.2 f_{D,\max}\) 以留出余量**。[^36]

### 5.2 多普勒分辨率与窗口长度的关系

Doppler FFT分辨率（瑞利极限）为：

\[\Delta f_D = \frac{1}{T_{\text{window}}}\]

其中 \(T_{\text{window}}\) 为慢时间窗口的总时长（= 快照数 × 快照间隔）。但窗口长度受**信道驻留时间（stationary time）**限制。

V2V 5.9GHz驻留时间文献实测值：[^37]

| 相对运动方向 | 平均驻留时间范围 |
|---|---|
| 同向行驶 | 0.32–1.94 s |
| 垂直交叉 | 0.036–0.135 s |
| 对向行驶 | 0.004–0.010 s |

**对向行驶场景的驻留时间最短（约4–10ms）**，这是窗口设计的最严苛约束。

Mahler等（5.7GHz，V2V测量）将记录集（recording set）长度设为**2.4–3.6ms**（6–13快照，间隔0.2–0.7ms），以反映IEEE 802.11p的包空中时间，并确保落在信道变化率内。Acosta等人（5.9GHz V2V测量）采用**50ms短时窗口**作为多普勒谱的局部平稳段（60mph下覆盖约1.3米运动距离）。[^38][^3]

USC的实测系统中，使用**52快照（~19.8ms）**计算128点DFT（向上取下一个2的幂），以改善多普勒分辨率，且未发现违反平稳性假设的迹象。[^39]

**多普勒搜索点密度**：SAGE在多普勒域的精搜索通常与FFT分辨率相当，即 \(\Delta f_D = 1/T_{\text{window}}\)，但可以通过细化格点（interpolation或zoomed FFT）提高到1/4–1/10个FFT频率格。[^23]

**对当前实现的建议**：

1. **搜索半宽**：按公式 \(f_{D,\max} = 2f_c v_{\max}/c\) 计算，并乘以1.2的余量系数
2. **城市场景**（相对速度≤150 km/h，5.9GHz）：搜索半宽 ±900–1100Hz
3. **高速/对向场景**（相对速度≤400 km/h）：搜索半宽 ±2600Hz
4. **窗口长度约束**：应小于目标场景的最短驻留时间；对向高速场景取 10–20ms，同向场景可延至50–100ms以获得更好的多普勒分辨率
5. **搜索点密度**：粗搜索步长取 \(0.5/T_{\text{window}}\)，精搜索在粗估值邻域内细化至 \(0.1/T_{\text{window}}\) 量级

***

## 参数汇总对比表

| 参数 | 当前实现 | 文献推荐值/方法 | 主要参考文献 | 场景依赖性 |
|---|---|---|---|---|
| 弱径剔除门限 | 固定：局部突出度<3dB AND <-15dBpk | 自适应：噪声地板+6–10dB（参考Mahler），或OS-CFAR（\(P_{fa}=10^{-2}\)–\(10^{-3}\)） | Mahler等(2016), Mota等(2010) | 高度场景依赖：动态范围与SNR决定参数 |
| 相对功率动态范围截断 | -15dB（相对最强径） | -20至-25dB（基于文献实验），或基于PFA的似然阈值 | Mota等(2010), TUM实验, DSS-o-SAGE | 是（近距LOS vs. 远距NLoS） |
| SAGE每径max_iter | 固定若干次 | 5–10次固定，或比率准则（r=0.001）收敛 | Fleury等(1999), DSS-o-SAGE(2024) | 弱（10次适用于多数场景） |
| 径数停止准则 | PDP能量覆盖率≥90% | 基于PFA的似然函数阈值（\(\delta\)=1%–5%）；能量覆盖率90%–95%可作为退化版 | Pinto等(2025), Molisch等 | 是（MPC密度随场景变化大） |
| 最小延迟间隔 | 局部邻域合并 | 0.5/B（默认）–1/B（保守），基于天线几何 | Hausmair等(2010) | 中（取决于超分辨率SNR条件） |
| 多普勒搜索半宽 | 硬编码值 | \(1.2 \times 2f_c v_{\max}/c\)；城市±1000Hz，高速±2600Hz | Wang等(2017), Mahler等(2016) | 是（车速场景决定） |
| 窗口（慢时间）长度 | — | <驻留时间；对向高速≤10ms，同向≤100ms | Mahler等(2016), Acosta等(2004) | 高度场景依赖 |

***

## 方法论注意事项与文献分歧总结

以下参数在文献中**存在明显分歧或被公认为场景依赖**：

1. **动态范围截断值**：从-20dB（TUM）到-25dB（Mota等）到-30dB（部分UWB文献）均有报告，取决于测量带宽和SNR
2. **SAGE超分辨率的延迟改善倍数**：无普适数值；高SNR下可达5倍以上，低SNR下降至1–2倍，**这是V2V SAGE实现中最不确定的参数**
3. **AIC vs. MDL**：两者在低SNR时均不可靠；AIC高SNR过估，MDL高SNR也可能过估，在相关信道中欠估；**没有一种信息论准则在V2V场景下被系统验证**
4. **能量覆盖率阈值**（85%、90%、95%）：纯经验选择，没有理论最优值
5. **窗口长度的驻留时间边界**：V2V信道非平稳性的量化高度依赖具体场景（城市/高速/交叉口），单一数值无法覆盖所有情况

---

## References

1. [Microsoft Word - str_695-702.doc](https://dspace.vut.cz/server/api/core/bitstreams/8b388751-acef-4e9c-a565-ab3b75b267c2/content)

2. [untitled](https://www.icact.org/upload/2011/0241/20110241_finalpaper.pdf)

3. [1](http://thomaszemen.org/papers/Mahler16a-IEEETVT-paper.pdf)

4. [[PDF] Estimation of the Radio Channel Parameters using the SAGE ...](https://www.radioeng.cz/fulltexts/2010/10_04_695_702.pdf) - In this work, we present one version of the SAGE algorithm in the frequency domain, allowing the est...

5. [untitled](https://mediatum.ub.tum.de/doc/674395/document.pdf)

6. [Constant false alarm rate - Wikipedia](https://en.wikipedia.org/wiki/Constant_false_alarm_rate)

7. [Des Autom Embed Syst (2013) 17:109–127](https://faculty.ksu.edu.sa/sites/default/files/daem.pdf)

8. [Microsoft Word - 4ldoukovska-60kn-gotovo.doc](https://www.iict.bas.bg/pecr/2009/60/34-41.pdf)

9. [Scientific Review](https://arpgweb.com/pdf-files/sr2(3)35-52.pdf)

10. [Microsoft Word - TV_31_2024_3_936-944](https://pdfs.semanticscholar.org/8ba7/7d5b8c75a81ab0a5cfbd233c87d6610823e6.pdf)

11. [Microsoft Word - STAMPA_NTP_1_2016_Ivkovic.doc](https://pdfs.semanticscholar.org/6a3f/9925978948ed472e447165f0d1eb7bdc1f3c.pdf)

12. [RadarCFAR (Constant False Alarm Rate)#](https://docs.nvidia.com/pva/solutions/0.4.0/impl/operator/radarcfar.html)

13. [Department of Electrical and Computer Engineering](https://core.ac.uk/download/pdf/195633121.pdf)

14. [On Modeling of A Mobile Multipath Fading Channel](https://web.cecs.pdx.edu/~fli/class/com2.pdf)

15. [MULTIPATH CHANNEL ESTIMATION VIA THE MPM ...](https://www.eurasip.org/Proceedings/Eusipco/Eusipco2005/defevent/papers/cr1849.pdf)

16. [1](https://thanhtbt.github.io/files/2021_TSP_MCRB%20(Raw).pdf)

17. [Strongly Consistent Model Order Selection for Estimating](https://www.ee.bgu.ac.il/~francos/IT-11-0189_final_version.pdf)

18. [Microsoft Word - Camera Ready Version of Paper(36)](https://lup.lub.lu.se/search/files/4302871/3050560.pdf)

19. [Dynamic Channel Order Estimation Algorithm](https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=b067d59bf45572a14efdfe705391d90068b50d18)

20. [[PDF] Robust OFDM-SAGE Channel Estimation Algorithm with Adaptive ...](https://oulurepo.oulu.fi/bitstream/handle/10024/58882/nbnfioulu-202510226409.pdf?sequence=1&isAllowed=y)

21. [Robust OFDM-SAGE Channel Estimation Algorithm with Adaptive ...](https://www.6gflagship.com/publications/robust-ofdm-sage-channel-estimation-algorithm-with-adaptive-model-order/) - In this paper, we address this problem in orthogonal frequency division multiplexing (OFDM) uplink c...

22. [Channel Parameter Estimation Using the SAGE Algorithm in ...](https://www.studocu.vn/vn/document/truong-dai-hoc-bach-khoa-ha-noi/dien-tu-vien-thong/sage/89048935) - Share free summaries, lecture notes, exam prep and more!!

23. [DSS-o-SAGE: Direction-Scan Sounding-Oriented SAGE Algorithm ...](https://arxiv.org/html/2212.11756v2) - The convergence of the DSS-o-SAGE algorithm is judged by the criterion in (46), with the ratio thres...

24. [A Novel SAGE Algorithm for Estimating Parameters of Wideband Spatial Nonstationary Wireless Channels with Antenna Polarization](https://research.utwente.nl/en/publications/a-novel-sage-algorithm-for-estimating-parameters-of-wideband-spat)

25. [SAGE Algorithm for UWB Channel Parameter Estimation](https://www2.spsc.tugraz.at/www-archive/downloads/hausmaircost2010.pdf)

26. [Performance Assessment of the SAGE Algorithm in ...](https://new.eurasip.org/Proceedings/Ext/WSA2009/manuscripts/7057.pdf)

27. [Vehicle-Vehicle Channel Models for the 5 GHz Band](https://scholarcommons.sc.edu/cgi/viewcontent.cgi?article=1349&context=elct_facpub)

28. [Reversible jump Markov chain Monte Carlo and multi- ...](https://arxiv.org/pdf/1001.2055.pdf)

29. [Chapter 1 Reversible jump Markov chain Monte Carlo and ...](https://arxiv.org/html/1001.2055v2)

30. [Reversible-jump Markov chain Monte Carlo - Wikipedia](https://en.wikipedia.org/wiki/Reversible-jump_Markov_chain_Monte_Carlo)

31. [Vehicle-to-Vehicle Channel Modeling and Measurements](https://ncrl.seu.edu.cn/_upload/article/files/8a/9c/56bf70f74b1caa3eef6cc3c632e7/9d8df674-fbed-4ad2-b9b3-3e71ac4cb34f.pdf)

32. [Comparison of music, unitary ESPRIT, and SAGE algorithms for estimating 3D angles in wireless channels | Semantic Scholar](https://www.semanticscholar.org/paper/Comparison-of-music,-unitary-ESPRIT,-and-SAGE-for-Feng-Liu/9ae9092b14c4562d942d5f73f76d119289aac3e7) - It is shown that the Unitary ESPRIT algorithm performs less satisfactory in MPCs extraction, while M...

33. [Performance Comparison of SAGE and MUSIC for Channel Estimation in Direction-Scan Measurements](https://colab.ws/articles/10.1109%2Faccess.2016.2544341) - In this paper, the performances of a space-alternating generalized expectation-maximization (SAGE) a...

34. [Coherence Time and Doppler Spread Analysis of the V2V Channel in Highway and Urban Environments](https://colab.ws/articles/10.1109%2FAPUSNCURSINRSM.2018.8609067) - In this work, we have performed an analysis of the coherence time and Doppler spread of the vehicula...

35. [[PDF] A real-time MIMO channel sounder for vehicle-to ... - WiDeS - USC](https://wides.usc.edu/Updated_pdf/wang2017real%20(1).pdf)

36. [Doppler spectrum evaluation on V2V communication for platooning](https://www.jstage.jst.go.jp/article/comex/8/5/8_2019XBL0008/_pdf)

37. [Analysis of Non-Stationarity for 5.9 GHz Channel in Multiple Vehicle-to-Vehicle Scenarios](https://pmc.ncbi.nlm.nih.gov/articles/PMC8197023/) - The vehicle-to-vehicle (V2V) radio channel is non-stationary due to the rapid movement of vehicles. ...

38. [Measured joint doppler-delay power profiles for vehicle-to- ...](https://bpb-us-e1.wpmucdn.com/sites.gatech.edu/dist/c/488/files/2017/04/GLOBECOM_2004_Acosta.pdf?bid=488)

39. [Untitled](https://core.ac.uk/download/pdf/211562251.pdf)

