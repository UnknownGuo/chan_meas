# 项目说明（Claude 专用）

## 项目背景
无线信道测量处理项目。博士科研，研究方向：V2V（车对车）信道特性，频段约28GHz。
单人开发，全Python，GPU加速（RTX 3060）。

## 当前阶段
- [x] 数据管理框架建立
- [ ] 旧代码迁移（MATLAB + Python → 统一Python）
- [ ] 校准系统（B2B + 静态OTA）
- [ ] 核心算法改进（CFO补偿、相干累加）

## 关键路径

| 变量 | 路径 | 说明 |
|------|------|------|
| `RAW_MEA_DIR` | `/mnt/win_data/data_mea/data_save/Mea_data` | 原始测量.bin |
| `RAW_CALI_DIR` | `/mnt/win_data/data_mea/data_save/Cali_data` | 原始校准.bin |
| 旧MATLAB代码 | `/mnt/win_data/data_mea/0123mea` | 参考用，不迁移整体 |
| 旧Python代码 | `/home/guo/project/research_ai/scripts/georadiomap/data` | 参考用 |

## 架构原则
- 所有路径只从 `src/paths.py` 取，不在其他文件硬编码
- `src/` 是稳定库代码，`notebooks/` 是探索验证
- `legacy_reference/` 只读参考，永远不被 import
- 三层架构：算子层（`src/signal/`）→ 逻辑模块层（`src/calibration/`）→ 流水线层（`src/pipeline/`）

## 数据说明
三组数据：
1. **B2B**：背靠背，线缆直连，用于提取硬件系统响应
2. **静态OTA**：静止环境空口测量，用于估计硬件CFO（载波频偏）
3. **V2V动态**：车对车实测，目标数据，动态范围目前约20dB

已知问题：硬件对每15个序列做了平均后再输出，导致动态范围受限。

## 校准逻辑（重要）
- B2B校准：旧逻辑不变，用新.bin文件重新生成校准矩阵
- 静态OTA：利用平均后的数据估计CFO，用于帧间相位对齐
- 参考文档：`docs/specs/reference/20260402_gemini.md`（Gemini对话记录，含详细原理）

## 代码风格
- 变量名用物理意义命名（如 `snr_db`、`cir_tensor`、`cfo_hz`）
- 函数输入输出加 Type Hint
- 核心算子用 PyTorch 实现（支持GPU），避免 numpy for-loop
