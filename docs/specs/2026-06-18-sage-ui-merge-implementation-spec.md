# SAGE 界面合并实施规格（Implementation Spec）

- 文档类型：Implementation Spec
- 日期：2026-06-18
- 上游方案：`docs/specs/2026-06-18-sage-ui-merge-plan.md`
- 评审意见：`docs/specs/comments.md`
- 目标：把修订后的模块 A / 模块 B 方案落到可直接开发的前后端数据、API、页面和算法接口层面
- 状态：Draft（未实施）

## 0. 总体目标

本实施规格只做两件事：

1. 保留当前已有 WebUI 作为模块 A；
2. 新增一个可切换的模块 B，用于：
   - 基于 SAGE 窗口结果计算“实测路损散点图”；
   - 在该散点图上做拟合曲线；
   - 合并统计特性分析：阴影衰落、多径衰落、莱斯 K 因子、RMS 时延扩展、RMS Doppler 扩展；
   - 全部以 PDF 形式展示统计拟合结果。

明确不做：

- 不新建原方案中的“多径分析页 / 路损分析页 / 统计特性页”四分结构；
- 不回迁 C++ 旧版多径参数页面；
- 不实现 3GPP / HATA / COST231 / SUI 多模型对比；
- 不实现多功率口径切换；
- 不保留“增益分布”页面或图表。

## 1. 页面结构与前端路由

## 1.1 页面组织方式

前端改为两个可切换模块：

- 模块 A：当前已有主界面
- 模块 B：实测路损 + 统计特性联合分析

建议实现方式：

- 在 `web/index.html` 顶部栏或左侧栏增加模块切换按钮：
  - `#moduleABtn`
  - `#moduleBBtn`
- 主区容器拆成两个 section：
  - `#moduleAView`
  - `#moduleBView`
- 默认进入模块 A
- 切换时仅前端显示隐藏，不做整页跳转

### 1.1.1 必须保留

- 当前数据加载、分析、回放、状态栏逻辑
- 当前模块 A 中所有已有图表和地图功能

### 1.1.2 必须新增

- 模块切换状态 `AppState.activeModule = 'A' | 'B'`
- 模块 B 的初始化函数与渲染函数
- 模块 B 的加载前置检查：没有当前 dataset 时禁用全部 B 图表与导出按钮

## 1.2 模块 A 的边界

模块 A 不做结构性重写，仅允许以下增量改动：

- 增加“切换到模块 B”入口
- 在 dataset 加载成功后，为模块 B 准备调用入口
- 如需共享状态，仅共享：
  - 当前 dataset 名称
  - 当前分析结果 JSON
  - 当前 Tx-Rx 距离数组
  - 当前 SAGE 窗口结果

不允许：

- 把模块 B 的统计图塞回模块 A 主布局
- 为了模块 B 改乱当前模块 A 的 2x2 总览图结构

## 1.3 模块 B 的前端布局

模块 B 建议布局为：

### 区块 B1：实测路损

- 图 1：实测路损散点图 + 拟合曲线
- 图 2：阴影衰落 PDF

### 区块 B2：统计特性

- 图 3：多径衰落 PDF
- 图 4：莱斯 K 因子 PDF
- 图 5：RMS 时延扩展 PDF
- 图 6：RMS Doppler 扩展 PDF

### 区块 B3：参数与结果说明

- 当前数据集名称
- 使用的 SAGE 窗口参数（只读）
- 当前拟合模型名称 / 模型切换控件
- 样本点数量
- 关键统计量摘要（均值、方差、shape factor、K 值等）

建议布局：

- 第一行：B1 两图并排
- 第二、三行：B2 四图按 2x2 排布
- 右上或顶部卡片：B3 参数说明

## 2. 后端 API 设计

## 2.1 新增 API

新增统一接口：

- `GET /api/datasets/{name}/module-b`

返回模块 B 所需全部数据，前端一次取回，不在浏览器里自己推导核心统计量。

### 2.1.1 返回结构

