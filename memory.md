# chan_meas 本次工作记录

## 已做的事情

### 1) 联合 delay-doppler 路径数上限调整为 15
- 修改了 `src/ui_dataset.py` 中 `compute_joint_delay_doppler_tracks()` 的默认参数：
  - `max_paths: int = 3` → `max_paths: int = 15`
- 这意味着在每个分析窗口里，联合 delay-doppler 提取模块会尽量保留更多局部峰值路径，而不是只保留少量最强路径。

### 2) 重新跑了测试
- 执行了 `pytest tests/test_ui_dataset.py -q`
- 结果：`12 passed`
- 说明这次改动没有破坏现有的单元测试。

### 3) 重新生成了当前测量结果图
- 使用当前代码重新跑了 `zjk_mea` 这段数据的联合 delay-doppler 分析。
- 这次生成的结果显示：
  - 窗口数：`682`
  - tracks 数：`2252`
  - `pathId` 覆盖 `1~15`
- 结果图已保存到：
  - `artifacts/joint_tracks_last_measurement_max15.png`

### 4) 当前结果的实际观测结论
- `max_paths=15` 确实能让图里出现更多路径。
- 但图面明显更拥挤，出现较多离群点和重叠点，视觉可读性下降。
- 从当前结果看，这更适合做“保留更全路径信息”的中间结果，不太适合作为最终展示图。

### 5) 已实现第一版前端展示层
新增了一个可运行的 FastAPI + HTML + ECharts 离线分析仪表盘。

新增 / 修改文件：
- `src/frontend_app.py`
  - FastAPI 应用入口。
  - 提供 `/` 页面。
  - 提供 `/api/health`、`/api/datasets`、`/api/datasets/default`、`/api/datasets/{name}`。
  - 从 `data/ui_samples/*.json` 读取已导出的前端数据。
  - 对旧样例中只有 `musicMpc`、没有 `jointDelayDoppler` 的情况做了兼容归一。
- `web/index.html`
  - 三栏式工程分析界面。
  - 左侧：数据导入、分析选项、回放控制。
  - 中间：GPS 轨迹、CIR 瀑布图、DPSD 图、MUSIC/SAGE 多径散点、当前帧 PDP、统计表、功率分布。
  - 右侧：数据概览和工程接口说明。
- `web/static/styles.css`
  - 深蓝顶栏、白色卡片、三栏工程软件风格布局。
  - 默认优先适配桌面调试界面。
- `web/static/app.js`
  - 模块化前端逻辑：`initLayout()`、`bindControls()`、`loadDatasetFromApi()`、`loadMockData()`、`syncFrame()`、`updateMapPanel()`、`updateCIRPlot()`、`updateDPSDPlot()`、`updateMusicPlot()`、`updateStatsPanel()` 等。
  - 播放 / 暂停 / 上一帧 / 下一帧 / 时间滑块逻辑已接好。
  - 当前帧变化时会同步地图、图表、统计表、右侧概览。
  - 文件选择入口已预留，JSON 样例可直接本地加载；`.bin` 后续可接上传和后端解析。
  - 提供 ECharts CDN 不可用时的 canvas fallback。
- `web/static/echarts.min.js`
  - 已下载到本地，页面不再依赖外部 CDN 才能显示图表。
- `tests/test_frontend_app.py`
  - 增加前端/FastAPI 行为测试。

### 6) 前端已实际运行验证
- 安装了 FastAPI 依赖：`fastapi`、`httpx`。
- 执行测试：
  - `cd /home/guo/桌面/project/chan_meas && .venv/bin/python -m pytest tests/test_frontend_app.py tests/test_ui_dataset.py -q`
  - 结果：`19 passed, 1 warning`
- 启动服务验证：
  - `cd /home/guo/桌面/project/chan_meas && .venv/bin/python -m uvicorn src.frontend_app:app --host 127.0.0.1 --port 8765`
- API 实测结果：
  - `/api/health` 返回 200，`datasetCount=6`
  - `/api/datasets` 返回 6 个样例数据集
  - `/api/datasets/default` 默认加载 `zjk_last_measurement_max15_full.json`
  - `/` 返回 HTML 页面
- 浏览器实测结果：
  - 页面标题、三栏布局、右侧概览正常。
  - 默认数据 `zjk_last_measurement_max15_full.json` 自动加载。
  - 本地 ECharts 正常渲染，不再依赖 CDN。
  - 时间轴最大帧为 `681`，末尾显示 `681 / 681`。
  - GPS 面板当前 Rx 标签能同步到 `Rx F681`。
  - MUSIC/SAGE 多径散点使用 `jointDelayDoppler.tracks`，当前 tracks 数 `1921`，`pathId` 覆盖到 `15`。

