# 信道测量分析软件 UI 重构 — 设计文档

- 日期：2026-06-16
- 范围：`web/index.html`、`web/static/app.js`、`web/static/styles.css`、`src/frontend_app.py`、生成脚本 `scripts/run_adaptive_sage_w20_step100_remaining.py`
- 性质：在现有 UI 上修改，**不另起炉灶**

## 1. 背景与问题

现有 UI 自称「V2V信道测量数据离线分析平台」，实为**信道测量分析软件原型**。Kimi 改了多轮未达预期，根因：

1. **图风格/尺寸不对**：用 ECharts 现画的图，配色、坐标轴、长宽比和用户心中的 matplotlib 参照图（`/mnt/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100/<stem>/`）对不上。
2. **逐帧回放与数据错配**：slider `max` 按 28308 原始帧设置，但逐帧数据只有窗口级（284 条），导致参数显示错位。
3. **摆设按钮**：部分按钮（如 `overviewList` 相关逻辑）接不上、不起作用。
4. **MPC 图路径写错**：`app.js` 指向不存在的 `figure4_style_0m_special_w20/` 目录。

## 2. 核心定位（已与用户确认）

- 这是**信道分析软件**，不是 V2V 专用。标题去掉「V2V」→「信道测量分析软件」。
- 工作流：加载 Rx `.bin`（可选校准 `.bin`）→ 导入 →「分析」→ 展示 CIR / Doppler / 多径等。
- **sage_outputs 里的图是"风格参照"，不是要原样嵌入的静态图片。** UI 里的图要**可交互（hover / 选点读数值）**，但配色/坐标轴/比例**照参照图调**。
- 逐帧切换（PDP 曲线 + GPS 当前点）是现有 UI 做得好的部分，**保留**。

## 3. 架构与数据流

```
.bin 文件
  │  （导入：校准可选，同时选则一起导入）
  ▼
分析管线（compute-or-cache）
  ├─ 有 JSON 缓存 → 直接加载 data/ui_samples/<stem>_b2b_adaptive_sage.json
  └─ 无缓存 → 后台异步跑生成管线 → 产出 JSON（载波频率作为参数传入）
  ▼
FastAPI（src/frontend_app.py）serve JSON
  ▼
前端 ECharts / leaflet 渲染（风格照 matplotlib 参照图）
```

- 后端已是「serve 已导出 JSON」的薄层，沿用此架构。
- 分析产物是 **JSON 数据**（非 PNG）；PNG 仅作风格参照。

## 4. 展示内容（已锁定）

### 4.1 汇总图（整段测量，可交互，风格照参照图）

| 图 | 数据源(JSON key) | ECharts 类型 | 风格参照 |
|---|---|---|---|
| PDP 原始瀑布 | `cirWaterfall` | heatmap | `adaptive_original_pdp_waterfall.png`（jet） |
| SAGE 多径 delay-time-power | `mpcScatter` | scatter（色=powerDb） | `adaptive_separate_delay_time_power.png`（hot） |
| doppler-time-power | `mpcScatter` | scatter（色=powerDb） | `adaptive_separate_doppler_time_power.png`（hot） |

- **配色 jet/hot，但取值范围自适应数据**（按实际 min/max 或稳健分位数自动定 `visualMap`，不写死 dB 区间）。
- 长宽比按参照图（~2:1）排，避免压扁。

### 4.2 逐帧交互区（保留现有）

| 图 | 数据源 | 类型 |
|---|---|---|
| 逐帧 PDP 曲线 | `framePayloads.pdpCurve` | ECharts line |
| GPS 位置 | `rxGps` / `txGps` | leaflet（随帧切换当前 Rx 点） |

### 4.3 状态栏

场景、Tx 模式、载波频率、当前帧时间、Tx-Rx 距离、N_MPC、coverage、检测到的帧间隔。

## 5. 左侧栏工作流（控件）

1. 选 Rx `.bin`（必填）
2. 选校准 `.bin`（可选）
3. **载波频率输入框**（新增，算 Doppler 用）
4. Tx 坐标：静止→手输 lat/lon/alt；运动→加载 Tx `.bin`（按钮置灰，标"待开发"）
5. **「导入」按钮**（新增）：同时选了校准+测量则一起导入；未选校准则只导入测量（校准可选）
6. **「分析」按钮**：compute-or-cache，载波频率作为参数传入

## 6. 新增的有用按钮（删摆设、补有用）

- **重新分析 / 强制重算**：忽略缓存重跑管线
- **导出当前图 / 数据**：图→PNG，当前帧/窗口数据→CSV
- **跳转时间 / 帧**：输入框直达，替代/合并冗余的「上一帧/下一帧」
- **范围缩放 + 读数游标**：时延轴缩放、十字游标读数开关

## 7. 回放控制（自适应降采样）

- 测量间隔可能为 1ms / 10ms / 其他，展示**每秒 1 个 CIR** 即可。
- **自动检测帧间隔并自适应**：优先用 `meta.frameRateHz` 推算每秒帧数；缺失则用 `rxGps` 时间戳差值兜底。据此把 slider 降采样到 1 CIR/秒。**不写死**。
- slider `max` 对齐到实际可用数据长度（修掉 28308 帧错配）。

## 8. Decision Log

| 决策 | 背景 | 理由 | 备选 | 风险 | 状态 |
|---|---|---|---|---|---|
| 图用可交互 ECharts，非嵌入静态 PNG | 用户要选点读数值 | 满足交互且贴合现有 JSON 架构 | 嵌入静态 PNG（无交互） | 低 | Locked In |
| sage_outputs 图作风格参照 | 用户"不要改风格" | 配色/轴/比例对齐即可满足"心中样式" | 完全自定义风格 | 低 | Locked In |
| colormap jet/hot 但范围自适应 | 用户"不要搞死" | 适应不同数据动态范围 | 写死 dB 区间 | 低 | Locked In |
| compute-or-cache 产 JSON | 重算耗时数分钟 | 缓存命中秒开，未命中后台跑 | 每次都重算 | 中 | Locked In |
| 保留逐帧 PDP/GPS + 回放 | 用户称现有做得好 | 不破坏可用功能 | 删除回放 | 低 | Locked In |
| 降采样到 1Hz 自动检测 | 帧间隔多样 | 展示足够且自适应 | 写死 100Hz | 中 | Locked In |
| 新增载波频率输入 | 算 Doppler 需要 | 参数化分析 | 硬编码频率 | 中 | Locked In |
| 标题去 V2V→「信道测量分析软件」 | 定位是通用信道分析 | 名实相符 | 保留旧名 | 低 | May Evolve（名字可再定） |

## 9. FMEA / 风险

| 失效模式              | 可能性 | 影响  | 缓解                                        |
| ----------------- | --- | --- | ----------------------------------------- |
| 生成管线重算数分钟卡死 UI    | 高   | 重大  | 后台异步执行 + 进度轮询，禁重复点击                       |
| 帧间隔检测错→降采样错       | 中   | 重大  | 优先 `meta.frameRateHz`，缺失用 `rxGps` 时间戳差值兜底 |
| 载波频率未填就算 Doppler  | 中   | 重大  | 导入/分析前校验，必填或给默认值并警告                       |
| bin 名 ↔ 文件夹名映射不一致 | 中   | 重大  | stem 规范化匹配，找不到时明确报错而非空白                   |
| ECharts 大热力图渲染慢   | 中   | 一般  | progressive 渲染 + 合理降采样                    |

## 10. Skill 协作

- 下游：本设计交给 **writing-plans** 出实现计划。Decision Log 中 "Locked In" 项不再重开。
- "May Evolve"：软件最终命名。
