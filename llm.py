#!/usr/bin/env python3
"""向后兼容垫片 — 转发到 llm_cli.cli.cli()。"""
import sys
from pathlib import Path

# 确保 src 布局在未 pip install 时也能工作
_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from llm_cli.cli import cli

if __name__ == "__main__":
    cli()
