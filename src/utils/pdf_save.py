"""安全保存 PyMuPDF 文档（覆盖原文件时处理 incremental 限制）。"""
from __future__ import annotations

import os
import tempfile

import fitz


def save_fitz_document(
    doc: fitz.Document,
    out_path: str,
    *,
    opened_from: str | None = None,
) -> None:
    """
    保存 PDF。若输出路径与打开路径相同，优先增量保存；否则先写入临时文件再替换。
    调用后 document 已关闭。
    """
    out_abs = os.path.normpath(os.path.abspath(out_path))
    opened = opened_from or getattr(doc, "name", None) or out_path
    opened_abs = os.path.normpath(os.path.abspath(opened))

    try:
        if out_abs != opened_abs:
            doc.save(out_abs, garbage=4, deflate=True)
            return

        if doc.can_save_incrementally():
            try:
                doc.saveIncr()
                return
            except Exception:
                pass

        directory = os.path.dirname(out_abs) or os.getcwd()
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix=".topdf_", dir=directory)
        os.close(fd)
        try:
            doc.save(tmp_path, garbage=4, deflate=True)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        doc.close()
        doc = None  # type: ignore[assignment]
        os.replace(tmp_path, out_abs)
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
