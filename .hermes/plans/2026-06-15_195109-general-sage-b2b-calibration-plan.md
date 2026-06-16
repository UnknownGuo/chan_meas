# 通用 SAGE + B2B 校准改造方案

> **For Hermes:** This is a planning-only document. Do not implement until user confirms.

**Goal:** 把当前 chan_meas 中的 delay-Doppler SAGE 从“针对某一次图像现象调参”的实验脚本，升级为面向多地点、多批次测量的通用、完整、可复用处理流程，并接入新测的 B2B 校准文件 `/mnt/win_data/data_mea/zjk_mea/cali_data.bin`。

**Architecture:** 采用分层流程：B2B 校准 → 原始测量 CIR → 校准后的 effective pulse/system response → SAGE raw candidates → 通用 validation/pruning → track-level 输出。输出目录按测量数据根目录组织，当前 zjk_mea 的图和结果统一放到 `/mnt/win_data/data_mea/zjk_mea/` 下，不再写入之前的 `/mnt/win_data/data_mea/0121campus_test/...`。

**Tech Stack:** Python, NumPy, Matplotlib, existing chan_meas modules (`src/io/bin_read.py`, `src/signal/delay_doppler_sage.py`, `src/ui_dataset.py`), pytest.

---

## 0. 总原则

1. 不再以某一次用户举例的视觉目标作为唯一优化目标。
2. SAGE 输出必须分层：
   - raw candidates: 算法候选，不等于真实 MPC；
   - pruned candidates: 通过单窗口基础剪枝；
   - validated MPCs: 通过跨窗口一致性/显著性验证；
   - DMC/background: PDP 可见但不宜解释成 specular MPC 的能量；
   - outlier windows: 垂直强带、全 delay 抬升、设备异常等坏窗口。
3. 参数应围绕物理模型和统计判据，而不是为了让某一张图看起来像预期结果。
4. 所有批次的输出应跟随输入数据目录，例如当前 zjk_mea 输出到 `/mnt/win_data/data_mea/zjk_mea/sage_outputs/` 或 `/mnt/win_data/data_mea/zjk_mea/figures/`。
5. 保留 raw 结果，后处理剪枝另存，避免调参覆盖原始候选。

---

## 1. 当前问题复盘

### 1.1 已确认在理的部分

- 单 delay-bin delta atom 会造成主径剥离不完整，是主径吸附/旁瓣伪检的重要原因。
- PDP waterfall 可见脊线不等价于 specular MPC。
- PDP-assisted initialization 是合理方向，但只能作为 proposal generator，不能把所有 PDP 峰当真实路径。
- 270s 一类全 delay 垂直强带应被标记为 outlier/snapshot-quality 问题，而不是解释为真实多径同时出生。
- raw SAGE candidates 必须经过剪枝、跟踪、稳定性验证后，才能叫 validated MPC。

### 1.2 当前临时剪枝的局限

已加的 local prominence pruning 让结果看起来更干净，但它仍然是单窗口启发式规则。它不能作为最终通用完整程序的核心依据，因为：

- 阈值 3 dB / -12 dB 仍是经验数；
- 不使用 B2B 校准得到的真实 pulse shape；
- 不做 DMC/colored residual 建模；
- 不做跨窗口轨迹关联；
- 不做系统性的 snapshot quality gating；
- 不区分真实弱径和短寿命伪检。

因此后续要把它降级为“简化 fallback pruning”，而不是最终判据。

---

## 2. 新 B2B 校准文件接入

### Input

- B2B 校准文件：`/mnt/win_data/data_mea/zjk_mea/cali_data.bin`
- 输出根目录：`/mnt/win_data/data_mea/zjk_mea/`

### 目标输出

建议新增：

- `/mnt/win_data/data_mea/zjk_mea/calibration/`
  - `b2b_cir.npy`
  - `b2b_avg_pulse.npy`
  - `b2b_effective_pulse_kernel.npy`
  - `b2b_calibration_summary.json`
- `/mnt/win_data/data_mea/zjk_mea/figures/`
  - `b2b_01_avg_pdp.png`
  - `b2b_02_pulse_kernel.png`
  - `b2b_03_frame_energy_quality.png`
  - `b2b_04_delay_sidelobe_profile.png`
- `/mnt/win_data/data_mea/zjk_mea/sage_outputs/`
  - later SAGE CSV/JSON/figures

### B2B 校准处理思路

1. 读取 `cali_data.bin`，沿用 `src/io/bin_read.py` 中已有帧解析和 `_sliding_correlate()`。
2. 得到 B2B CIR 后，不直接把峰值 bin 当 delta，而是估计 effective pulse shape：
   - 找到 B2B 平均 PDP 主峰；
   - 取主峰附近例如 ±16 或 ±32 bins；
   - 做相位对齐后复数平均，得到复数 pulse kernel；
   - 同时保存 normalized magnitude kernel 和 complex kernel。
