from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.module_b import export_module_b_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Module B results from a UI dataset JSON")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to *_b2b_adaptive_sage.json")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory to store JSON/CSV/PNG outputs")
    args = parser.parse_args(argv)

    artifacts = export_module_b_results(args.dataset, args.out_dir)
    print(json.dumps({
        "json": str(artifacts.json_path),
        "csv": [str(p) for p in artifacts.csv_paths],
        "png": [str(p) for p in artifacts.png_paths],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