```json
{
  "meta": {
    "datasetName": "xxx.json",
    "sourceBin": "xxx.bin",
    "frameRateHz": 100.0,
    "bandwidthHz": 50000000.0,
    "windowSizeFrames": 20,
    "stepFrames": 100,
    "nWindows": 283,
    "fitModels": {
      "fading": ["rayleigh", "rice", "nakagami"],
      "kFactor": ["moment", "rice_fit"],
      "rmsDelay": ["lognormal", "gamma", "weibull"],
      "rmsDoppler": ["lognormal", "gamma", "weibull"]
    }
  },
  "pathLoss": {
    "distanceM": [...],
    "measuredDb": [...],
    "fit": {
      "model": "log_distance_linear_fit",
      "xDistanceM": [...],
      "yFitDb": [...],
      "params": {...}
    },
    "shadowResidualDb": [...]
  },
  "shadowFading": {
    "samplesDb": [...],
    "pdf": {
      "x": [...],
      "y": [...],
      "model": "gaussian",
      "params": {"mu": 0.0, "sigma": ...}
    }
  },
  "multipathFading": {
    "samples": [...],
    "models": {
      "rayleigh": {"x": [...], "y": [...], "params": {...}},
      "rice": {"x": [...], "y": [...], "params": {...}},
      "nakagami": {"x": [...], "y": [...], "params": {...}}
    },
    "defaultModel": "nakagami"
  },
  "kFactor": {
    "samples": [...],
    "models": {
      "moment": {"x": [...], "y": [...], "params": {...}},
      "rice_fit": {"x": [...], "y": [...], "params": {...}}
    },
    "defaultModel": "moment"
  },
  "rmsDelaySpread": {
    "samplesNs": [...],
    "models": {...},
    "defaultModel": "lognormal"
  },
  "rmsDopplerSpread": {
    "samplesHz": [...],
    "models": {...},
    "defaultModel": "lognormal"
  }
}
```

## 2.2 错误处理

- dataset 不存在：404
- dataset 中缺少 `sageDelayDoppler`：422，错误文案明确说明“当前数据集不含 SAGE 窗口结果，无法生成模块 B”
- SAGE 路径为空：200，但返回空样本结构，前端显示“无可分析样本”
- 统计拟合失败：保留 `samples`，对应 `models[xxx] = null`，前端显示“该模型拟合失败”

## 2.3 性能约束

- 模块 B 结果允许首次请求时现算
- 但同一 dataset 再次请求应命中缓存
- 推荐缓存形式：
  - 内存缓存：开发态
  - 文件缓存：`data/ui_samples/<stem>_module_b.json`

建议缓存键：
- datasetName
- SAGE 关键参数签名（window/step/max_paths 等）

## 3. 后端数据管线设计

## 3.1 新增 Python 模块

建议新增：

- `src/analysis/module_b.py`

职责：

1. 从 dataset 或原始中间结果中提取窗口级 SAGE 路径
2. 计算实测路损散点
3. 计算拟合曲线
4. 计算阴影衰落样本与高斯 PDF
5. 计算多径衰落样本与多模型 PDF
6. 计算 K 因子样本与 PDF
7. 计算 RMS 时延扩展样本与 PDF
8. 计算 RMS Doppler 扩展样本与 PDF
9. 输出 JSON 可序列化结构

## 3.2 禁止事项

- 不要把模块 B 分析逻辑硬塞到 `frontend_app.py`
- 不要把统计模型拟合直接写在前端 JS 中
- 不要从 `mpcScatter` 直接做一切统计，优先使用 `sageDelayDoppler.windowTracks`
  - 因为 `windowTracks` 保留了窗口边界，更适合窗口级统计

## 4. 模块 B 的算法定义

## 4.1 输入数据源

主输入：

- `dataset["sageDelayDoppler"]["windowTracks"]`
- `dataset["frameStats"]`
- `dataset["rxGps"]`
- `dataset["txGps"]`
- `dataset["meta"]`

每个窗口至少需要：

- `timeSec`
- `frameStart`
- `frameEnd`
- `peaks[]`
  - `delayNs`
  - `dopplerHz`
  - `powerDb`
  - `amplitudeReal`
  - `amplitudeImag`

## 4.2 实测路损散点图的严格定义

### 4.2.1 每窗口复振幅叠加

对每个窗口：

```python
A_sum = sum(complex(amplitudeReal, amplitudeImag) for peak in peaks)
```

### 4.2.2 转 dB

统一定义为：

```python
received_power_db = 20 * log10(abs(A_sum) + 1e-30)
```

说明：

- 该定义等价于 `10*log10(|A_sum|^2 + eps)`
- 实施时只保留一种公式，避免前后端混乱
- 本 spec 直接锁定使用 `20*log10(abs(A_sum)+eps)`，不要做可切换项

### 4.2.3 距离坐标

每个窗口的距离取该窗口中心对应的距离：

优先级：

