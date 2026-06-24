# SAGE 算法驱动的界面合并与改造方案（按评审意见修订）

- 文档类型：Spec / Planning
- 日期：2026-06-18
- 适用项目：`/home/guo/桌面/project/chan_meas`
- 状态：Draft（根据 `docs/specs/comments.md` 修订，先出方案，未实施）

## 1. 背景

当前项目中已经具备两套可用资产：

1. 现有 Python + FastAPI + WebUI 分析平台
   - 前端：`web/index.html`, `web/static/app.js`, `web/static/styles.css`
   - 后端：`src/frontend_app.py`
   - 数据构建：`src/ui_dataset.py`, `src/pipeline/analyze.py`
   - 已支持 B2B 校准、CIR/PDP 瀑布、Doppler-Time 瀑布、SAGE 多径散点、逐帧 PDP、GPS 轨迹。

2. 别人已有的 Qt/C++ 信道分析界面及其分析结果
   - 解析目录：`_zip_analysis_20260618_173753/generated_files/`
   - 原版偏“分析工具箱”：多径参数、路损模型、统计衰落、相关性等
   - 修改版偏“原始 BIN 解析器”：BIN → IQ/GPS/CIR/PDP/轨迹导出

本次修订后的目标不再写成抽象的“信息架构整合”，而是直接按用户意见落到页面模块设计：

- 模仿 C++ 页面组织方式，增加模块 A、模块 B 等可切换页面；
- 模块 A 直接使用当前已有 WebUI 界面；
- 模块 B 重新设计为“实测路损 + 统计特性联合分析页面”；
- 底层数据统一继续基于当前 Python 管线和 SAGE 输出。

## 2. 本次阅读范围与依据

### 2.1 当前项目关键文件

- `src/frontend_app.py`
- `src/ui_dataset.py`
- `src/pipeline/analyze.py`
- `web/index.html`
- `web/static/app.js`
- `web/static/styles.css`
- `docs/specs/2026-06-16-channel-analysis-ui-implementation-spec.md`
- `docs/specs/2026-06-18-参数说明.md`

### 2.2 旧 Qt 工程关键分析文件

- `_zip_analysis_20260618_173753/generated_files/CODE_SUMMARY.md`
- `_zip_analysis_20260618_173753/generated_files/UI_INDEX.md`
- `_zip_analysis_20260618_173753/generated_files/DIFF_REPORT.md`
- `_zip_analysis_20260618_173753/generated_files/MIGRATION_NOTES.md`
- `_zip_analysis_20260618_173753/generated_files/FUNCTION_INDEX.md`

### 2.3 旧 Qt 工程源码证据

- `software_orig/ChannelAnalyzer/widget.cpp`
- `software_orig/ChannelAnalyzer/delayprocessor.cpp`
- `software_orig/ChannelAnalyzer/pathlossevaluator.cpp`
- `software_orig/ChannelAnalyzer/residualanalyzer.cpp`

### 2.4 评审意见依据

- `docs/specs/comments.md`

## 3. 核心修订结论

1. 不再保留原方案里“推荐的信息架构 / 四大独立页面 / 多阶段抽象规划”的主导写法。
2. 页面组织直接模仿 C++ 的“模块 A / 模块 B 可切换页面”思路。
3. 模块 A 就是当前已有 WebUI 界面，舍弃 C++ 旧版对应的多径参数页面，不单独迁移该旧页面。
4. 模块 B 需要大改，不再保留原方案中“路损分析页”和“统计特性页”分开的设计，而是合并为一个新模块。
5. 模块 B 中，实测路损的核心口径改为：对 SAGE 估计出的 N 个多径复振幅进行叠加，再取 dB 生成散点图，并在其基础上做拟合曲线。
6. 删除原方案中的：
   - 增益分布；
   - 3GPP / HATA / COST231 / SUI / 实测模型并列对比；
   - 多种功率口径切换设计。
7. 模块 B 中保留并强化统计特性分析，包括：
   - 阴影衰落 PDF；
   - 多径衰落拟合 PDF；
   - 莱斯 K 因子 PDF；
   - RMS 时延扩展 PDF；
   - RMS Doppler 扩展 PDF。

## 4. 对旧 Qt 算法价值的重新定位

### 4.1 旧多径提取算法

旧 Qt 多径提取核心证据：

- `widget.cpp::GetMulParam(...)`
- `delayprocessor.cpp::processData(...)`

其方法本质上是：

- 对单帧 CIR 做局部峰值检测；
- 阈值使用“低 85% 分位 + 3σ”；
- 超阈值局部峰视为多径；
- 再做峰值时延的概率统计。

