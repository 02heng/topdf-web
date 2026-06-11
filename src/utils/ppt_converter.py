"""PPT/PPTX 转 PDF，供预览与批注使用"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.services.project_service import get_user_data_dir

PPT_CACHE_VERSION = "v2"


def _cache_path(source: str) -> Path:
    stat = os.stat(source)
    key = f"{os.path.abspath(source)}:{stat.st_mtime}:{stat.st_size}:{PPT_CACHE_VERSION}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    name = Path(source).stem[:40]
    cache_dir = get_user_data_dir() / "ppt_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{name}_{digest}.pdf"


def _find_soffice() -> str | None:
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None
    for cmd in ("libreoffice", "soffice"):
        if shutil.which(cmd):
            return cmd
    return None


def _convert_with_libreoffice(source: str, output_pdf: str) -> bool:
    soffice = _find_soffice()
    if not soffice:
        return False

    out_dir = os.path.dirname(output_pdf)
    os.makedirs(out_dir, exist_ok=True)

    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, source],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False

    generated = os.path.join(out_dir, Path(source).stem + ".pdf")
    if os.path.isfile(generated):
        if os.path.abspath(generated) != os.path.abspath(output_pdf):
            shutil.move(generated, output_pdf)
        return True
    return os.path.isfile(output_pdf)


def _convert_with_powerpoint(source: str, output_pdf: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False

    app = None
    presentation = None
    try:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = 0
        presentation = app.Presentations.Open(
            os.path.abspath(source),
            ReadOnly=True,
            Untitled=False,
            WithWindow=False,
        )
        presentation.SaveAs(os.path.abspath(output_pdf), 32)
        return os.path.isfile(output_pdf)
    except Exception:
        return False
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass


def _convert_with_builtin(source: str, output_pdf: str) -> bool:
    """使用内置渲染（仅 .pptx，无需 Office）"""
    if not source.lower().endswith(".pptx"):
        return False
    try:
        from src.utils.pptx_renderer import render_pptx_to_pdf

        render_pptx_to_pdf(source, output_pdf)
        return os.path.isfile(output_pdf)
    except Exception:
        return False


def convert_ppt_to_pdf(source: str) -> str:
    """将 PPT/PPTX 转为 PDF（带缓存），返回 PDF 路径"""
    source = os.path.abspath(source)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"文件不存在: {source}")

    ext = Path(source).suffix.lower()
    if ext not in (".ppt", ".pptx"):
        raise ValueError(f"不支持的格式: {ext}")

    cache = _cache_path(source)
    if cache.is_file():
        try:
            if cache.stat().st_mtime >= os.path.getmtime(source):
                return str(cache)
        except OSError:
            pass

    if cache.is_file():
        cache.unlink(missing_ok=True)

    if _convert_with_powerpoint(source, str(cache)):
        return str(cache)
    if _convert_with_libreoffice(source, str(cache)):
        return str(cache)
    if _convert_with_builtin(source, str(cache)):
        return str(cache)

    if ext == ".ppt":
        raise RuntimeError(
            "旧版 .ppt 需要安装 LibreOffice 或 PowerPoint。"
            "建议在 PowerPoint 中另存为 .pptx 后再导入。"
        )
    raise RuntimeError(
        "无法解析此 PPT。若安装了 LibreOffice，转换效果会更接近原版。"
    )


def get_render_pdf_path(file_path: str, converted_map: dict[str, str]) -> str:
    """获取用于预览/导出的 PDF 路径"""
    if not file_path:
        return ""
    lower = file_path.lower()
    if lower.endswith((".ppt", ".pptx")):
        from src.utils.file_utils import file_key

        return converted_map.get(file_key(file_path)) or converted_map.get(file_path, file_path)
    return file_path
