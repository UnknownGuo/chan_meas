from pathlib import Path

try:
    from config.local import RAW_MEA_ROOT, RAW_CALI_ROOT
except ImportError:
    raise ImportError("找不到 config/local.py，请复制 config/local.example.py 并填入本机路径")

# 项目根目录（自动推断，换机器不用改）
PROJECT_ROOT = Path(__file__).parent.parent

# ── 处理后的数据（项目内）──────────────────────────
DATA_DIR        = PROJECT_ROOT / "data"
CALIB_B2B_DIR   = DATA_DIR / "calibration" / "b2b"
CALIB_OTA_DIR   = DATA_DIR / "calibration" / "static_ota"
MEASURED_DIR    = DATA_DIR / "measured"

# ── 原始数据（外部大硬盘）─────────────────────────
RAW_MEA_DIR     = Path(RAW_MEA_ROOT)
RAW_CALI_DIR    = Path(RAW_CALI_ROOT)