### 7) 修复前端默认数据仍是旧 96 帧样例的问题
- 根因：前端默认仍加载旧的 `zjk_last_measurement_music_sample.json`，它只有 `96` 帧；同时 `build_dataset_from_arrays()` 内部调用 `compute_joint_delay_doppler_tracks()` 时还有一处硬编码 `max_paths=3`。
- 已修复：
  - `src/ui_dataset.py` 中 `build_dataset_from_arrays()` 的联合 delay-doppler 调用改为 `max_paths=15`。
  - `src/frontend_app.py` 默认优先加载 `zjk_last_measurement_max15_full.json`，没有该文件时才回退旧样例。
  - 新增 `scripts/export_full_max15_ui_sample.py`，用于从完整原始 `.bin` 生成窗口级 Web UI 数据。
  - 新增 `data/ui_samples/zjk_last_measurement_max15_full.json`。
- 新 JSON 统计：
  - 原始帧数：`68280`
  - Web UI 窗口帧数：`682`，因此滑块为 `0~681`
  - tracks 数：`1921`
  - `pathId` 覆盖：`1~15`
  - UI 时间轴语义：`joint_delay_doppler_windows`，不是原始逐帧时间轴。

### 8) 修复 DPSD 和 MUSIC/SAGE 图形语义
- 用户指出 DPSD 需要参考 `matlab_code_reference/doppler_spectrum/`，MUSIC/SAGE 要画成上下两个 time-series scatter 子图。
- 已读取参考 MATLAB：
  - `doppler_test.m`
  - `doppler_test_2.m`
  - `doppler_test_3.m`
  - `read_bin_CIR_GPS_doppler_version.m`
- MATLAB 参考逻辑要点：
  - DPSD / Doppler-Delay 图是在原始 CIR 的慢时间窗口上做 FFT：`fft(slow_time_data, [], 2)` / `fftshift`。
  - 常用 `doppler_window=64`、`step_size=50` 或按窗口取当前段。
  - 频率轴按 `linspace(-50, 50, doppler_window)`，图像使用 `imagesc(delay_axis, freq_axis, DPSD')`，`axis xy`，jet/parula 类色图。
- 已修复 DPSD：
  - 新增 `src.ui_dataset.compute_doppler_delay_frame()`。
  - 方法名：`matlab_style_doppler_delay_fft`。
  - 对原始 CIR 每个 UI 窗口中心取 64 帧慢时间窗口，针对前 300 个 delay bin 做 Doppler FFT。
  - 新增 sidecar：`data/ui_samples/zjk_last_measurement_max15_full_dpsd.npz`。
  - sidecar 形状：`(682, 64, 300)`，即 682 个 UI 窗口 × 64 个 Doppler bin × 300 个 delay bin。
  - FastAPI 新增按需接口：`/api/datasets/{name}/dpsd/{frame_index}`。
  - 前端 `updateDPSDPlot()` 当前帧变化时按需请求 DPSD sidecar，显示 Delay Index × Doppler/Hz 的 MATLAB-style FFT 热力图。
- 已修复 MUSIC/SAGE 图：
  - 前端不再画单张 Delay-Doppler 散点图。
  - 改为 `updateMusicTrackPlot()`：上下两个 ECharts grid。
    - 上图：Delay-Time，横轴 Time (s)，纵轴 Delay (ns)。
    - 下图：Doppler-Time，横轴 Time (s)，纵轴 Doppler (Hz)。
  - 15 条 path 用离散颜色和 marker，同时绘制两个子图，series 数为 `30`（15 paths × 2）。
  - MUSIC/SAGE 面板改为横跨分析区整行的大面板，便于接近目标图样式。
- 为避免浏览器缓存旧 JS/CSS，`web/index.html` 已给 `styles.css` 和 `app.js` 加版本参数：`v=20260613-dpsd-music`。
- 验证：
  - 测试结果：`20 passed, 1 warning`。
  - API 验证：`/api/datasets/zjk_last_measurement_max15_full.json/dpsd/681` 返回 `64 × 300` 的 `matlab_style_doppler_delay_fft` 数据。
  - 浏览器 DOM 验证：
    - DPSD 标题：`DPSD t=0s · MATLAB-style FFT`。
    - MUSIC/SAGE ECharts option 中有两个标题：`Delay-Time`、`Doppler-Time`。
    - MUSIC/SAGE 有两个 grid，y 轴分别为 `Delay (ns)`、`Doppler (Hz)`。
    - MUSIC/SAGE series 数为 `30`。

