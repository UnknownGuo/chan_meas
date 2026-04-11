"""
运行此脚本更新 README.md 中的目录树。
用法：python scripts/update_tree.py
"""
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent
README_PATH  = PROJECT_ROOT / "README.md"

IGNORE = {".git", "__pycache__", ".ipynb_checkpoints", ".obsidian", "*.pyc"}

def build_tree(path: Path, prefix: str = "", ignore_names: set = IGNORE) -> list[str]:
    entries = sorted(
        [e for e in path.iterdir() if e.name not in ignore_names],
        key=lambda e: (e.is_file(), e.name)
    )
    lines = []
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            lines.extend(build_tree(entry, prefix + extension, ignore_names))
    return lines

tree_lines = ["```", "chan_meas/"] + build_tree(PROJECT_ROOT) + ["```"]
tree_str = "\n".join(tree_lines)

readme = README_PATH.read_text(encoding="utf-8")
start_tag = "<!-- TREE_START -->"
end_tag   = "<!-- TREE_END -->"

if start_tag in readme and end_tag in readme:
    before = readme[:readme.index(start_tag) + len(start_tag)]
    after  = readme[readme.index(end_tag):]
    new_readme = before + "\n" + tree_str + "\n" + after
    README_PATH.write_text(new_readme, encoding="utf-8")
    print("README.md 目录树已更新。")
else:
    print("未找到 <!-- TREE_START --> 标签，请在 README.md 中添加后再运行。")
