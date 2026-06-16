# 信道测量分析软件 UI 重构 — 实现规格 (Implementation)

- 文档类型：Implementation
- 日期：2026-06-16
- 上游设计：[设计文档](2026-06-16-channel-analysis-ui-redesign-design.md)（Decision Log + FMEA，Locked In 项不可重开）
- 目标：让 AI 零歧义地实现 P0–P7

## 0. 数据契约（已核对，5 个 JSON 一致）

| key | 类型 | 用途 |
|---|---|---|
| `meta` | obj: `name, frameRateHz, bandwidthHz, numFrames, numDelayBinsExported, delayUnit, txMode, relativePower` | 元信息 |
| `txGps` | obj: `lat, lon, alt, source` | Tx 位置 |
| `rxGps[]` | 284× `{frame, timeSec, lat, lon, alt}` | 逐窗口 Rx 轨迹 |
| `frameStats[]` | 284× `{frame, timeSec, distanceM, peakPowerDb, peakDelayNs, meanPowerDb, rmsDelayNs, pathCount}` | 逐窗口统计 |
| `framePayloads[]` | 284× `{frame, timeSec, rxGps, txGps, stats, pdpCurve, powerDistribution, mpcScatter}` | 逐帧载荷 |
| `framePayloads[i].pdpCurve` | `{delayNs[256], powerDb[256], peakDelayNs, peakPowerDb, relative}` | 逐帧 PDP 曲线 |
| `cirWaterfall` | `{delayNs[256], timeSec[284], powerDb[284][256]}` | PDP 瀑布；powerDb p1/p99≈-48/5.5 |
| `mpcScatter[]` | 355× `{timeSec, delayNs, dopplerHz, powerDb, pathId, frameStart, frameEnd, ...}` | SAGE 多径散点 |

汇总指标来源（状态栏）：`/mnt/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100/adaptive_summary.json`，按 `file == <stem>.bin` 匹配，取 `nWindows, mpcCandidates, validatedTracks, maxPathsPerWindow`。

## 1. P1 — 汇总图重渲染（核心）

### 1.1 colormap（数组固定，取值范围自适应）

```js
// jet 色标停靠点（PDP 瀑布用）
const JET_STOPS = ['#00008f','#0000ff','#0080ff','#00ffff','#80ff80','#ffff00','#ff8000','#ff0000','#800000'];
// hot 色标停靠点（MPC 散点用；低=暗 高=亮，匹配参照图 afmhot 风格）
const HOT_STOPS = ['#000000','#3b0000','#8f0000','#ff3000','#ff8000','#ffd000','#ffff60','#ffffff'];
```

**自适应范围算法**（不写死 dB）：

```js
function robustRange(values, loPct = 1, hiPct = 99) {
  const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
  if (!sorted.length) return [0, 1];
  const q = p => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p / 100 * (sorted.length - 1))))];
  let lo = q(loPct), hi = q(hiPct);
  if (hi - lo < 1e-6) { hi = lo + 1; }  // 退化保护
  return [lo, hi];
}
```

- PDP 瀑布：`visualMap.min/max = robustRange(cirWaterfall.powerDb.flat())`
- 散点：`visualMap.min/max = robustRange(mpcScatter.map(m=>m.powerDb))`

### 1.2 三张图的 ECharts 配置

| 图 | type | x | y | 色=visualMap 维度 | 长宽比 |
|---|---|---|---|---|---|
| PDP 原始瀑布 | heatmap | delayNs(category) | timeSec(category) | powerDb，JET_STOPS | 容器 `aspect-ratio: 2/1` |
| SAGE delay-time | scatter | timeSec(value) | delayNs(value) | powerDb，HOT_STOPS | `aspect-ratio: 2/1` |
| SAGE doppler-time | scatter | timeSec(value) | dopplerHz(value) | powerDb，HOT_STOPS | `aspect-ratio: 2/1` |