### 9) 2026-06-14 前端布局和地图修正
- 根据用户反馈，GPS 框太长、地图未正常显示，已重排 Web UI：
  - `GPS 轨迹与 Tx/Rx 位置`、`当前帧 CIR/PDP 曲线`、`统计参数` 放到同一行。
  - 删除独立 `功率分布` 卡片和 `powerDistributionChart` DOM；前端不再初始化/更新该图。
  - 主图区改为两段：上方分析图（CIR/Doppler/MUSIC），下方三列（GPS/PDP/统计）。
- 地图瓦片改为 FastAPI 本地代理 + Esri World Imagery：
  - 路由：`/tiles/base/{z}/{x}/{y}.jpg`。
  - 后端函数：`_load_or_fetch_map_tile()`。
  - 缓存目录：`data/tile_cache/esri_imagery/`。
  - 前端 Leaflet 使用本地代理 URL，避免浏览器直接请求 OSM 被 Access blocked。
  - 实测 tile 返回 JPEG，浏览器 tile naturalWidth/naturalHeight = 256。
- 验证：`pytest tests/test_ui_dataset.py tests/test_frontend_app.py -q` → `21 passed, 1 warning`。
- 当前服务运行在 `http://127.0.0.1:8765/`，建议用 `?v=compact-map-3` 或 Ctrl+F5 刷新静态缓存。

### 10) 2026-06-14 分析图最终比例方案
- 用户最终确认采用固定比例而不是继续微调：
  - 第一行：`CIR 瀑布图 / 时延-功率` + `Doppler 谱瀑布图 / Delay 平均`，并排两列，高度 `300px`。
  - 第二行：`MUSIC/SAGE 多径参数` 独占整行，高度 `260px`。
  - 第三行：`GPS 轨迹` / `当前帧 CIR-PDP` / `统计参数`，高度 `190px`。
- 底部三列宽度固定为 `1.6 : 1.2 : 0.65`（GPS 更宽，统计更窄）。
- 当前 CSS：
  - `.analysis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: 300px 260px; }`
  - `.bottom-grid { grid-template-columns: 1.6fr 1.2fr 0.65fr; height: 190px; }`
- 浏览器 DOM 验证：
  - CIR / Doppler：`452.5 × 300 px`
  - MUSIC/SAGE：`917 × 260 px`
  - 底部三列宽度：约 `414 / 311 / 168 px`
- 视觉复查：第一行热力图可读性显著改善；第二行仍是全宽，但整体比例已按用户指定固定。
- 验证：`pytest tests/test_frontend_app.py -q` → `6 passed, 1 warning`。

### 11) 2026-06-14 回放/Doppler/第三行修正
- 用户要求：切换“回放控制”帧时，Doppler 瀑布图不要跟着刷新；恢复“均方根时延”；帧率不要显示 1.0 Hz；第三行再放大一点。
- 已修改 `web/static/app.js`：
  - `syncFrame()` 不再调用 `updateDPSDPlot()`，因此切换帧只更新地图/PDP/统计，不重绘 Doppler 瀑布图。
  - `frameRateLabel` 改为优先显示 `meta.rawFrameRateHz`，当前数据显示 `100.0 Hz`。
  - 统计参数标签从 `均方时延` 改回 `均方根时延`。
- 已修改 `web/static/styles.css`：
  - 第三行 `bottom-grid` 高度从 `190px` 调整到 `220px`。
  - 第三行列宽改为 `1.55 : 1.15 : 0.85`，给统计列更多宽度。
- 浏览器实测：
  - 连续 `syncFrame(1/2/3)` 后，`dpsd.setOption()` 调用次数为 `0`。
  - `frameRateLabel = 100.0 Hz`。
  - 统计表包含 `均方根时延`。
  - 第三行高度 `220px`，列宽约 `390 / 289 / 214 px`。

### 12) 2026-06-14 Doppler 初始化补回
- 在“切帧时不刷新 Doppler 瀑布图”的修正后，出现了 Doppler 图首次加载不显示的问题。
- 根因：`syncFrame()` 去掉了 `updateDPSDPlot()`，但 `setDataset()` 里没有补上首次初始化绘制。
- 已修复：`setDataset()` 现在按顺序调用
  - `updateCIRPlot()`
  - `updateDPSDPlot()`
  - `updateMusicPlot()`
  - `syncFrame(0)`
