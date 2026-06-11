"""TO PDF 后端入口 — 供开发模式与 PyInstaller 调用。"""
from __future__ import annotations

from src.run_electron_server import main

if __name__ == "__main__":
    main()