1. 若 `window.timeSec` 能映射到 `frameStats.timeSec`，取最近的 `frameStats.distanceM`
2. 否则用 `frameStart/frameEnd` 对应帧的中间点距离
3. 不允许直接用原始 `mpcScatter` 散点自己的 frame 近似拼凑

### 4.2.4 输出

得到：

- `distanceM[i]`
- `measuredDb[i]`

这就是实测路损散点图唯一数据源。

## 4.3 路损拟合曲线定义

本 spec 不再使用 3GPP/HATA/COST231/SUI 多模型。

仅保留一个实测拟合曲线，默认采用对数距离线性拟合：

```text
y = beta0 + beta1 * log10(d)
```

输出：

- `xDistanceM`
- `yFitDb`
- `params = {beta0, beta1, rmse, r2}`

注意：

- 若距离非正，必须过滤
- 拟合前应保证 `distanceM` 与 `measuredDb` 一一对应

## 4.4 阴影衰落定义

```python
shadow_residual_db = measured_db - fitted_db
```

要求：

- 不再额外做复杂趋势拆分
- 直接以拟合残差作为阴影衰落样本
- 高斯模型固定为：
  - `mu = sample_mean(residual)`
  - `sigma = sample_std(residual)`
- 展示时同时给出：
  - 样本直方图
  - 理论高斯 PDF 曲线

评审意见中要求“0 均值高斯分布”，因此前端展示文案写为：

- 主判断目标：是否接近 0 均值高斯
- 若样本均值明显偏离 0，则在结果区提示“均值偏离 0，需要检查大尺度拟合是否充分”

## 4.5 多径衰落定义

这是模块 B 中最容易歧义的部分，当前实施规格先锁定一个可执行口径：

### 4.5.1 样本定义

默认使用“最强路径幅度，经局部归一化后得到快衰落包络样本”：

对每个窗口：

1. 找最强路径 `peak_max`
2. 取其复振幅模值 `r_i = abs(a_max)`
3. 对 `r_i` 做局部均值归一化，得到 `r_norm_i`
4. 用 `r_norm_i` 作为多径衰落样本

局部均值窗口建议：
- 沿时间轴 21 点滑动平均
- 边界做截断

### 4.5.2 拟合模型

必须支持：

- Rayleigh
- Rice
- Nakagami

输出：

- 每个模型的参数估计
- 每个模型对应的 PDF 曲线
- `defaultModel` 初始设置为 `nakagami`

## 4.6 莱斯 K 因子定义

要求：

- 不直接从旧 C++ 页面迁移逻辑
- 只基于当前窗口级 SAGE 路径结果定义

默认实现两种方法：

1. `moment`
   - 由包络样本矩估计 K
2. `rice_fit`
   - 由 Rician 分布拟合参数反推 K

输出：

- 每种方法得到的 `K` 样本或全局估计
- 对应 PDF 曲线
- 前端可切换显示方法

## 4.7 RMS 时延扩展定义

每个窗口：

设路径功率权重为 `w_k = |a_k|^2`
设时延为 `tau_k`

```python
tau_mean = sum(w_k * tau_k) / sum(w_k)
rms_delay = sqrt(sum(w_k * (tau_k - tau_mean)**2) / sum(w_k))
```

输出：

- `samplesNs`
- 多个候选拟合模型 PDF

建议实现的模型：

- lognormal
- gamma
- weibull

## 4.8 RMS Doppler 扩展定义

每个窗口：

设 Doppler 为 `f_k`
设权重为 `w_k = |a_k|^2`

```python
f_mean = sum(w_k * f_k) / sum(w_k)
rms_doppler = sqrt(sum(w_k * (f_k - f_mean)**2) / sum(w_k))
```

输出：

- `samplesHz`
- 多个候选拟合模型 PDF

建议实现的模型：

- lognormal
- gamma
- weibull

## 5. 前端图表规范

## 5.1 图表库

继续使用 ECharts。

## 5.2 模块 B 图表要求

### 图 1：实测路损散点 + 拟合曲线

- 散点：蓝色小圆点
- 拟合线：红色实线
- x 轴：Distance (m)
- y 轴：Measured path loss / received power (dB)
- tooltip 显示：距离、测量值、拟合值

### 图 2–6：PDF 图

统一要求：

- 直方图：浅蓝色柱
- 理论 PDF：红色或橙色线
- 支持模型切换时，切换后只重绘该图
- tooltip 显示：x、pdf、样本数量/参数

## 5.3 导出

模块 B 的每张图右上角保留导出 PNG 按钮。

新增：