- 当前行为：
  - 数据集加载时，Doppler 瀑布图绘制一次；
  - 后续切换帧时，Doppler 瀑布图不重绘；
  - 地图 / 当前帧 PDP / 统计参数随帧更新。
- 验证：`pytest tests/test_frontend_app.py -q` → `6 passed, 1 warning`。

### 13) 2026-06-14 第一版功能性 delay-Doppler SAGE 已接入
- 按当前项目约束实现了第一版单天线 `delay-doppler SAGE`，重点是功能可用，不做 CFO 补偿，不做角度维。
- 新增文件：
  - `src/signal/delay_doppler_sage.py`
- 主要实现：
  - 先对每个慢时间窗口做 2D FFT，提取 delay-Doppler 初值；
  - 对每条路径做局部 SAGE / CLEAN-SAGE 式优化：delay 邻域搜索、Doppler 邻域搜索、LS 幅度更新；
  - 支持可选 GPU FFT 初始化（`use_gpu=True` 且本机 CUDA 可用时启用）；
  - 仍然遵循物理 delay gate，不直接搜索全部 `1024` 个 delay bin。
- `src/ui_dataset.py` 已新增：
  - `compute_sage_delay_doppler_tracks()`
  - `build_dataset_from_arrays(..., include_sage=True)`
  - `build_measurement_dataset(..., include_sage=True)`
  - `export_measurement_dataset(..., include_sage=True)`
- 当前输出字段：
  - `sageDelayDoppler`
  - 每条 peak 附带 `amplitudeReal` / `amplitudeImag`
  - `mpcScatter` 在启用 SAGE 时优先使用 SAGE tracks
- 已新增测试：
  - 单窗口两径恢复
  - dataset 集成输出 `sageDelayDoppler`
- 实测命令：
  - `cd /home/guo/桌面/project/chan_meas && .venv/bin/python -m pytest tests/test_ui_dataset.py::test_compute_sage_delay_doppler_tracks_recovers_two_paths_in_one_window tests/test_ui_dataset.py::test_build_dataset_from_arrays_includes_sage_tracks_when_requested -q`
  - 结果：`2 passed`
  - `cd /home/guo/桌面/project/chan_meas && .venv/bin/python -m pytest tests/test_ui_dataset.py tests/test_frontend_app.py -q`
  - 结果：`23 passed, 1 warning`
- 当前版本仍是“第一版功能实现”，还没有做：
  - 跨窗口全局 trackId 连续跟踪
  - CFO 补偿接入
  - fractional-delay 精细化
  - 面向真实 420 MHz 数据的参数整定脚本

### 14) 2026-06-15：420 MHz 最后一组数据的 SAGE 问题定位与 v2 修正
- 测试数据：
  - `/mnt/win_data/data_mea/0121campus_test/0121mea/接收数据帧_20260121115358435.bin`
  - 总帧数：`35788`，帧率 `100 Hz`，总时长约 `357.88 s`
  - 主要测试窗口：`50` 帧，`step=50`，delay gate `0–6000 ns`（前 `300` 个 delay bins）
- 用户指出：UI 的 PDP 瀑布图中肉眼可见多条连续 delay-time 多径脊线，但第一版 SAGE 估计结果大量集中在主径附近，其他径稀疏或缺失。
- 问题定位：原 `src/signal/delay_doppler_sage.py` 第一版实现更像单 bin 的 delay-Doppler CLEAN-SAGE 简化版，不足以解释真实匹配滤波 CIR：
  - 路径 atom 原来是单 delay-bin 冲激：`s_path[:, delay_col] = amp * tone`，无法扣除真实路径在 delay 维的主瓣/裙边/旁瓣，导致后续路径继续被主径残留吸附。
  - 初始化原来主要依赖 2D delay-Doppler FFT 全局强峰，偏向相干主径和主径邻域，PDP 瀑布图里功率明显但相干性较弱的次径难进入初值。
  - refine 原来只搜 `±1 bin`，一旦初始化落到主径附近，就难以跳到远处次径。
  - 路径功率原来把 `residual_floor` 加进每条路径功率，压缩动态范围，弱径/噪声径不易区分。
