"""开发环境与 PyInstaller 打包后的路径解析"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_project_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def get_resource_path(*parts: str) -> Path:
    return get_project_root().joinpath(*parts)


def get_user_config_dir() -> Path:
    """可写配置目录（安装版写入用户数据目录）"""
    if is_frozen():
        from src.services.project_service import get_user_data_dir

        return get_user_data_dir()
    return get_resource_path("config")


def get_default_config_path() -> Path:
    return get_resource_path("config", "default.yaml")


def get_local_config_path() -> Path:
    return get_user_config_dir() / "local.yaml"


def get_web_dir() -> Path:
    if is_frozen():
        return get_resource_path("web")
    return get_resource_path("src", "web")
