# SAGE与HRPE多径估计中主径吸附、伪检与PDP脊线失配的深度调研

## 研究结论

围绕你描述的七类症状，文献给出的主线答案非常一致：**问题的根源通常不是“路径数不够”本身，而是前向模型过粗、残差模型过白、初始化过于偏向强径、以及窗口内时变性被忽略**。经典 SAGE 文献之后的 RiMAX/HRPE 研究，正是沿着这四条线改进：一方面把**测量系统响应**和**连续时延**写进 path atom，另一方面把**不可分辨的剩余能量**建模成 DMC 或 colored noise，并在初始化、模型阶数控制和时变跟踪上加上更强的约束与可靠性判据。只要仍把单径写成“单个 delay bin 的 delta”，主径附近的主瓣/旁瓣与系统脉冲裙边就很难被完整减除，后续估计自然会继续“吸附”到主径附近；而如果再用更激进的 PDP 辅助初值去补召回，通常就会把噪声、DMC、旁瓣和插值误差一起召回，表现成一堆 -25 到 -35 dB 的“弱径”。citeturn23view0turn37view0turn22view1turn35view0turn27view0

第二个核心结论是：**PDP waterfall 里肉眼可见的 ridge，并不等价于“可分辨 specular MPC”**。RiMAX 的基本思想就是把观测分成 deterministic specular mean 和 structured stochastic remainder；后者就是 dense multipath component。后续 DMC 文献进一步指出，DMC 既可能占总功率的大头，也可能在**和 specular 相近的 delay/angle 附近聚集**，因此在功率图上形成明显 ridge，但未必值得被解释成单条稳定、相干、在窗口内参数恒定的 specular path。对于快时变场景，跟踪文献也反复强调：路径可能在快照间出现/消失、时延慢漂、局部不满足平稳性，因此“看得见峰值”与“适合在固定窗口里用恒定 delay/Doppler 模板去拟合”是两件不同的事。citeturn37view0turn45view0turn41search1turn43view5turn39view0

如果只用一句话概括对你实现最重要的修改，那就是：**把 delta-bin SAGE 改成“连续 delay 的校准 pulse-shape atom + DMC/colored residual + residual-domain 初始化 + 轨迹级剪枝”**。这不是“锦上添花”的精修，而是从文献角度看最接近 RiMAX/现代 HRPE 的最低可用版本。citeturn37view0turn42view0turn40view2turn8view1turn38view0

## 正确的信号模型

经典 SAGE 在信道参数估计里的本意，并不是把单径直接当作观测域里一个“单 bin 冲激”。在后续可访问的宽带/超宽带 SAGE 文献里，这一点非常清楚：单条路径写成**已知发射/探测脉冲的连续时移版本**。例如 Hausmair 等人的 UWB SAGE 明确采用
\[
s(t;\theta_l)=c(\phi_l)\,\alpha_l\,p(t-\tau_l),
\]
其中 \(p(t)\) 是已知宽带脉冲，\(\tau_l\) 是**连续**时延参数；Steinböck 等人的 SAGE/HRPE 信号模型同样把单径写成 \(u(t-\tau_l)\) 的形式，而不是 delay-bin delta。RiMAX 进一步强调：**数据模型必须同时表示传播过程和测量设备影响**，模型选得正确与否直接决定可靠性与分辨力。citeturn42view0turn23view0turn37view0

把这些模型降维到你的**单天线 delay–Doppler**问题，最自然的写法其实是下面这种 RiMAX 风格的 reduced model：
\[
y_m(\tau)=\sum_{l=1}^{K}\alpha_l\,e^{j2\pi \nu_l mT}\,g(\tau-\tau_l)+d_m(\tau)+w_m(\tau),
\]
或者在频域写成
\[
Y_m(f)=\sum_{l=1}^{K}\alpha_l\,G(f)\,e^{-j2\pi f\tau_l}e^{j2\pi \nu_l mT}+D_m(f)+W_m(f).
\]
这里的 \(g(\cdot)\) 或 \(G(f)\) 不该是理想 delta 的变体，而应当是**你的 sounding sequence、模数链路、窗口、匹配滤波器、系统脉冲响应共同形成的有效 atom**。这一写法不是凭空“工程直觉”，而是 Hausmair 的脉冲模型、Steinböck 的 \(u(t-\tau_l)\) 模型，以及 RiMAX/宽带 HRPE 对“把 measurement device 写入前向模型”的直接推论。citeturn42view0turn23view0turn37view0turn27view0