- 已修改核心 SAGE 实现：
  - 文件：`src/signal/delay_doppler_sage.py`
  - 新增 PDP-assisted、delay-diverse 初始化：用窗口内 robust PDP（median + 75 分位）找 delay 局部峰，再估 Doppler。
  - 默认 `init_strategy="pdp"`，避免只靠 FFT 主径吸附。
  - 新增有限宽度 delay pulse/kernel atom：路径模型变为 `amp × exp(j2πf_d t) × delay_kernel(τ-τ_l)`，不再是单 bin delta。
  - delay refine 默认扩大到约 `±8 bins`；仍保持单天线 delay-Doppler SAGE，不引入角度维。
  - 路径功率改为只由拟合幅度 `|amp|²` 给出，不再把残差底噪加到每条路径。
  - 保持 `estimate_window_paths()` 接口兼容，并额外支持 `pulse_half_width_bins`、`delay_search_bins`、`init_strategy` 等参数。
- 验证脚本：
  - `scripts/run_sage_v2_alltime_50frames.py`
- SAGE v2 全时长 50 帧窗口运行结果：
  - 输出目录：`/mnt/win_data/data_mea/0121campus_test/sage_v2_alltime_50frames/`
  - CSV：`sage_v2_paths_50frame_windows.csv`
  - delay-power 图：`01_sage_v2_delay_power_scatter.png`
  - doppler-power 图：`02_sage_v2_doppler_power_scatter.png`
  - PDP 可见峰叠加图：`03_overlay_pdp_visible_peaks_vs_sage_v2.png`
  - 路径数诊断图：`04_sage_v2_path_count_diagnostics.png`
  - 窗口数：`715`；路径总数：`1968`；平均 `2.75` 条/窗口；每窗口最少 `1`，最多 `8`。
- 重要观测：
  - 平均 `2.75` 条/窗口容易误导，因为分布两极化：`394` 个窗口只有 `1` 条，但 `166` 个窗口超过 `5` 条，其中 `122` 个窗口为 `7–8` 条。
  - SAGE v2 不再只集中于主径，已经能在部分时段估出 `2800–3000 ns`、`3300–3800 ns`、`4400–5400 ns` 等次径/弱径。
  - 但 SAGE v2 目前召回偏高：图中大量深蓝/紫色小点是 SAGE 输出的 raw weak candidates，通常约为相对最强路径 `-25~-35 dB`，不能直接解释为有效物理 MPC。
  - 这些弱点可能来自噪声局部峰、DMC/弥散多径、主径旁瓣残留、垂直强带瞬态干扰或单窗口不稳定候选。
  - PDP 瀑布图中约 `270 s` 附近有垂直强带/全 delay 变亮现象，会诱发大量异常路径和 Doppler 野点，应作为 snapshot outlier / transient event 处理。
- 当前结论：
  - 原第一版 SAGE 结果集中到主径，是实现问题，不是 SAGE 原理必然如此。
  - SAGE v2 修复了主径吸附的一部分问题，但还缺少 path validation / pruning / model order selection。
  - 后续不应把所有 raw SAGE candidates 当真实 MPC，应区分：`valid specular MPC`、`DMC/background`、`sidelobe/residual artifact`、`noise/transient outlier`。
- 测试：
  - `python3 -m pytest tests/test_ui_dataset.py -q` → `17 passed`
  - 全量 `pytest` 在当前系统 Python 下因缺 `fastapi` 采集失败，和 SAGE 修改无关；项目 `.venv` 里此前前端测试可用。
- 已同步更新 skill：`wireless-dataset-analysis` 的 `references/chan-meas-delay-doppler-sage.md`，记录不要只用 FFT 初始化、不要单 bin atom、需要 PDP-assisted delay-diverse seeds 和有限 pulse/kernel atom。

### 15) 2026-06-15：SAGE/HRPE 文献调研问题凝练
- 为后续用 Perplexity/论文检索调研，已凝练关键研究问题：
  - wideband channel sounder 中 SAGE/RiMAX 的正确路径 atom：是否必须包含 pulse shape、fractional delay、系统响应/B2B 校准；
  - PDP waterfall visible ridges、specular MPC、DMC、clutter/noise 的区分；
  - SAGE/RiMAX/HRPE 初始化方法：successive cancellation、CLEAN、noncoherent ML、PDP-assisted initialization、RiMAX initialization；
  - model order selection / path pruning：likelihood improvement、AIC/BIC/MDL、path SNR、residual reduction、CRLB/估计方差、最小轨迹持续时间、跨窗口 tracking consistency；
  - time-varying channel 中固定 50 帧窗口是否过长，是否需要 recursive SAGE、Kalman/KEST/RIMAX tracking、或允许 delay drift 的模型；
  - 垂直强带/瞬态干扰帧的 snapshot quality gating、robust likelihood、outlier rejection。