3. 输出 B2B 诊断图：
   - 平均 PDP 是否有清晰主峰；
   - 主瓣宽度、旁瓣水平；
   - 帧间能量稳定性；
   - 加 60 dB 衰减后动态范围是否足够。
4. 若 B2B 数据本身不稳定，应先标记校准质量，而不是把坏 kernel 写进 SAGE。

---

## 3. 通用 SAGE 架构改造

### 3.1 模块拆分建议

新增或改造以下文件：

- `src/calibration/b2b.py`
  - 负责 B2B CIR 读取、pulse kernel 提取、质量评估、保存/加载。
- `src/signal/delay_doppler_sage.py`
  - 保留核心 SAGE 算子。
  - 增加可选 `pulse_kernel` 输入。
  - 若提供 B2B kernel，优先用真实 kernel；否则 fallback 到当前 Gaussian kernel。
- `src/signal/sage_validation.py`
  - 单窗口候选剪枝、局部 SNR、local prominence、residual improvement、snapshot quality gating。
- `src/signal/sage_tracking.py`
  - 跨窗口轨迹关联、持续性筛选、轨迹平滑、birth/death 管理。
- `scripts/run_zjk_sage_pipeline.py`
  - 面向 zjk_mea 的完整 pipeline CLI。
- `scripts/extract_b2b_calibration.py`
  - 只跑 B2B 校准和图。

### 3.2 SAGE 输出数据结构

每个窗口输出不应只有一组 `peaks`，建议改为：

```json
{
  "windowIndex": 0,
  "timeSec": 0.25,
  "snapshotQuality": {
    "isOutlier": false,
    "reason": null,
    "totalEnergyDb": -73.2,
    "noiseFloorDb": -112.4,
    "flatDelayBurstScoreDb": 1.1
  },
  "rawCandidates": [],
  "prunedCandidates": [],
  "validatedCandidates": [],
  "dmcSummary": {}
}
```

最终全局输出再增加：

```json
{
  "tracks": [],
  "outlierWindows": [],
  "calibration": {},
  "parameters": {},
  "figures": {}
}
```

---

## 4. 通用判据设计

### 4.1 Snapshot quality gating

用于处理垂直强带，不针对某一时刻写死。

候选特征：

- 每帧/每窗口总 CIR 能量；
- delay 后段或无效 delay gate 的噪声底；
- 全 delay 同步抬升程度；
- 峰值数量异常；
- robust z-score 或 MAD score。

判定结果：

- `normal`: 正常跑 SAGE；
- `degraded`: 可以估计已有强轨迹，但禁止新增弱路径 birth；
- `outlier`: 不做 SAGE birth，输出 outlier window。

### 4.2 单窗口 candidate pruning

组合判据，不只靠功率：

- 相对本窗口最强径功率；
- local delay prominence；
- 与 B2B pulse sidelobe 位置是否一致；
- 加入该路径后的 residual improvement；
- Doppler 是否落在可解释范围；
- 是否位于 delay gate 边界附近。

输出：`rawCandidates` → `prunedCandidates`。

### 4.3 跨窗口 validation/tracking

这是通用化关键。

规则建议：

- 相邻窗口用 delay 和 Doppler 距离做关联；
- 可先用 greedy nearest-neighbor，后续再用 Hungarian；
- 轨迹必须满足最小持续时间，例如连续 3–5 个窗口，或总持续时间超过 1–2 s；
- delay 变化速度不能突变；
- Doppler 变化不能无规律大跳；
- 短寿命、低功率、无连续性的点标为 false alarm 或 DMC/background。

最终只有 track-level 通过的才叫 validated MPC。

---

## 5. 输出图设计

当前 zjk_mea 输出全部放在：

- `/mnt/win_data/data_mea/zjk_mea/figures/`
- `/mnt/win_data/data_mea/zjk_mea/sage_outputs/`

建议图集：

### B2B calibration figures

1. `b2b_01_avg_pdp.png`
2. `b2b_02_effective_pulse_kernel.png`
3. `b2b_03_frame_energy_quality.png`
4. `b2b_04_sidelobe_profile.png`

### Measurement SAGE figures

1. `sage_01_raw_candidates_delay_time.png`
2. `sage_02_pruned_candidates_delay_time.png`
3. `sage_03_validated_tracks_delay_time.png`
4. `sage_04_pdp_visible_peaks_overlay.png`
5. `sage_05_outlier_windows.png`
6. `sage_06_path_count_diagnostics.png`
7. `sage_07_doppler_time_tracks.png`
8. `sage_08_residual_quality.png`

关键点：raw/pruned/validated 三张图分开，避免把“看起来很多点”和“真实 MPC”混在一起。

---

## 6. 实施步骤

### Task 1: 只做 B2B 校准诊断脚本

目标：确认 `/mnt/win_data/data_mea/zjk_mea/cali_data.bin` 可读、质量是否足够、pulse kernel 是否稳定。

涉及文件：