这也解释了你最困扰的 **fractional delay** 问题。宽带 HRPE 新文献明确指出，窄带假设一旦失效，频率响应与天线/设备响应不再能被简单地“独立校准后忽略”，否则就会形成**model mismatch**，使估计偏置且方差界必须从 CRB 转向 MCRB。与此相呼应，VB-SAGE/IARD 文献还直接指出：在离散信号实现里，色散参数目标函数需要在采样点之间插值；插值误差会留下 residual interference，并表现为 fictive components 或对模型稀疏度的高估。换句话说，**你用单个 delay bin 去替代连续 pulse-shape atom，本质上就是一种 basis mismatch**。citeturn27view0turn9search2turn22view1turn22view0

因此，对你的实现，path atom 的正确方向不是“再细分 delay bin”，而是**先标定 1D effective pulse，再对它做连续时移**。最直接的工程实现，是用直连/through/稳定 LOS 参考测量得到匹配滤波后的有效脉冲 \(g\)，对它做过采样，然后用 sinc、fractional-delay FIR，或者频域相位斜坡 \(e^{-j2\pi f\tau}\) 来实现连续 \(\tau_l\)；关键不是具体插值器，而是**合成与减除时必须使用同一个 bandlimited pulse atom**。这一步通常比增加 max_paths 更能减少“主径吸附”。citeturn37view0turn42view0turn22view1

## PDP脊线、specular 与 DMC 的关系

RiMAX 的基本观测模型可以概括为：**specular mean + DMC covariance + white noise**。Springer 的最新综述章节把这一点写得非常清楚：均值由 specular paths 表示，残差 \(\mathbf r=\mathbf y-\mathbf s(\theta)\)，而对数似然显式依赖 structured covariance \(\mathbf R\)；RiMAX 与 pyMAX 都属于这种 maximum-likelihood framework。更早的 RiMAX 论文也明确提出：估计对象不仅包含 specular path 参数，还包含 dense multipath components，并给出额外的 reliability measures 来增强稳健性。citeturn8view1turn37view0

这类模型之所以重要，是因为 DMC 并不是“噪声地板上的小尾巴”，而是**不可分辨散射能量的主体候选**。Schieler 等人把 DMC 解释为大量 SC 在有限带宽和有限 SNR 下无法分辨时形成的 colored Gaussian remainder；早期 Lund/Aalto 一系工作则给出了更直观的测量发现：DMC 是无法由 distinct plane waves 的叠加来表征的那部分能量，它在 LOS/NLOS 下都存在，而且**随 TX–RX 距离增加而占比上升**；在另一篇室内测量论文中，DMC 占总功率甚至可从约 10% 到 95% 变化，且通常在 NLOS 下更高。citeturn35view0turn45view0turn41search1

更关键的是，Lund 的那篇 DMC 特性论文还指出，**DMC 的能量往往集中在和 specular components 相近的 angles 和 delays 上**。这对你的问题几乎是“对号入座”：PDP waterfall 里一条清晰 ridge，完全可能是“若干可分辨 specular + 一团同 delay 附近的 dense energy + 系统脉冲形状”叠加后的结果。功率图上它会很清楚，但如果你强迫 SAGE 在一个固定 50 帧窗口里只用“常 delay、常 Doppler、单个 delta-like atom”去解释它，算法未必会把它认作一条单独的稳定 specular path。citeturn45view0turn37view0turn35view0

此外，**PDP 是功率域可见性，HRPE 是相干模板可辨识性**，二者天然不同。Mahler 等人的 V2V 小尺度 tracking 论文明确说，由于车辆信道在快照之间会出现非平稳行为，例如 MPC 的出现/消失和 delay 变化，他们宁愿把每个 measurement snapshot 当作独立处理步骤，而不是依赖需要多快照平稳性的 ESPRIT/MUSIC 类方法；Wang 等人的 V2V HRPE 论文也强调，在快时变 V2V 场景中，新路径检测放在快照末尾、在先把当前参数“打磨”好之后再看 residual，会更稳定。你的 50 帧固定窗口如果已经能看见 ridge 缓慢漂移，那么它对 PDP 可见，对“固定 delay/Doppler 的窗口内相干拟合”却未必有利。citeturn43view5turn40view1turn40view3

