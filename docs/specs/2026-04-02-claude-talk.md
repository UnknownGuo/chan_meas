# Data Management Framework Design
**Date:** 2026-04-02  
**Project:** chan_meas  
**Status:** Approved

---

## 1. 目标

为无线信道测量科研项目建立一套简洁、多机可用、模块间无冲突的数据管理框架。

**范围：** 目录结构 + 路径管理 + 文件命名规范  
**不包含：** 信号处理算法、校准算法、核心流水线（后续子项目）

---

## 2. 目录结构

```
/home/guo/project/chan_meas/
│
├── config/
│   ├── local.py            ← 本机路径（gitignore，不提交）
│   └── local.example.py    ← 模板（提交git）
│
├── data/                   ← 只放处理后的数据，原始.bin不进此目录
│   ├── calibration/
│   │   ├── b2b/            ← B2B校准处理结果
│   │   └── static_ota/     ← 静态OTA校准处理结果
│   └── measured/           ← V2V动态测量处理结果（CIR）
│
├── src/
│   ├── paths.py            ← 全项目路径唯一入口
│   ├── io/                 ← 读取 .bin 文件
│   ├── signal/             ← 信号处理算子（FFT、CIR提取等）
│   ├── calibration/        ← 校准逻辑（B2B、CFO估计）
│   └── pipeline/           ← 流水线（串联各模块）
│这个src可能还得分一下，一部分是测试验证想法的，一部分是实际处理的。
测试验证的可能会有很多测试，可能每天都会做测试。临时性比较强。
实际处理的可能不太会动。
├── scripts/                ← 日常运行入口（batch处理等）
├── legacy_reference/       ← 旧代码存档，永远不被import
├── docs/
│   └── specs/              ← 设计文档
└── .gitignore
```

**调用关系：**
```
scripts/ → pipeline/ → [io/ + calibration/ + signal/]
                              ↑
                          paths.py（所有路径从这里取）
```

---

## 3. 路径管理

### `config/local.example.py`
```python
# 复制此文件为 local.py，填入本机路径
RAW_DATA_ROOT = "/path/to/your/raw/data"
```

### `src/paths.py`
```python
from pathlib import Path

try:
    from config.local import RAW_DATA_ROOT
except ImportError:
    raise ImportError("找不到 config/local.py，请复制 local.example.py 并填入本机路径")

PROJECT_ROOT = Path(__file__).parent.parent

# 处理后的数据（项目内）
DATA_DIR         = PROJECT_ROOT / "data"
CALIB_B2B_DIR    = DATA_DIR / "calibration" / "b2b"
CALIB_OTA_DIR    = DATA_DIR / "calibration" / "static_ota"
MEASURED_DIR     = DATA_DIR / "measured"

# 原始数据（外部大硬盘）
RAW_ROOT         = Path(RAW_DATA_ROOT)
RAW_B2B_DIR      = RAW_ROOT / "b2b"
RAW_OTA_DIR      = RAW_ROOT / "static_ota"
RAW_MEASURED_DIR = RAW_ROOT / "measured"
```

---

## 4. 文件命名规范
Bin文件存储
/mnt/win_data/data_mea/data_save/Mea_data
### 处理后的CIR数据
```
YYYYMMDD_Location_FreqBand_Scene_State_SeqN.mat
示例：20260402_Lab405_28GHz_NLOS_Move30kmh_001.mat
```


| 字段 | 说明 | 示例 |
|------|------|------|
| YYYYMMDD | 测量日期 | 20260402 |
| Location | 测量地点 | Lab405 |
| FreqBand | 频段 | 28GHz |
| Scene | LOS / NLOS | NLOS |
| State | Static / MoveNkmh | Move30kmh |
| SeqN | 序号，3位补零 | 001 |

两个校准文件的存储：/mnt/win_data/data_mea/data_save/Cali_data
### B2B校准文件
```
Calib_VN_YYYYMMDD_B2B_Device_Cable_AttNdB.mat
示例：Calib_V1_20260402_B2B_Dev01_RG316_30dB.mat
```