- 散点：`symbolSize: 6`，`visualMap` 连续型横向放底部，`tooltip` 显示 `t={timeSec}s, delay/doppler={..}, power={powerDb} dB`。
- 瀑布：保留现有 `heatmapTriples()`，仅替换 colormap 与自适应范围；`progressive: 8000`。
- 坐标轴名：与参照图一致（`Measurement time (s)` / `Delay (ns)` / `Doppler (Hz)` / colorbar `Power (dB)`）。

### 1.3 删除
- `updateMusicPlot()` 中 `figure4_style_0m_special_w20` 路径逻辑与 `#mpcPng` 静态图节点。
- `updateDPSDPlot()` 及 `#dpsdChart` 容器（doppler 改用 1.2 的散点）。
- `index.html` 中 `mpcPng`、`dpsdChart` 元素。

## 2. P2 — 回放自适应

### 2.1 帧间隔自检测 + 降采样

```js
function detectDisplayStep(dataset) {
  const rx = dataset.rxGps || [];
  if (rx.length < 2) return { decim: 1, dtSec: 1 };
  const dts = [];
  for (let i = 1; i < rx.length; i++) dts.push(Number(rx[i].timeSec) - Number(rx[i-1].timeSec));
  dts.sort((a, b) => a - b);
  const medDt = dts[Math.floor(dts.length / 2)] || 1;        // 相邻窗口中位时间差
  const decim = medDt > 0 && medDt < 1 ? Math.max(1, Math.round(1 / medDt)) : 1;  // 目标 1 CIR/秒
  return { decim, dtSec: medDt };
}
```

### 2.1.1 frame-id 映射（消除索引对齐脆弱性，HIGH-5）
加载时按 `frame` 字段建映射，slider 由有序 frame 列表驱动，**不**依赖数组下标对齐：

```js
function buildFrameIndex(dataset) {
  const m = new Map();
  (dataset.framePayloads || []).forEach(p => m.set(p.frame, { payload: p }));
  (dataset.rxGps || []).forEach(g => { if (m.has(g.frame)) m.get(g.frame).gps = g; });
  const orderedFrames = Array.from(m.keys()).sort((a, b) => a - b);
  return { map: m, orderedFrames };
}
```

- `slider.max = Math.floor((orderedFrames.length - 1) / decim)`（对齐实际数据，**绝不**用 `meta.numFrames`）。
- slider 值 `s` → `frameId = orderedFrames[s * decim]` → `entry = map.get(frameId)`，取 `entry.payload / entry.gps`。
- 当前时间显示用 `entry.payload.timeSec`，不再用 `currentFrame / frameRateHz`。

### 2.1.2 UI 状态机（CRITICAL-2）
状态：`IDLE | ANALYZING | LOADING_DATA | READY | ERROR`。

- 仅 `READY` 时启用依赖 dataset 的控件：`#frameSlider #jumpInput #playPauseBtn #exportCsvBtn` 及各图导出按钮；其余状态一律 `disabled`。
- `loadDatasetFromApi` 流程**原子且有序**：① 进入 `LOADING_DATA`、禁用控件 → ② fetch+parse → ③ `buildFrameIndex` → ④ 更新 `slider.max` 等属性 → ⑤ 渲染所有图 → ⑥ 进入 `READY`、启用控件。任一步抛错 → `ERROR` + `resetUI()`。
- `resetUI()`：清当前帧、禁用上述控件、slider.max=0；在「开始加载新数据 / 出错」时调用。

### 2.2 保留
- 逐帧 PDP 折线（`#pdpChart`）：数据 `entry.payload.pdpCurve`，保持现有渲染。
- GPS leaflet 当前点：保持现有 `updateMapPanel()`，当前点用 `entry.gps`。

## 3. P3 — 左侧栏工作流

### 3.1 新增控件（index.html）
- 载波频率输入：`<input id="carrierHzInput" type="number">`，单位下拉 `GHz/MHz`，默认空，placeholder「如 28」。
- 「导入」按钮 `#importBtn`，「分析」按钮已有 `#loadDefaultBtn` 复用并改名为「分析」。
- Tx 坐标：静止 → 显示 `lat/lon/alt` 三个 `number` 输入（`#txLat #txLon #txAlt`）；运动 → 隐藏输入、显示置灰的「加载 Tx bin（待开发）」按钮 `disabled`。