最后，还要警惕**模型错误本身会制造“可见脊线”**。Landmann 等人关于不准确阵列/系统模型的研究给出过非常强的提醒：错误的模型阶数或不准确的数据模型会让 ML 过程产生 non-physical/ghost specular components；在他们的单径仿真里，ghost SC 的最大功率大约可落在真路径以下 25 dB 左右，且会形成看似“参数扩散/簇化”的结构。那篇论文研究的是阵列模型误差，但对你的一维问题，**未建模的 pulse shape、旁瓣与分数时延误差很可能产生同类 ghost tap**；这是我基于相同 ML 机理给出的推论。citeturn31view0

## 初始化、主径吸附与弱径召回

关于你说的 **path crowding / 主径吸附**，Steinböck 等人的初始化论文几乎就是在直接回答这一问题。它明确指出：经典 SAGE/SIC 的实现是通过最小化 residual 的 \(L_2\) 范数来工作的，因此估计会聚集到 PDP 早期、高功率区域；ISIS 虽然引入了 delay bins 来改善搜索效率，但如果最终仍按“最强分量优先”选取，依然不能解决早期高功率段的路径聚集问题。该文提出的出发点就是：如果你希望在**整个 PDP 范围**内提取路径，而不是只把前面的大峰剥到极致，就必须重构初始化和搜索程序。citeturn23view0

那篇文献给出的改进思路与你正在尝试的“PDP-assisted initialization”高度相关，但比“看峰就加初值”更结构化。它提出了三类方法：一类是在**valid-power delay regions** 内做带灵活边界的 delay bins；一类是在这些区域中找 **PDP 的局部极大值**；还有一类是在二维 profile 上找局部极大值。作者也提醒，如果平均 PDP 过于 peaky，就会得到过多 maxima。也就是说，**PDP 辅助初始化是文献认可的方向，但需要在有效区域、峰数量、局部抑制与后续验证上加限制**，否则就会提高伪检率。citeturn23view0

在快时变 V2V 场景里，Wang 等人又把初始化往前推了一步。他们指出，对单条 specular path 做多维全局网格搜索很贵，因此很多旧方法把搜索拆到单独维度里做；这样虽然省算力，却损失了 joint multi-dimensional correlation gain，容易导致**weak SP 的 misdetection**。他们提出的办法是在大网格上先找 correlation peak，再在小网格上做 zoom refinement，并按照 SNR 降序检测、估计和减除，直到最大相关值低于阈值或路径数达上限。对你的 delay–Doppler 单天线问题，这个思路几乎可以原样迁移：**先做 residual-domain 的联合 delay–Doppler 相关峰搜索，再做局部细化，而不是把 delay 提议和 Doppler 提议完全拆开。**citeturn40view2

更有价值的是，Wang 等人没有把“新路径出生”放在旧 RiMAX 那样的快照开头，而是放在**当前快照参数都重新优化完之后**，再去分析 residual；作者明确说，在典型 fast time-varying V2V channel 里，这样做更稳定。结合你的症状，这意味着一个很实用的实现原则：**先用 calibrated pulse atom 把当前强径与已确认弱径尽可能解释干净，再在 whitened residual 上找新路径。** 如果在主径还没被正确剥离时就把 PDP maxima 全灌进 SAGE，主径裙边、DMC 峰和噪声局部峰都会混进初值池。citeturn40view1turn40view3

因此，我建议你的初始化不要在“纯 2D FFT 强峰”与“纯 PDP-assisted”之间二选一，而是采用**混合但分层**的策略：先对已有路径做联合再优化；再在 residual 上做 delay–Doppler correlation search；最后只从 robust PDP 的晚时延区域补充少量局部峰作为 birth proposals，用来覆盖 strongest-first 容易漏掉的弱晚径。若你观察到 residual 中存在多个明显的 diffuse 延迟团，而不是单一指数衰减尾巴，那么 recent DMC work 提醒你，**单模态 DMC 初始化本身也会失败**，甚至会进一步偏置 specular path。citeturn40view2turn35view0

## 模型阶数、剪枝与时变跟踪

就 **model order selection / pruning** 而言，文献共识不是“找一个万能阈值”，而是**把多个可靠性指标叠加使用**。RiMAX 2004 就已经强调会计算额外 reliability measures；Springer 2025 的综述更进一步指出，在 model misspecification 显著时，单纯依赖传统 CRB 会留下许多 unphysical paths，而引入 **MCRB** 做模型阶数控制可以明显减少这些不物理的估计结果。也就是说，你的 path pruning 最好不是只按功率剪，而是把**统计可靠性、模型失配和物理 plausibility** 同时纳入。citeturn37view0turn8view1