### 静态OTA校准文件
```
Calib_VN_YYYYMMDD_OTA_Device_Location_FreqBand.mat
示例：Calib_V1_20260402_OTA_Dev01_Lab405_28GHz.mat
```

| 字段 | 说明 |
|------|------|
| VN | 校准版本，硬件/线缆变动时递增 |
| Device | 设备编号 |
| Cable | 线缆型号（B2B专用） |
| AttNdB | 衰减量（B2B专用） |

---

## 5. Decision Log

| 决策 | 理由 | 备选方案 | 风险 | 状态 |
|------|------|---------|------|------|
| 纯Python paths.py | 零依赖，IDE可跳转，单人开发 | YAML, .env | 低 | **锁定** |
| `__file__` 推断项目根 | 换机器不改代码 | 环境变量 | 低 | **锁定** |
| local.py gitignore | 防止路径污染git | 分支隔离 | 低 | **锁定** |
| scripts/ 与 src/ 分离 | 脚本≠库，职责清晰 | 全放src | 低 | **锁定** |
| legacy_reference/ 隔离 | 旧代码参考用，防止误import | 直接删除 | 低 | **锁定** |

---

## 6. FMEA

| 故障模式 | 可能性 | 影响 | 缓解措施 |
|---------|-------|------|---------|
| 换机器忘建local.py | 中 | 启动报错 | ImportError给出明确中文提示 |
| RAW_DATA_ROOT路径错误 | 低 | 静默加载失败 | io层读文件时检查路径存在 |
| data/子目录不存在 | 中 | 写文件报错 | pipeline第一步`mkdir(exist_ok=True)` |
| 命名不一致 | 高 | 难以检索 | local.example.py附命名规则注释 |

---

## 7. 下一步子项目

1. ✅ **A. 数据管理框架**（本文档）
2. **D. 旧代码迁移** — 逻辑审计 + 重构为三层架构
3. **C. 校准系统** — B2B + 静态OTA分层校准，解决20dB动态范围瓶颈
4. **B. 核心算法改进** — CFO补偿、相干累加、GPU加速

旧代码迁移 — 逻辑审计 + 重构为三层架构

旧代码1：
目录：/mnt/win_data/data_mea/0123mea
所有的m文件（matlab）编写

旧代码二：
/home/guo/project/research_ai/scripts/georadiomap/data
均为python编写，该项目可以参考的文件为
/home/guo/project/research_ai下面的md文件

 **校准系统** — B2B + 静态OTA分层校准，解决20dB动态范围瓶颈
 B2B的逻辑不变，但是新的B2B测量数据（bin）文件重新测量了，要根据新的bin文件按照原来的逻辑生成cali数据

静态OTA分层校准：
校准数据目前有的是平均后的校准数据，（什么是平均参考/home/guo/project/chan_meas/docs/specs/reference/20260402_gemini.md）
如何操作也参考这个文件写代码。

如果效果不好，可能考虑
## 1. 能做到的：修正“帧与帧”之间的相位关系

如果你平均后的数据（每秒或者每毫秒输出一个平均值）依然存在相位旋转，那么利用“1秒测量”得到的频偏 $\Delta f$ 是可以校准这些数据的。

- **操作逻辑：** 1. 假设从“1秒测量”的数据里算出的频偏是 $50\text{Hz}$。
    
    2. 即使你的生产数据是硬件平均后的，但“平均块 A”和“平均块 B”之间的时间差是已知的。
    
    3. 你可以用这 $50\text{Hz}$ 的参数，在 Python 里把这些“平均块”之间的相位旋转拉平。
    
- **意义：** 这样你就可以对多个“平均块”进行更长时间的相干处理（比如做多普勒分析或多帧累加），**防止动态范围进一步塌陷**。
但是现在我感觉doppler测量还是比较准确的，理论与测量都对得上。
这样是否有意义？
我该如何做一个对比实验：
该实验从理论上，以及从实际上来对比
1.有频偏vs无频偏的CIR噪底。
2.实际测量连续15帧和15帧平均对比。
这个实验要怎么做可能还要讨论一下。

另外还需要一个cheeck list记录问题。
还需要一个环节，就是每次更改都需要更新目录。