### 3.2 导入逻辑

```
点击「导入」：
  if (rxBin 未选)        → 报错「请先选择 Rx 数据」，return
  files = [rxBin]
  if (calBin 已选)       → files.push(calBin)    // 校准可选；两者都选则一起导入
  标记 rxLoadState/calLoadState = ok（calBin 未选则 calLoadState 保持 pending）
  // 原型阶段导入=登记文件名，真正出图在「分析」
```

### 3.3 分析逻辑（前端调用，见 P4 后端）

载波频率解析（单位统一为 Hz，HIGH-2）：

```js
function parseCarrier() {                 // 返回 Hz；非法返回 null
  const v = parseFloat(document.getElementById('carrierHzInput').value);
  if (!Number.isFinite(v) || v <= 0) return null;
  const unit = document.getElementById('carrierUnitSelect').value;  // 'GHz' | 'MHz'
  return unit === 'GHz' ? v * 1e9 : v * 1e6;
}
```

```
点击「分析」：
  carrierHz = parseCarrier()
  if (carrierHz === null) → 提示「请填写载波频率（算 Doppler 用）」+ 聚焦输入框, return
  POST /api/analyze {rxBinName, calBinName?, carrierHz(单位Hz), txMode, txLat?, txLon?, txAlt?, force:false}
  → {status:"ready", datasetName} → loadDatasetFromApi(datasetName)
  → {status:"running", jobId}      → 进入 ANALYZING，轮询 /api/analyze/status/{jobId}（见 P4）
```

## 4. P4 — 后端 compute-or-cache

### 4.1 端点

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/analyze` | `{rxBinName, calBinName?, carrierHz(Hz), txMode, txLat?, txLon?, txAlt?, force?}` | `{status:"ready", datasetName}` 或 `{status:"running", jobId}` |
| GET | `/api/analyze/status/{jobId}` | — | `{status:"running"\|"done"\|"error", progress?:0-100, datasetName?, detail?}` |

> **部署约束（CRITICAL，HIGH-1）**：job 状态存于进程内存，本应用**仅支持单 worker**（`uvicorn ... --workers 1`，默认即 1）。多 worker 会导致轮询命中无该 jobId 的进程而失败。如需多 worker，须改用 Redis 等跨进程存储——超出当前范围。

### 4.2 行为（并发安全，CRITICAL-1）

模块级共享状态 + 锁：
```python
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}            # jobId -> {status, progress, datasetName, detail}
RUNNING_BY_STEM: dict[str, str] = {}  # stem -> jobId（同 stem 去重）
```

```
stem = normalize_stem(rxBinName)      # 去路径、去 .bin（大小写不敏感），仅留主体
jsonPath = DATASET_DIR / f"{stem}_b2b_adaptive_sage.json"
with JOB_LOCK:
    if stem in RUNNING_BY_STEM:                       # 已在跑 → 复用，不重启
        return {"status":"running", "jobId": RUNNING_BY_STEM[stem]}
    if jsonPath.exists() and not force:
        return {"status":"ready", "datasetName": jsonPath.name}
    jobId = uuid4().hex
    JOBS[jobId] = {"status":"running", "progress":0}
    RUNNING_BY_STEM[stem] = jobId
    executor.submit(_run_analysis, jobId, stem, carrierHz, ...)   # 单线程池