经典的外层阶数控制当然还包括 **AIC/BIC/MDL** 一类信息准则。Lund 的 BP tracking 论文明确把 AIC/BIC 列为 classical model-order detection 方法；但 VB-SAGE/IARD 这条线的结论很值得你注意：在 super-resolution multipath estimation 里，若离散实现存在插值误差或 basis mismatch，**SAGE-BIC 这类方法本身也可能引入越来越多 fictive components**。Shutin 与 Fleury 的 2011 论文甚至在测得信道上用“按延迟位置的平滑功率轮廓相对阈值”来控制灵敏度：在他们的示例中，阈值相当于“只保留在该 delay 位置上高于局部功率约 15 dB 阈值的分量”，而不是简单相对全局最强径设定统一门限。对你的情形，这比统一采用“最强径 -30 dB 全收或全拒”更合理。citeturn38view0turn22view1turn22view0

从 tracking 文献看，**Wald test、false-alarm modeling 和 temporal persistence** 都是很强的剪枝工具。Salmi 等人的 state-space 跟踪方法在每个观测时刻都做“搜索新路径 + 丢弃不可靠路径”，并用 **Wald hypothesis test** 以路径权重是否显著非零作为保留/删除判据；Li 等人的 BP tracking 论文则显式建模了 time-varying MPC 数量和 false alarm rate，并强调 probabilistic data association 在 prior estimation stage 存在大量 false alarms 时更稳。换成你的实现语言，就是：**单窗口内被检出的弱路径，不应该只靠一次输出就“确认为物理 MPC”，而应该至少经过多窗口持续性、显著性与轨迹一致性的联合验证。**citeturn5search3turn38view0

时变性方面，文献给到的结论也很明确。Mahler 等人在 V2V 场景中采用**尽可能短的时间窗口，甚至逐 snapshot 处理**，理由就是快照间存在非平稳 MPC 行为和 delay 变化；Salmi 的 EKF 跟踪则把**参数变化率**纳入状态向量，用常速模型来跟踪 delay 与角度的连续演化；BP tracking 又进一步把出生/死亡和 false alarms 纳入贝叶斯跟踪。对应到你的 50 帧窗口：如果 ridge 在窗口内已出现可见 delay drift，那么与其强迫一条路径在 50 帧内共享固定 \((\tau,\nu)\)，不如**缩短窗口、做 sliding window，或直接把 delay-rate 纳入状态模型**。这比一味调高 max_paths 更符合文献。citeturn43view5turn5search3turn38view0

如果你需要“近年的应用侧佐证”，这类 path-based MPC tracking 已经被用于近期的**空地信道测量数据**分析；因此，把 single-window SAGE 变成“snapshot HRPE + track-level validation”的两阶段框架，不只是 V2V 的特例，而是正在被更广泛采用的方向。citeturn15search15turn15search4

## 瞬态干扰与坏快照

关于你提到的 **全 delay 同时发亮的垂直强带 / 瞬态干扰**，我查到的 SAGE–RiMAX 主线文献，重点大多放在**更准确的数据模型、DMC 协方差、路径出生/死亡与 false alarm** 上，而不是把“整帧 burst outlier”直接作为一个标准统计项写进似然函数。也正因为如此，工程实践里最常见的做法不是“让 SAGE 自己解释 vertical burst”，而是**在进入 HRPE 之前先做 snapshot 质量控制**。这并不违背文献主线：Ahrens 等人的 channel sounding with SDRs 论文就明确指出，测量设备伪迹会污染 channel estimates，需要先做 signal restoration / artefact mitigation；NIST 的 sounder verification 报告也把明显 outlier 识别出来并移除，以避免坏点不成比例地影响结果。citeturn46search5turn46search10turn46search13

因此，对你的 vertical bright bands，我更建议把它们当成**坏快照**而不是“很多真实新路径同时出生”。具体做法可以是：先做逐帧质量门控，例如检测全 delay 能量突增、噪声底同步抬升、AGC/幅度统计异常、或所有延迟 bin 同步变亮；对被标记的帧，直接剔除，或禁止“新路径出生”，仅允许已有强轨迹做极小步长更新。然后再把残余的一次性检出交给 track-level false-alarm suppression 去清掉。这个处理思路虽然偏工程，但和 BP tracking 文献中“prior estimation stage 会产生大量 false alarms、需要在 tracking stage 建模并抑制”的结论是完全一致的。citeturn38view0turn46search5turn46search10

