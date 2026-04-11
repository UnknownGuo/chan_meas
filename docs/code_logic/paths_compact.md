# src/paths.py 脱水版

## 核心逻辑 (2行)

自动推断项目根目录，管理内部数据（处理结果）和外部数据（原始测量）的分层存储。

## 数据契约

**输入** : config/local.py 中的 RAW_MEA_ROOT, RAW_CALI_ROOT（字符串）  
**输出** : 7个Path对象（PROJECT_ROOT, DATA_DIR, CALIB_B2B_DIR, CALIB_OTA_DIR, MEASURED_DIR, RAW_MEA_DIR, RAW_CALI_DIR）

## 核心变换

```python
# 自动推断项目根
PROJECT_ROOT = Path(__file__).parent.parent  # 上升两级

# 内部结构（项目内）
DATA_DIR = PROJECT_ROOT / "data"
├─ CALIB_B2B_DIR = DATA_DIR / "calibration/b2b"
├─ CALIB_OTA_DIR = DATA_DIR / "calibration/static_ota"
└─ MEASURED_DIR = DATA_DIR / "measured"

# 外部结构（用户配置的硬盘）
RAW_MEA_DIR = Path(RAW_MEA_ROOT)
RAW_CALI_DIR = Path(RAW_CALI_ROOT)
```

## 物理含义

| 变量 | 用途 |
|------|------|
| RAW_MEA_DIR | 原始.bin文件存储（GB级） |
| DATA_DIR | 处理后的CIR、校准向量存储 |
| CALIB_B2B_DIR | B2B频响校准向量 |
| MEASURED_DIR | A2A测量处理结果 |

