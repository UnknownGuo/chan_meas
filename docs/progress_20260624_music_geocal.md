# 进度记录 2026-06-24：MUSIC 提取 + 模块B源切换 + 地图修复 + 几何时延校准

> 本文档为会话交接记录。状态：几何时延校准功能已实现并全量应用，但**发现远场数据集 GPS 距离与实测 LOS 不一致（Δτ<0），处理方式待用户决定**（当前卡点）。

---

## 一、本次会话完成的功能

### 1. MUSIC 多径提取算法（频域空间平滑 MUSIC 估时延）
- **新文件** `src/signal/music_delay.py`
  - `estimate_window_delays_music()`：CIR 窗内相干平均 → FFT → 前后向平滑协方差（M=600≈0.586·N）→ 特征分解 → **MDL 自动定阶**（替代 matlab `MPC_number.m` 写死的 D=30）→ 扫描时延谱 `1/(a'·En·En'·a)` → findpeaks
  - 每径输出 `(delay_bin, delay_ns, power_db)`；**功率取自该时延 bin 的实际 PDP（20log10|相干平均CIR|），不是谱峰高度**；无多普勒、无复幅度
  - 参考：`matlab_code_reference/Wuhan_3_scenarios/MPC_number.m`、`test_use.m`
- **接入** `src/ui_dataset.py`：`compute_music_delay_tracks()`，新 key `musicDelay`（与 `sageDelayDoppler` 并列），合成 `amplitude=√(10^(P/10))`、`dopplerHz=0` 以兼容模块B；新参数 `include_delay_music`
- 效果：MUSIC 每窗多径数远多于 SAGE（xiaoquan: SAGE median 1 → MUSIC median 6，≥3条窗口 82%），解决"单径窗口太多算不了 RMS/K因子"的诉求

### 2. 模块 B 数据源切换（SAGE / MUSIC）
- `src/analysis/module_b.py`：`build_module_b_payload(ds, source="sage"|"music")`，**统计数学逻辑零改动**，只切换读哪个 windowTracks；MUSIC 下 `dopplerAvailable=False`
- `src/frontend_app.py`：`/api/datasets/{name}/module-b?source=sage|music`，分 source 缓存 `{stem}_module_b_{source}.json`
- 前端 `web/index.html` + `web/static/app.js`：模块B顶部 SAGE/MUSIC 切换条；MUSIC 下「RMS 多普勒」面板显示 N/A
- 效果：MUSIC 把可用统计窗口数翻倍（xiaoquan K因子 119→270，RMS时延 119→223）

### 3. 地图"全球视图"bug 修复
- 根因：`updateMapPanel`（`app.js`）里 `fitBounds` 在 `invalidateSize` 之前调用，容器尺寸为0时退化成世界视图
- 修复：fitBounds 前先同步 invalidateSize；切回模块A时重新定位地图；tx坐标加有限性保护
- 与 GPS 数据无关（数据本身干净，都在 40.303°N,115.772°E）

### 4. 几何时延校准（GPS 几何 → 主径时延对齐）
- **新文件** `src/calibration/geometric_delay.py`
  - `compute_delay_shift()`：τ_geo = d/c，τ_peak = 首帧 argmax|CIR|/BW，Δτ = τ_peak − τ_geo
  - `apply_delay_shift()`：频域乘 `exp(+j2πf·Δτ)`（分数 bin 精确平移，纯相位**不改功率**）
- 接入 `src/ui_dataset.py`：B2B 校准后、SAGE/MUSIC 前；`rx_first_alt_m` 驱动；meta 记录 `geometricDelayCal`
- **离地高度语义**：输入是 Rx 天线**离地高度**（非绝对海拔），`d=√(水平²+离地高度²)`，水平距离用 GPS haversine
- 后端 `analyze.py`/`frontend_app.py`：`AnalyzeRequest.rxFirstAltM`；顺手给实时分析也补了 `include_delay_music=True`
- 前端：侧边栏「Rx 首帧离地高度」输入框

---

