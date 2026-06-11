"""打包版启动前的运行时修复（须在其它业务模块导入前执行）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare_frozen_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for sub in ("", "pymupdf"):
            dll_dir = os.path.join(base, sub) if sub else base
            if os.path.isdir(dll_dir):
                try:
                    os.add_dll_directory(dll_dir)
                except OSError:
                    pass

    # 尽早验证 PyMuPDF 可导入，避免 UI 渲染阶段才静默失败
    try:
        import fitz  # noqa: F401
    except Exception as exc:
        try:
            log_dir = Path(os.environ.get("APPDATA", Path.home())) / "TOPDFAnnotator" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "runtime.log", "a", encoding="utf-8") as f:
                f.write(f"\n[prepare_frozen_runtime] fitz import failed: {exc}\n")
        except Exception:
            pass
