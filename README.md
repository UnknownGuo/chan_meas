# chan_meas — 无线信道测量处理项目

无线信道测量数据处理工程，覆盖 B2B校准 → 静态OTA校准 → V2V动态数据处理全流程。

## 快速开始

```bash
# 1. 复制路径配置模板
cp config/local.example.py config/local.py
# 2. 编辑 local.py，填入本机实际路径
# 3. 安装依赖（待补充）
```

## 目录结构

<!-- TREE_START -->
```
chan_meas/
├── config
│   ├── local.example.py
│   └── local.py
├── data
│   ├── calibration
│   │   ├── b2b
│   │   └── static_ota
│   └── measured
├── docs
│   ├── specs
│   │   ├── reference
│   │   │   └── 20260402_gemini.md
│   │   └── 2026-04-02-data-management-design.md
│   ├── checklist.md
│   ├── data_log.md
│   └── hardware.md
├── legacy_reference
├── notebooks
├── scripts
│   └── update_tree.py
├── src
│   ├── calibration
│   │   └── __init__.py
│   ├── io
│   │   └── __init__.py
│   ├── pipeline
│   │   └── __init__.py
│   ├── signal
│   │   └── __init__.py
│   ├── __init__.py
│   └── paths.py
├── .gitignore
├── CLAUDE.md
└── README.md
```
<!-- TREE_END -->

## 数据流

```
原始 .bin（大硬盘）
    │
    ├── B2B校准       → data/calibration/b2b/
    ├── 静态OTA校准   → data/calibration/static_ota/
    └── V2V动态测量   → data/measured/
```

## 模块说明

| 模块 | 路径 | 职责 |
|------|------|------|
| IO | `src/io/` | 读取 `.bin` 文件，输出标准张量 |
| Signal | `src/signal/` | FFT、CIR提取等算子 |
| Calibration | `src/calibration/` | B2B校准矩阵生成、CFO估计 |
| Pipeline | `src/pipeline/` | 串联各模块的处理流水线 |

## 文件命名规范

**测量数据：** `YYYYMMDD_Location_FreqBand_Scene_State_SeqN.mat`
```
示例：20260402_Lab405_28GHz_NLOS_Move30kmh_001.mat
```

**B2B校准：** `Calib_VN_YYYYMMDD_B2B_Device_Cable_AttNdB.mat`
```
示例：Calib_V1_20260402_B2B_Dev01_RG316_30dB.mat
```

**静态OTA校准：** `Calib_VN_YYYYMMDD_OTA_Device_Location_FreqBand.mat`
```
示例：Calib_V1_20260402_OTA_Dev01_Lab405_28GHz.mat
```

## 相关文档

- [设计文档](docs/specs/2026-04-02-data-management-design.md)
- [问题记录](docs/checklist.md)
- [硬件配置](docs/hardware.md)
- [测量日志](docs/data_log.md)
