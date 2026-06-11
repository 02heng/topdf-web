import os
from typing import List, Tuple

SUPPORTED_EXTENSIONS = {".pdf", ".ppt", ".pptx"}


def get_file_type(file_path: str) -> str:
    """获取文件类型"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".ppt", ".pptx"):
        return "ppt"
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def is_supported_file(file_path: str) -> bool:
    """检查文件是否支持"""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def get_supported_files(directory: str) -> List[str]:
    """获取目录中所有支持的文件"""
    files = []
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath) and is_supported_file(filepath):
            files.append(filepath)
    return files


def validate_file(file_path: str) -> Tuple[bool, str]:
    """验证文件"""
    if not os.path.exists(file_path):
        return False, "文件不存在"
    if not os.path.isfile(file_path):
        return False, "路径不是文件"
    if not is_supported_file(file_path):
        return False, "不支持的文件格式"
    return True, ""


def file_key(path: str) -> str:
    """文件唯一键（用于批注分组，避免路径格式差异）"""
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))