return {"status":"running", "jobId": jobId}
```

- `_run_analysis` 末尾（无论成功/异常）在 `JOB_LOCK` 内 `RUNNING_BY_STEM.pop(stem, None)`；成功设 `status=done, datasetName`，异常设 `status=error, detail=摘要`。
- 后台执行用 `concurrent.futures.ThreadPoolExecutor(max_workers=1)`。
- 进度：脚本按窗口数上报 `progress = done_windows / n_windows * 100`（无法细粒度时给 0 与 100 两态）。
- **状态栏聚合（HIGH-3）**：`load_dataset_file` 加载 `*_b2b_adaptive_sage.json` 后，读取 `adaptive_summary.json` 中 `file==<stem>.bin` 的条目，把 `nWindows, mpcCandidates, validatedTracks, maxPathsPerWindow` 合并进 `payload["meta"]["summary"]`（缺失则跳过，不报错）。前端只消费单一数据源。

### 4.3 生成脚本改造
`scripts/run_adaptive_sage_w20_step100_remaining.py` 抽出单 bin 函数 `analyze_one(bin_path, carrier_hz, out_dir) -> json_path`，供后端 import 调用；保留原 `__main__` 批处理入口不变（向后兼容）。

> **载波频率的作用范围（执行阶段澄清，2026-06-16）**：核实 `src/signal/sage_adaptive.py::estimate_window_paths_adaptive` 的多普勒估计只用 `frame_rate_hz` 做慢时间 FFT（采样定理决定频率轴），**不依赖载波频率**——这是物理上正确的：多普勒频移 $f_d$（Hz）由帧率直接解调得到；载波频率只用于把 $f_d$ 换算成速度 $v=f_d\cdot c/f_c$，而当前管线不产出速度字段。因此 `analyze_one(carrier_hz=...)` **不把 carrier_hz 传入 SAGE 计算**，只写入产出 JSON 的 `meta.carrierHz`（Hz）供前端状态栏显示。若未来需要速度换算，再扩展。

## 5. P5 — 新增按钮

| 按钮 id | 行为 |
|---|---|
| `#reanalyzeBtn` 重新分析 | 同分析，`force:true`（忽略缓存重跑） |
| 每图右上角 `.export-fig-btn`（HIGH-4） | 导出**该图** `chart.getDataURL({pixelRatio:2})` → 下载 PNG；废弃模糊的"聚焦图"全局按钮 |
| `#exportCsvBtn` 导出数据 | 当前窗口 `pdpCurve`（delayNs,powerDb）→ CSV Blob 下载 |
| `#jumpInput` 跳转 | `type=number`，输入秒→`idx=argmin|timeSec-x|`→`syncFrame` |
| `#cursorToggle` 读数游标 | 切换 ECharts `axisPointer: {type:'cross'}` 开关 |
| dataZoom | 三张汇总图 `dataZoom:[{type:'inside'},{type:'slider'}]` 启用时延/时间轴缩放 |

合并冗余：删除 `#prevFrameBtn/#nextFrameBtn`（由 slider + 跳转替代）。

## 6. P6 — 状态栏 / 改名 / 清理

- 标题 `V2V信道测量数据离线分析平台` → `信道测量分析软件`（`<title>` + `<h1>` + eyebrow 文案）。
- 状态栏字段：场景 | Tx模式 | 载波频率 | 当前时间(s) | Tx-Rx距离(m) | N_MPC | 窗口数 | 检测帧间隔(s)。N_MPC/窗口数取 `meta.summary`（后端已聚合，见 §4.2 HIGH-3）；当前时间/距离取当前 `entry`；载波频率取输入框；帧间隔取 `detectDisplayStep().dtSec`。
- 删除 `updateOverview()` 对不存在的 `#overviewList` 的引用（改为渲染状态栏 `#statusBar`）。

## 7. ANTI-PATTERNS (DO NOT)

| ❌ Don't | ✅ Do Instead | Why |
|---|---|---|
| 用 `meta.numFrames`(28309) 设 slider.max | 用 `framePayloads.length` 经 decim 后的长度 | 逐帧数据只有 284 窗口，原值导致参数错位 |
| 写死 colormap dB 区间（如 -100~0） | `robustRange(p1,p99)` 自适应 | 用户明确「不要搞死」，不同数据动态范围不同 |
| 把成品 PNG 当静态图嵌入 | 用 ECharts 渲染可交互图，风格照参照图调 | 用户要选点读数值 |
| 分析时同步阻塞跑 SAGE | 后台线程 + 进度轮询 | 重算数分钟会卡死 UI |
| Doppler 计算硬编码载波频率 | 从 `carrierHzInput` 取，缺失则阻止 | 载波频率影响 Doppler 标定 |
| 改 `legacy_reference/` 或硬编码路径 | 路径常量集中、复用现有 `frontend_app.py` | 违反项目架构原则 |
| 手动 patch 生成代码绕过 spec | 改 spec 再生成 | Stream Coding Rule of Divergence |