- 当前倾向的技术路线：
  - 保留 SAGE/HRPE 框架估计 specular MPC；
  - 路径 atom 用系统 pulse shape / fractional delay，而不是单 bin；
  - 初始化采用相干 FFT + robust PDP 峰混合，但最终必须经过似然/SNR/持续性剪枝；
  - 输出分层：specular MPC、DMC/background、异常窗口，而不是把 PDP 所有可见峰都当 specular path。

## 还没有做的事情

### 1) 还没有做结果可读性增强
当前只是把路径数放大了，没有同步做下面这些抑制杂散峰的措施：
- 离群点过滤
- 平滑或中值滤波
- 对异常延迟 / 异常多普勒做裁剪
- 只保留主路径并弱化其余路径的展示

### 2) 还没有做路径跨窗口连续跟踪
- 现在的 `pathId` 主要是每个窗口内部按峰值排序得到的编号。
- 还没有做跨窗口的轨迹关联、身份保持、重编号或全局跟踪。
- 所以不同窗口里的同一 `pathId` 不一定代表同一条物理路径。

### 3) 前端还没有接真实 `.bin` 上传解析
- 当前 FastAPI 只读取已经导出的 `data/ui_samples/*.json`。
- 左侧“选择文件”按钮在前端已预留事件；选择 JSON 可直接加载。
- 但选择 `.bin` 后还没有上传到后端，也没有触发 `build_measurement_dataset()` 实时解析。
- 后续可增加 `/api/analyze` 或 `/api/upload/rx`，把 `.bin` 文件上传后调用现有 Python 数据层生成 dataset。

### 4) 前端还没有 Electron / PyWebView 打包壳
- 当前是浏览器 + FastAPI 本地服务。
- 还没有做 Windows 安装包、Electron、PyWebView 或桌面快捷方式。

### 5) 还没有做最终展示版输出整理
- 虽然当前结果图已经保存在项目的 `artifacts/` 目录里，但还没有进一步整理成正式报告或图集。
- 还没有生成适合直接发给别人看的最终版图注与说明。

### 6) 还没有回退或比较别的推荐参数
- 目前只验证了 `max_paths=15` 的版本。
- 还没有系统比较 `3 / 4 / 8 / 15` 这些参数在同一数据上的视觉效果和物理解释性。

### 7) SAGE 当前实现约束与方向
- 当前 SAGE 测试载频只有 `420 MHz`，因此在现有 `10 ms / 100 Hz` 帧率下，Doppler 不模糊范围较小的问题暂时可接受。
- 第一版 SAGE 只做功能性：单天线 delay-Doppler SAGE / CLEAN-SAGE，不考虑角度维。
- 暂不做 CFO 补偿；以后补充相应 B2B / 静态 OTA / 真实 CFO 数据后再接入公共相位补偿。
- 不直接搜索全部 `1024` 个 delay bin；默认继续遵循物理 delay gate，优先限制在约 `0–6000 ns`，即前约 `300` 个 delay bin，除非明确指定更大范围。
- 可选 GPU 加速可以开启，但优先保证算法接口、输出格式和功能正确。
- 即使不做高精度 fractional-delay 细化，也需要在 FFT 峰值附近做局部优化，例如 delay 邻域和 Doppler 邻域的局部搜索 / LS 幅度更新。

## 运行方式

启动本地 Web UI：

```bash
cd /home/guo/桌面/project/chan_meas
.venv/bin/python -m uvicorn src.frontend_app:app --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

测试：

```bash
cd /home/guo/桌面/project/chan_meas
.venv/bin/python -m pytest tests/test_frontend_app.py tests/test_ui_dataset.py -q
```

## 备注
- 如果目标是“更完整地保留多径信息”，`15` 是更保守的配置。
- 如果目标是“图要清楚好读”，后续仍然建议考虑降到 `3` 或 `4`，或者在保留 15 条的同时加上过滤与降噪逻辑。
- 下一步最自然的是：把左侧 `.bin` 文件选择接到 FastAPI 上传接口，然后调用 `src.ui_dataset.build_measurement_dataset()` 实时生成前端 dataset。