- 模块 B 结果 JSON 导出按钮
- 导出当前统计样本 CSV 的按钮（每个分析项一个）

## 6. 文件修改范围

## 6.1 前端

- 修改：`web/index.html`
- 修改：`web/static/app.js`
- 修改：`web/static/styles.css`

## 6.2 后端

- 修改：`src/frontend_app.py`
- 新增：`src/analysis/module_b.py`
- 可选新增：`src/analysis/distributions.py`
- 可选新增：`src/analysis/path_loss_fit.py`

## 6.3 测试

- 新增：`tests/test_module_b_analysis.py`
- 新增：`tests/test_module_b_api.py`
- 前端最少保留静态结构测试：`tests/test_frontend_app.py`

## 7. 测试规格

## 7.1 单元测试

### UT-001 实测路损由复振幅叠加得到

输入：一个窗口 3 条路径，给定复振幅

验证：
- `received_power_db == 20*log10(abs(sum(a_k))+eps)`
- 不是逐 dB 相加

### UT-002 阴影衰落残差定义正确

输入：distance、measured_db、fitted_db

验证：
- `shadow_residual_db = measured_db - fitted_db`

### UT-003 RMS 时延扩展计算正确

输入：给定时延和功率

验证：
- 与手算一致

### UT-004 RMS Doppler 扩展计算正确

输入：给定 Doppler 和功率

验证：
- 与手算一致

### UT-005 空窗口安全处理

输入：某窗口 `peaks=[]`

验证：
- 不崩溃
- 跳过该窗口或输出 null，并在聚合前过滤

## 7.2 API 测试

### IT-001 `/api/datasets/{name}/module-b` 正常返回

验证：
- 200
- 顶层字段齐全
- `pathLoss.distanceM` 与 `pathLoss.measuredDb` 长度一致

### IT-002 缺少 SAGE 数据时报错

验证：
- 422
- 错误信息明确

## 7.3 前端手动验证

- [ ] 模块 A 与模块 B 能正常切换
- [ ] 模块 A 现有图表不受影响
- [ ] 模块 B 路损散点图加载正常
- [ ] 模块 B 拟合曲线叠加正常
- [ ] 五类 PDF 图都可显示
- [ ] 模型切换能生效
- [ ] 空数据时不崩溃
- [ ] 导出 PNG / JSON / CSV 正常

## 8. 禁止偏离项

1. 不要恢复原四页面信息架构。
2. 不要重新加入 3GPP / HATA / COST231 / SUI 模型对比。
3. 不要加入多功率口径切换。
4. 不要把模块 B 的核心统计逻辑放在前端 JS 算。
5. 不要把旧 Qt 的峰值法当成模块 B 主结果来源。

## 9. 开发顺序

按用户最新要求，顺序必须是：先把结果输出出来，再改 UI 界面。

### Phase 1：先产出结果（不改 UI）

1. 完成 `src/analysis/module_b.py` 的纯 Python 数据计算
2. 先在后端或脚本层把模块 B 所需结果完整输出出来
3. 输出内容至少包括：
   - 实测路损散点数据（距离、基于 SAGE 复振幅叠加后的 dB 值）
   - 路损拟合曲线数据
   - 阴影衰落样本与 PDF
   - 多径衰落样本与各候选模型 PDF
   - 莱斯 K 因子结果与 PDF
   - RMS 时延扩展结果与 PDF
   - RMS Doppler 扩展结果与 PDF
4. 结果先落为可检查的 JSON / CSV / PNG（或至少 JSON + 可复现实验脚本），确保算法口径先跑通
5. 这一阶段允许新增：
   - `/api/datasets/{name}/module-b`
   - 或单独导出脚本 / 中间结果文件

### Phase 2：确认结果正确

1. 先人工检查结果是否符合预期
2. 重点确认：
   - 复振幅叠加后的实测路损定义是否正确
   - 拟合曲线是否合理
   - 各统计量样本是否稳定
   - PDF 拟合是否可接受
3. 若结果口径有争议，先改算法与输出，不进入 UI 阶段

### Phase 3：最后再改 UI

1. 结果确认后，再给前端增加模块 A / 模块 B 切换
2. 再接模块 B 图表与导出按钮
3. 模块 A 现有 UI 在此之前保持不动

## 10. 一句话执行指令

先不要急着改界面；先从当前 dataset 的 SAGE 窗口结果出发，把模块 B 需要的实测路损和各类统计 PDF 结果完整输出并验证正确，确认算法口径后，再把这些结果接入模块 B UI。