## 8. TEST CASE SPECIFICATIONS

### Unit Tests (pytest, 后端)
| Test ID | 组件 | 输入 | 期望输出 | 边界 |
|---|---|---|---|---|
| TC-001 | `normalize_stem` | `"0m-...-xiaoquan.bin"` | `"0m-...-xiaoquan"` | 带路径前缀、大写 .BIN |
| TC-002 | `/api/analyze` 缓存命中 | 已存在 JSON 的 stem | `{status:"ready", datasetName}` | force=true 时改走 running |
| TC-003 | `/api/analyze` 缓存未命中 | 不存在的 stem | `{status:"running", jobId}` | jobId 唯一 |
| TC-004 | `/api/analyze/status` | 有效 jobId | `status∈{running,done,error}` | 无效 jobId → 404 |
| TC-005 | `analyze_one` 缺载波频率 | `carrier_hz=None` | 抛 `ValueError` | 0 或负值同样拒绝 |

### Integration Tests
| Test ID | 流程 | Setup | 验证 | Teardown |
|---|---|---|---|---|
| IT-001 | 缓存命中端到端 | 用 xiaoquan JSON | 200 + datasetName 可被 `/api/datasets/{name}` 加载 | — |
| IT-002 | 未命中→后台→完成 | mock `analyze_one` 写假 JSON | 轮询最终 `done` + datasetName 存在 | 删假 JSON |

### 前端手动验证清单
- [ ] 三张汇总图配色/坐标轴/比例贴近参照 PNG，hover 出数值
- [ ] slider 拖动：PDP 曲线 + GPS 当前点同步，时间显示来自 timeSec
- [ ] 切换 5 个场景图都正确
- [ ] 导入：只选 Rx / Rx+校准 两种都正确登记
- [ ] 无死按钮

## 9. ERROR HANDLING MATRIX

### 后端
| 错误 | 检测 | 响应 | 日志 |
|---|---|---|---|
| stem 无对应 bin/folder | 映射查不到 | 404 `{detail:"未找到测量 <stem>"}` | WARN |
| carrierHz 缺失/非正 | 请求校验 | 400 `{detail:"载波频率必填且为正"}` | WARN |
| 分析脚本异常 | 线程 try/except | job.status=error, detail=异常摘要 | ERROR + traceback |
| 重复分析同 stem | 已有 running job | 复用该 jobId，不重启 | INFO |

### 前端（用户可见）
| 错误 | 提示文案 | 恢复 |
|---|---|---|
| 未选 Rx 就导入/分析 | 「请先选择 Rx 数据」 | 高亮 Rx 行 |
| 载波频率为空就分析 | 「请填写载波频率（算 Doppler 用）」 | 聚焦 `#carrierHzInput` |
| 分析后台报错 | 「分析失败：<detail>」 | 启用「重新分析」 |
| 数据集加载失败 | 「数据加载失败，请重试」 | 保留上一次视图 |

## 10. REFERENCES (Deep Links)

| 主题 | 位置 |
|---|---|
| 总体设计/Decision Log/FMEA | [设计文档](2026-06-16-channel-analysis-ui-redesign-design.md#8-decision-log) |
| 前端主逻辑 | `web/static/app.js`（`setDataset/updateCIRPlot/updateDPSDPlot/updateMusicPlot/syncFrame`） |
| 前端结构 | `web/index.html`（`#cirWaterfallChart #dpsdChart #mpcPng #pdpChart #mapLeaflet #statsTable`） |
| 后端 | `src/frontend_app.py`（`create_app`, `/api/datasets`, `load_dataset_file`） |
| 生成脚本 | `scripts/run_adaptive_sage_w20_step100_remaining.py`（输出 7 PNG + JSON 的管线） |
| 样例数据 | `data/ui_samples/*_b2b_adaptive_sage.json`（5 场景） |
| 风格参照图 | `/mnt/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100/<stem>/adaptive_*.png` |
