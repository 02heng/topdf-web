"""运行期错误日志：打包后无控制台时仍可定位渲染/加载失败。"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def get_log_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "TOPDFAnnotator" / "logs"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "TOPDFAnnotator"
    else:
        base = Path.home() / ".local" / "share" / "TOPDFAnnotator" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_runtime_error(context: str, exc: BaseException | None = None) -> None:
    """把运行期错误追加写入 runtime.log，不影响主流程。"""
    try:
        log_path = get_log_dir() / "runtime.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {context}\n")
            f.write(f"  frozen={getattr(sys, 'frozen', False)} platform={sys.platform}\n")
            if exc is not None:
                f.write(traceback.format_exc())
    except Exception:
        pass
