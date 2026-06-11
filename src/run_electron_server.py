"""Electron 无 GUI 后端入口 — 供 PyInstaller 冻结为 topdf-backend.exe"""
from __future__ import annotations

import multiprocessing
import os
import sys


def _load_config_headless():
    """加载配置，跳过 GUI 依赖"""
    from pathlib import Path
    import yaml
    from src.models.config import Settings
    from src.utils.runtime import get_default_config_path, get_local_config_path

    default_path = get_default_config_path()
    local_path = get_local_config_path()

    config_data = {}
    if default_path.is_file():
        with open(default_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

    if local_path.is_file():
        with open(local_path, "r", encoding="utf-8") as f:
            local_data = yaml.safe_load(f) or {}
            for key, value in local_data.items():
                if key in config_data and isinstance(config_data[key], dict) and isinstance(value, dict):
                    config_data[key].update(value)
                else:
                    config_data[key] = value

    return Settings(**config_data)


def main() -> None:
    multiprocessing.freeze_support()

    from src.frozen_bootstrap import prepare_frozen_runtime

    prepare_frozen_runtime()

    if getattr(sys, "frozen", False):
        from pathlib import Path

        meipass = getattr(sys, "_MEIPASS", None)
        root = Path(meipass) if meipass else Path(sys.executable).resolve().parent
        os.chdir(root)
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    os.environ.setdefault("TOPDF_ELECTRON_MODE", "1")

    port = int(os.environ.get("TOPDF_API_PORT", "8765"))
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg == "--port" and len(sys.argv) > 2:
            try:
                port = int(sys.argv[sys.argv.index("--port") + 1])
            except (ValueError, IndexError):
                pass

    import socket
    import time

    host = "127.0.0.1"
    for attempt in range(12):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
            break
        except OSError:
            if attempt == 11:
                raise
            print(f"[topdf-backend] port {port} busy, retrying in 5s…", flush=True)
            time.sleep(5)

    settings = _load_config_headless()

    from src.services.electron_backend import run_electron_backend
    run_electron_backend(settings, port=port)


if __name__ == "__main__":
    main()