该方法可作为旧系统逻辑参考，但不再作为新系统主分析结果来源。

### 4.2 当前 SAGE 输出的定位

当前 Python 管线已具备：

- B2B 校准后的 CIR；
- adaptive SAGE 的 delay / doppler / power 联合估计；
- `mpcScatter`；
- `sageDelayDoppler.windowTracks`；
- `dopplerTimeWaterfall`。

因此新方案中，模块 B 的实测路损与统计特性都应优先建立在 SAGE 输出之上，而不是旧的单帧峰值法之上。

## 5. 当前系统现状（与本方案直接相关）

### 5.1 当前已有 WebUI 能力

当前首页已支持：

- PDP 原始瀑布；
- Doppler-Time-Power-Spectrum；
- SAGE delay-time 散点图；
- SAGE doppler-time 散点图；
- 当前帧 PDP 曲线；
- GPS 轨迹 + 当前 Rx 位置；
- 状态栏（场景、时间、距离、N_MPC、窗口数等）。

样例数据已经是实 SAGE 结果，不是 mock：

- `meta.numFrames = 28309`
- `rxGps / frameStats / framePayloads = 284`
- `dopplerTimeWaterfall.timeSec = 283`
- `mpcScatter = 355`
- `sageDelayDoppler.windowTracks = 283`

结论：当前 WebUI 已足够作为模块 A 直接保留，不需要再从 C++ 多径页面回迁功能。

### 5.2 当前 SAGE 参数链路现状

从 `docs/specs/2026-06-18-参数说明.md` 可知，目前 UI 侧几乎未开放 SAGE 核心参数。

真正算法层支持的参数远多于当前 WebUI 表单项，例如：

- `window_size_frames`
- `step_frames`
- `delay_gate_distance_m`
- `coverage_target`
- `min_coverage_gain`
- `max_paths_hard`
- `pulse_half_width_bins`
- `delay_search_bins`
- `doppler_search_half_span_hz`
- `doppler_search_points`
- `enable_weak_nonprominent_prune`

当前 `build_dataset_from_arrays()` 中仍写死使用：

- `window_size_frames=20`
- `step_frames=100`
- `coverage_target=0.95`
- `max_paths_hard=30`

结论：本方案阶段先不讨论参数开放，而是先确定模块 A / 模块 B 的结果定义与展示逻辑。

## 6. 模块化页面方案（按评审意见重写）

### 6.1 模块 A：当前 UI 主界面

模块 A 直接采用当前已有 WebUI 界面。

保留内容：

- PDP 原始瀑布；
- Doppler-Time-Power-Spectrum；
- SAGE delay-time；
- SAGE doppler-time；
- 当前帧 PDP 曲线；
- GPS 轨迹；
- 状态栏；
- 当前已有导入 / 分析 / 回放逻辑。

处理原则：

- 不再单独迁移 C++ 旧版“多径参数分析页面”；
- 不再把旧版“峰值概率统计结果”等页面作为新的独立模块；
- 模块 A 就是现有工作台，是主入口。

### 6.2 模块 B：实测路损 + 统计特性联合分析

模块 B 取代原方案中的“路损分析页”与“统计特性页”分离设计，统一成一个页面。

#### 6.2.1 模块 B 的核心数据定义

模块 B 的核心输入不再采用：

- 每帧 CIR 最大峰值；
- 多种功率口径切换；
- 多个经验传播模型并列比较。

而改为：

- 对每个分析窗口内 SAGE 估计出的 N 个多径复振幅进行叠加；
- 由叠加结果求功率；
- 再取 dB，形成“实测路损”散点。

用符号表示：

- 设某窗口估计得到路径复振幅为 `a_1, a_2, ..., a_N`
- 先做复振幅叠加：`A_sum = Σ a_k`
- 再求功率并转 dB：`P_meas_db = 20 log10(|A_sum| + eps)` 或等效功率定义
- 再基于距离轴形成实测路损散点图

注：最终采用 `20log10|A_sum|` 还是 `10log10|A_sum|^2`，本质等价到常数因子，需要在实施阶段统一约定输出口径，但原则是“先复振幅叠加，再转 dB”，而不是“先对各路径取 dB 后再做非线性拼接”。

#### 6.2.2 模块 B 页面内容

模块 B 建议包含以下分区：

1. 实测路损散点图
   - 横轴：Tx-Rx 距离；
   - 纵轴：基于 SAGE 复振幅叠加得到的实测路损/实测接收功率 dB 量；
   - 数据单位和正负号口径在实施时统一。