## 二、关键文件清单（本次新增/修改）

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/signal/music_delay.py` | 新增 | MUSIC 算法 |
| `src/calibration/geometric_delay.py` | 新增 | 几何时延校准算子 |
| `src/ui_dataset.py` | 修改 | compute_music_delay_tracks、几何校准接入、include_delay_music/rx_first_alt_m 参数 |
| `src/analysis/module_b.py` | 修改 | source 参数（sage/music） |
| `src/frontend_app.py` | 修改 | module-b?source=、AnalyzeRequest.rxFirstAltM、_run_analysis |
| `src/pipeline/analyze.py` | 修改 | rx_first_alt_m + include_delay_music=True |
| `web/index.html` | 修改 | SAGE/MUSIC 切换条、Rx离地高度输入框、缓存版本 v=20260624-geocal |
| `web/static/app.js` | 修改 | setModuleBSource/loadModuleB、地图修复、rxFirstAltM |
| `web/static/styles.css` | 修改 | mb-toolbar 样式 |
| `tests/test_music_delay.py` | 新增 | MUSIC + 模块B源切换 |
| `tests/test_geometric_delay.py` | 新增 | 几何校准 |
| `config/local.py` | 修改 | ZJK_RAW_ROOT 修正为 `/mnt/win_data/data_mea/zjk_mea_260610`（旧路径 zjk_mea 已失效；gitignored） |

**测试状态**：`pytest tests/` → **56 passed**

---

## 三、当前数据状态

- 全部 **19 个 UI 数据集**（`data/ui_samples/*_b2b_adaptive_sage.json`）均为：当前代码 SAGE + MUSIC + **几何校准（统一离地高度 2.0m）**
- `module_b_cache` 已清空（延迟已变，按需重算）
- UI 服务运行中：http://127.0.0.1:8765
- 原始数据：`/mnt/win_data/data_mea/zjk_mea_260610/`（注意目录名带 _260610）

---

## 四、⚠️ 当前卡点：几何校准的 GPS 一致性问题

全量应用后发现 **5 个远场数据集 Δτ<0（实测主径比几何 LOS 还早到，物理不可能）**：

| 数据集 | d(GPS) | τ_geo | τ_peak | Δτ | 判定 |
|--------|--------|-------|--------|-----|------|
| 近场 (xiaoquan/3m/5m/9m/rotate…) | 8~20m | 26~70ns | 60~120ns | +30~90ns | 正常 |
| 100m_data | 100m | 334ns | 140ns | **−194ns** | ⚠ |
| 100-200m | 100m | 335ns | 40ns | **−295ns** | ⚠ |
| 196m_data | 203m | 676ns | 300ns | **−376ns** | ⚠ |
| 196m_smwhere | 196m | 653ns | 460ns | **−193ns** | ⚠ |
| smw-0m | 120m | 400ns | 100ns | **−300ns** | ⚠ |

**诊断**：
- "0m-0m" 共置数据集实测 τ_peak 仍有 60~120ns → 系统/触发**基线延迟**（硬件固有）
- 远场实测峰完全不跟随 GPS 距离（100m 应 ≈60+334ns，实测仅 140ns）→ **远场 GPS 距离/首帧位置与实测 LOS 对不上**
- 近场 GPS 距离本身也被几米级 GPS 噪声主导（"3m_data" 算出 7.7m）

**RMS 时延扩展确实会变**（之前误说"不变"，已纠正）：
- xiaoquan SAGE：median 116.6→79.7ns（−32%），参与窗口数 119→236（证明 SAGE 在平移后CIR上重估，径集合本身变了，非纯平移）
- 196m：median 264→245ns（−7%）
- 机制：① 时延门控边界截断 + ② SAGE/MUSIC 非严格平移等变

**待用户决定的处理方向**（已问，用户选择先澄清，未定）：
1. 只对 Δτ 合理的数据集启用，远场标注"几何校准不适用"
2. 先核查远场首帧 Rx GPS/轨迹（是否应取轨迹起点而非终点）
3. 照旧全部应用
4. 撤销几何校准，保留代码待 GPS 问题理清

**可深入的诊断点**（用户想澄清的方向）：
- 拉远场数据集首帧 GPS + 轨迹 + 首帧 PDP 最强几个峰，判断是首帧位置错还是主径找错
- 用所有 0m-0m 数据集反推系统基线延迟是否为稳定常数（若是，应校"τ_peak − 基线 = 传播"而非直接对齐 τ_geo）
- τ_peak 取法：现在是首帧全局 argmax，可能被近 bin-0 直流/旁瓣或强反射带偏；可试"前N帧平均PDP峰"或"加最小时延门限"
- 是否应改用**已知真实距离**而非 GPS 距离做基准

---

## 五、其他挂起事项

- **功能测试固化为回归用例**：已有 `scripts` 外的临时测试（scratchpad `functional_test.py` 端点+接线审计 33/33；`ui_button_test.py` CDP 真实点击，环境不稳未跑通）。可固化成 `tests/test_frontend_endpoints.py`
- **网页按钮测试边界**：会发请求的按钮已端点级强验证；纯前端交互（导出图/csv、回放、模型下拉）仅静态接线审计，未在浏览器真实点击验证
- **git 提交**：当前 master 分支累积大量未提交改动（含本次全部新增）。提交建议先开分支。本次会话未提交。

---

## 六、运行信息

```bash
# 启动 UI 服务
cd /home/guo/桌面/project/chan_meas
.venv/bin/python -m uvicorn src.frontend_app:app --host 127.0.0.1 --port 8765

# 跑测试
PYTHONPATH=/home/guo/桌面/project/chan_meas .venv/bin/python -m pytest tests/ -q

# 重新导出单个数据集（含 SAGE+MUSIC+几何校准）
# 参考 scratchpad 脚本 batch_reexport_geocal.py / backfill_music.py
```