## 对你实现的修改建议

最值得优先改的，不是把 `max_paths` 再调大，而是把 **path atom** 改掉。把现在的
\[
\alpha_l e^{j2\pi \nu_l t}\delta(\tau-\tau_l)
\]
替换成
\[
\alpha_l e^{j2\pi \nu_l t} g(\tau-\tau_l),
\]
其中 \(g\) 是你通过系统标定得到的**匹配滤波后有效脉冲**，\(\tau_l\) 为连续参数而不是整数 bin。若带宽较大、系统频响或传播频率依赖显著，则应直接在频域实现为 \(G(f)e^{-j2\pi f\tau_l}\) 的形式。只要不这样做，主径剥离就永远会留裙边，后面的“新路径”只会继续往主径附近长。citeturn42view0turn37view0turn27view0turn9search2

第二步是在 residual 端加入 **DMC 或至少 colored residual**。完整做法当然是 RiMAX 风格的 specular + DMC + noise 联合似然；如果你暂时不想重写完整 RiMAX，那么一个折中版本也有效：用单天线 reduced model 估计 residual 的频域/时延域协方差，先做 whitening，再在 whitened residual 上搜索新路径，而不是在原始 PDP 上直接捡峰。对于明显存在多个 diffuse 延迟团的场景，要警惕单模态指数 DMC 的不足，因为 recent work 已表明忽略 multi-modal DMC 会反过来偏置 specular estimation。citeturn37view0turn40view1turn35view0

第三步是重写 **初始化流程**。建议采用“先老路径、后新路径”的顺序：先在当前窗口把已有路径联合优化到收敛，再在 residual 上做一次联合 delay–Doppler correlation search，必要时再从 robust PDP 的晚时延部分补少量局部峰初值。不要再把 PDP 辅助初始化当成“把所有峰都扔进 SAGE”，而应把它当成**覆盖 late/weak regions 的 proposal generator**。这正是 Steinböck 的 PDP maxima 思路与 Wang 的 residual-domain global search 思路结合后的、一维场景下最实用的版本。citeturn23view0turn40view2turn40view1

第四步是在输出端做 **组合式 pruning**。我建议至少同时检查五件事：其一，加入该路径后的 likelihood 或 correlation 是否有实质提升；其二，该路径的局部 SNR 是否高于**本 delay 附近的局部阈值**，而不是只看相对全局最强径；其三，残差能量或 SRR 是否真的改善；其四，路径方差/可靠性是否可接受；其五，它是否至少跨若干滑动窗口持续存在并形成一致轨迹。文献表明，只靠 BIC 或只靠全局功率阈值都不稳；把 Wald、local-threshold、reliability 和 persistence 叠加起来，才更接近成熟 HRPE 工作流。citeturn22view1turn8view1turn37view0turn5search3turn38view0

第五步是处理 **窗口内非平稳与 delay drift**。如果你已经在 waterfall 上看到 ridge 缓慢漂移，而当前窗口又长达 50 帧，那么建议先做一个最小改动版实验：把窗口显著缩短，改成 sliding window，并把相邻窗口中经剪枝留下的路径接到 tracking 层；若这一步明显减少了“可见 ridge 但 SAGE 不认”的现象，就说明症结确实在“窗口内恒定参数假设”而不在“路径数不够”。进一步再上 EKF/recursive tracking 或显式 delay-rate basis expansion。citeturn43view5turn5search3turn38view0

第六步是把你说的垂直强带单独拎出来做 **snapshot gating**。在我看来，这一步应当先于任何高分辨参数估计：先把坏帧剔除或降权，再让 SAGE/RiMAX 去解释“正常传播”。否则，算法会被迫用一组物理上并不可信的弱路径去拟合一个本质上来自干扰或仪器伪迹的突发事件。对这类问题，文献更支持“恢复/清洗后再估计”，而不是“把 burst 当成多条 specular 路径”。citeturn46search5turn46search10turn38view0

综合起来，我对你当前实现的优先级排序是：**先改 atom，再加 colored residual/DMC，再改初始化，再做组合式 pruning，最后上 tracking 与坏帧门控**。如果只能做两件事，我会选“校准 pulse-shape atom + residual-domain 初始化/剪枝”；这两步最直接地对应你现在的两个主故障模式：主径吸附和弱径伪检。citeturn23view0turn22view1turn40view2turn37view0