- Create: `src/calibration/b2b.py`
- Create: `scripts/extract_b2b_calibration.py`
- Test: `tests/test_b2b_calibration.py`

验证：

- 输出 B2B summary JSON；
- 输出四张 B2B 图到 `/mnt/win_data/data_mea/zjk_mea/figures/`；
- pytest 通过。

### Task 2: SAGE 支持外部 pulse kernel

目标：让 SAGE atom 从 Gaussian fallback 变成可使用 B2B complex kernel。

涉及文件：

- Modify: `src/signal/delay_doppler_sage.py`
- Test: `tests/test_delay_doppler_sage.py` 或 `tests/test_ui_dataset.py`

验证：

- 合成双径测试仍能恢复；
- 用非 delta kernel 的合成测试验证不再把主径旁瓣当路径。

### Task 3: Snapshot quality gating

目标：通用检测全 delay 突发、能量异常、噪声底抬升。

涉及文件：

- Create: `src/signal/sage_validation.py`
- Test: `tests/test_sage_validation.py`

验证：

- 合成 flat-delay burst 被标为 degraded/outlier；
- 正常双径窗口不被误杀；
- 输出 outlier reason。

### Task 4: 单窗口 candidate pruning 标准化

目标：把当前 local prominence heuristic 收进 validation 模块，作为多判据之一，而非硬编码在 SAGE 核心末尾。

涉及文件：

- Modify: `src/signal/delay_doppler_sage.py`
- Modify/Create: `src/signal/sage_validation.py`
- Test: `tests/test_sage_validation.py`

验证：

- raw candidates 保留；
- pruned candidates 可复现；
- 参数写入 summary。

### Task 5: Track-level validation

目标：把 pruned candidates 关联成 tracks，只把稳定轨迹标为 validated MPC。

涉及文件：

- Create: `src/signal/sage_tracking.py`
- Test: `tests/test_sage_tracking.py`

验证：

- 合成连续轨迹可被关联；
- 孤立单点被丢入 false alarm；
- 轨迹 ID 跨窗口稳定。

### Task 6: zjk_mea pipeline CLI

目标：一条命令跑完整流程，但当前不要急着执行。

涉及文件：

- Create: `scripts/run_zjk_sage_pipeline.py`

命令形式建议：

```bash
cd /home/guo/桌面/project/chan_meas
.venv/bin/python scripts/run_zjk_sage_pipeline.py \
  --measurement-dir /mnt/win_data/data_mea/zjk_mea \
  --b2b /mnt/win_data/data_mea/zjk_mea/cali_data.bin \
  --output-dir /mnt/win_data/data_mea/zjk_mea/sage_outputs \
  --fig-dir /mnt/win_data/data_mea/zjk_mea/figures
```

### Task 7: 文档和参数记录

目标：让以后换测量地点时不用重新猜参数。

涉及文件：

- Create: `docs/sage_pipeline_design.md`
- Update: `memory.md` only after user confirms stable conclusions

记录内容：

- B2B 文件；
- measurement 文件；
- delay gate；
- frame rate；
- pulse kernel source；
- validation thresholds；
- outlier gating thresholds；
- 输出文件路径。

---

## 7. 验证标准

### 必须通过的测试

- `pytest tests/test_ui_dataset.py -q`
- `pytest tests/test_b2b_calibration.py -q`
- `pytest tests/test_sage_validation.py -q`
- `pytest tests/test_sage_tracking.py -q`

### 必须人工看图确认的内容

1. B2B pulse kernel 是否合理；
2. raw candidates 是否保留足够信息；
3. pruned candidates 是否少了随机伪检；
4. validated tracks 是否平滑、连续、不过拟合；
5. outlier windows 是否和全 delay 垂直强带/能量异常吻合；
6. 不同测量文件换入后，不需要针对某一张图手动调程序。

---

## 8. 风险与开放问题

1. B2B 加 60 dB 衰减后，若 SNR 太低，估计出的 pulse kernel 可能不稳定。
2. 当前 `cali_data.bin` 是否和后续 measurement 使用完全相同带宽、序列、采样、硬件设置，需要确认。
3. 如果 measurement 和 B2B 的中心频率/带宽/序列不同，kernel 不能直接混用。
4. 单天线 delay-Doppler SAGE 无法分辨角度，因此某些 DMC/簇状散射不能强行解释成 specular MPC。
5. 完整 DMC/RiMAX 协方差建模工作量较大，可先做简化 colored residual / local noise floor，再迭代升级。
6. Track-level validation 会降低弱短寿命路径召回率，需要根据科研目标区分“物理稳定 MPC”和“瞬态散射事件”。

---

## 9. 建议的下一步

先只执行 Task 1：B2B 校准诊断。

不要马上重写全部 SAGE。先确认新 B2B 文件能不能给出稳定、可信的 effective pulse kernel。如果 B2B pulse 质量好，再把它接入 SAGE atom；如果 B2B 质量不好，继续用 fallback kernel 但明确标记 calibration unavailable。