2. 实测路损拟合曲线
   - 在上述散点图上进行拟合；
   - 本方案不再要求同时挂多个经典传播模型；
   - 重点是“实测散点 + 拟合曲线”。

3. 阴影衰落分析
   - 基于拟合残差；
   - 以 0 均值高斯分布为目标；
   - 绘制 PDF。

4. 多径衰落分析
   - 搜索和实现常用拟合模型；
   - 至少考虑：Nakagami、Rayleigh、Rician；
   - 绘制 PDF。

5. 莱斯 K 因子分析
   - 提供几个常用模型可切换；
   - 绘制 PDF。

6. 均方根时延扩展分析
   - 提供几个常用模型可切换；
   - 绘制 PDF。

7. 均方根 Doppler 扩展分析
   - 提供几个常用模型可切换；
   - 绘制 PDF。

#### 6.2.3 模块 B 明确删除项

删除以下原方案内容：

- 增益分布；
- 3GPP / HATA / COST231 / SUI / 实测模型并列展示；
- `raw_peak_power / main_path_power / topk_path_sum_power` 三种功率口径切换；
- 将统计特性分析单独拆成一个独立模块 C 页面。

## 7. 模块 B 的算法落地要求

### 7.1 实测路损的定义要求

模块 B 的第一优先级不是 UI，而是先把“实测路损散点图的算法定义”钉死。

要求：

1. 输入来自 SAGE 窗口结果，而不是旧峰值法。
2. 路损/接收功率量必须由 N 条多径的复振幅叠加后得到。
3. 距离坐标使用当前系统已有的 Tx-Rx 距离定义。
4. 路损拟合必须建立在这套新口径之上。

### 7.2 阴影衰落定义

建议定义：

- 用实测路损散点减去拟合曲线，得到残差；
- 将残差视为阴影衰落样本；
- 验证其是否接近 0 均值高斯；
- 绘制 PDF。

### 7.3 多径衰落定义

建议从以下口径中择一定义，并在实施时固定：

- 基于主径幅度；
- 基于局部窗口归一化后的复包络；
- 基于去除大尺度衰落后的快衰落包络。

本 spec 当前只确定需求，不提前锁死具体归一化公式；但实施前必须先把公式单独补成 implementation-level spec。

### 7.4 K 因子、RMS 时延扩展、RMS Doppler 扩展

这些量都应建立在统一的窗口级结果之上：

- K 因子：基于 LOS / 散射项定义或 Rician 拟合参数反推；
- RMS 时延扩展：基于每个窗口路径功率-时延分布；
- RMS Doppler 扩展：基于每个窗口路径功率-Doppler 分布。

本方案要求页面上提供若干常用模型切换，并输出对应 PDF，而不是只给一个数值列表。

## 8. 页面切换与交互组织

按评审意见，页面层面应模仿 C++ 的模块切换方式。

因此建议前端组织方式改为：

- 模块 A 按钮 / 标签页
- 模块 B 按钮 / 标签页

切换逻辑：

- 模块 A：进入当前已有工作台；
- 模块 B：进入实测路损 + 统计特性联合分析页面。

这里不再扩展更多抽象页面，不再保留原方案中“总览 / 多径分析 / 路损分析 / 统计特性”四分结构。

## 9. 本方案相对旧版 spec 的主要变化

1. 删除“旧 Qt 功能结构整体吸收”的泛化表述，改成明确模块方案。
2. 删除“多径分析页单独迁移”的主线；模块 A 直接采用当前 UI。
3. 删除“路损分析页”和“统计特性页”分离设计，合并为模块 B。
4. 删除多功率口径设计。
5. 删除多个传播模型横向对比设计。
6. 强化“基于 SAGE N 个多径复振幅叠加后取 dB”这一实测路损定义。
7. 强化 PDF 型统计展示要求。

## 10. 当前版本的实施边界

本文件当前只定义到“方案级”。

已经明确的：

- 模块组织方式；
- 模块 A / 模块 B 的职责；
- 模块 B 的结果定义方向；
- 必须删除与必须保留的功能项。

尚未在本文件中展开到可直接编码的：

- 模块 B 每个统计量的精确公式；
- 复振幅叠加后的路损符号与标定口径；
- 各 PDF 拟合模型的参数估计方法；
- 前端组件拆分和后端 API 字段设计。

这些内容应在下一份 implementation spec 中细化。

## 11. 一句话版本

最终页面按 C++ 风格组织成可切换模块：模块 A 保留当前已有 UI；模块 B 重做为“基于 SAGE 多径复振幅叠加得到的实测路损 + 统计特性联合分析页面”；删除原方案中多模型对比、多功率口径和独立统计页设计。