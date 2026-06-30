from pathlib import Path

try:
    from config.local import RAW_MEA_ROOT, RAW_CALI_ROOT
except ImportError:
    raise ImportError("找不到 config/local.py，请复制 config/local.example.py 并填入本机路径")

try:
    from config.local import EXTRA_RAW_ROOT, EXTRA_SAGE_OUTPUTS_ROOT
except ImportError:
    EXTRA_RAW_ROOT = None
    EXTRA_SAGE_OUTPUTS_ROOT = None

# 项目根目录（自动推断，换机器不用改）
PROJECT_ROOT = Path(__file__).parent.parent

# ── 处理后的数据（项目内）──────────────────────────
DATA_DIR          = PROJECT_ROOT / "data"
CALIB_B2B_DIR     = DATA_DIR / "calibration" / "b2b"
CALIB_B2B_HF_DIR  = CALIB_B2B_DIR / "h_f"   # B2B H(f) 向量 (.npy, complex128, shape=(U,))
CALIB_OTA_DIR     = DATA_DIR / "calibration" / "static_ota"
MEASURED_DIR      = DATA_DIR / "measured"

# ── 原始数据（外部大硬盘）─────────────────────────
RAW_MEA_DIR     = Path(RAW_MEA_ROOT)
RAW_CALI_DIR    = Path(RAW_CALI_ROOT)

# ── 附加测量数据集（可选） ──────────────────
EXTRA_RAW_DIR          = Path(EXTRA_RAW_ROOT) if EXTRA_RAW_ROOT else None
EXTRA_SAGE_OUTPUTS_DIR = Path(EXTRA_SAGE_OUTPUTS_ROOT) if EXTRA_SAGE_OUTPUTS_ROOT else None
