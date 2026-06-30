from pathlib import Path

# 程序根目录（打包后为 _internal，源码运行为项目根）。
_BUNDLE_ROOT = Path(__file__).resolve().parents[1]

# 原始 / 校准数据目录：默认指向程序旁的 raw_bins，可改为你的本地路径。
RAW_MEA_ROOT = str((_BUNDLE_ROOT / "raw_bins").resolve())
RAW_CALI_ROOT = str((_BUNDLE_ROOT / "raw_bins").resolve())

# 可选的附加数据集（默认无）。
EXTRA_RAW_ROOT = None
EXTRA_SAGE_OUTPUTS_ROOT = None
