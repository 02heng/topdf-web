"""无状态 Web API 处理逻辑 — 从请求体读取 PDF/设置，不依赖本地文件系统会话。"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保 src 包可导入
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from src.models.annotation_marker import (  # noqa: E402
    AnnotationMarker,
    marker_to_dict,
    serialize_annotations_for_web,
)
from src.models.config import Settings  # noqa: E402


def _dict_to_marker(data: Dict[str, Any]) -> AnnotationMarker:
    return AnnotationMarker(
        x=int(data.get("x", 0)),
        y=int(data.get("y", 0)),
        text=str(data.get("text", "")),
        color=str(data.get("color", "#7C3AED")),
        display_mode=str(data.get("display_mode", "marker")),
        original_text=str(data.get("original_text", "")),
        placement=str(data.get("placement", "right")),
        box_width=int(data.get("box_width", 0)),
        box_height=int(data.get("box_height", 0)),
        source_x=data.get("source_x"),
        source_y=data.get("source_y"),
        font_size=int(data.get("font_size", 12)),
        font_family=str(data.get("font_family", "")),
        text_orientation=str(data.get("text_orientation", "horizontal")),
        style_kind=str(data.get("style_kind", "inline")),
    )


class TempPdfApp:
    """最小 HeadlessApp 替身，供 inline_translation / annotation 服务使用。"""

    def __init__(self, pdf_doc: fitz.Document, source_name: str = "", settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.pdf_doc = pdf_doc
        self.total_pages = len(pdf_doc)
        self.current_page = 0
        self.annotations: Dict[int, list] = {}
        self.text_positions: Dict[int, list] = {}
        self.ocr_text_positions: Dict[int, List[dict]] = {}
        self.ocr_text_sources: Dict[int, str] = {}
        self.ppt_slide_emu = (9144000, 6858000)
        self._source_name = source_name


def _merge_env_api_keys(settings: Settings) -> Settings:
    data = settings.model_dump()
    llm = data.setdefault("llm", {})
    for provider in ("openai", "deepseek", "xiaomi", "agnes"):
        env_key = os.environ.get(f"TOPDF_{provider.upper()}_API_KEY", "")
        if env_key and provider in llm:
            card = llm[provider]
            if not card.get("api_key"):
                card["api_key"] = env_key
    return Settings(**data)


def _decode_pdf(pdf_base64: str) -> bytes:
    try:
        return base64.b64decode(pdf_base64)
    except Exception as exc:
        raise ValueError("无效的 PDF 数据") from exc


def _read_upload_bytes(upload) -> bytes:
    """从 cgi.FieldStorage 或其它上传对象读取二进制内容。"""
    data = b""
    if hasattr(upload, "file") and upload.file is not None:
        chunk = upload.file.read()
        if isinstance(chunk, str):
            data = chunk.encode("latin-1")
        elif chunk:
            data = chunk
    if not data and hasattr(upload, "value") and upload.value is not None:
        val = upload.value
        if isinstance(val, bytes):
            data = val
        elif isinstance(val, str):
            data = val.encode("latin-1")
    return data


def process_upload(files) -> Dict[str, Any]:
    results = []
    for upload in files:
        name = upload.filename or "document.pdf"
        raw = _read_upload_bytes(upload)
        if not raw:
            continue

        pdf_bytes = raw
        lower = name.lower()

        if lower.endswith((".ppt", ".pptx")):
            from src.utils.ppt_converter import convert_ppt_to_pdf

            suffix = ".pptx" if lower.endswith(".pptx") else ".ppt"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            try:
                pdf_path = convert_ppt_to_pdf(tmp_path)
                if not pdf_path or not os.path.isfile(pdf_path):
                    raise ValueError(f"PPT 转换失败: {name}")
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        elif not lower.endswith(".pdf"):
            raise ValueError(f"不支持的文件类型: {name}")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        doc.close()

        file_id = f"f_{uuid.uuid4().hex[:12]}"
        results.append({
            "id": file_id,
            "name": name,
            "mime": "application/pdf",
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "total_pages": total_pages,
        })

    if not results:
        raise ValueError("没有有效文件")
    return {"ok": True, "files": results}


def process_annotate_page(body: Dict[str, Any]) -> Dict[str, Any]:
    pdf_b64 = body.get("pdf_base64", "")
    page_num = int(body.get("page", 0))
    settings_raw = body.get("settings") or {}
    source_name = body.get("source_name", "")

    settings = _merge_env_api_keys(Settings(**settings_raw))
    pdf_bytes = _decode_pdf(pdf_b64)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_num < 0 or page_num >= len(doc):
            raise ValueError(f"页码越界: {page_num}")

        app = TempPdfApp(doc, source_name, settings)
        uses_inline = settings.annotation.mode == "overlay"

        if uses_inline:
            from src.services.inline_translation_service import generate_inline_markers_for_page

            markers = generate_inline_markers_for_page(app, page_num, settings.llm)
            app.annotations.setdefault(page_num, []).extend(markers or [])
            count = len(markers or [])
        else:
            from src.models.page import Page
            from src.services.annotation_service import AnnotationService

            service = AnnotationService(settings.llm)
            page_obj = Page(page_number=page_num + 1)
            annotations = service.process_page(
                page_obj,
                pdf_path="",
                pdf_doc=doc,
                source_path=source_name,
                total_pages=len(doc),
            )
            count = _apply_sidebar_annotations(app, page_num, annotations)

        ann_pages = serialize_annotations_for_web(app.annotations)
        return {
            "ok": True,
            "message": f"第 {page_num + 1} 页批注完成，共 {count} 条",
            "count": count,
            "annotations": ann_pages,
        }
    finally:
        doc.close()


def _apply_sidebar_annotations(app: TempPdfApp, page_num: int, annotations: list) -> int:
    from src.models.annotation_marker import AnnotationMarker

    if not annotations:
        return 0
    if page_num not in app.annotations:
        app.annotations[page_num] = []
    count = 0
    for ann in annotations:
        marker = AnnotationMarker(
            x=int(getattr(ann, "position_x", 50)),
            y=int(getattr(ann, "position_y", 50 + count * 30)),
            text=getattr(ann, "content", ""),
            color="#7C3AED",
            display_mode="marker",
            original_text=getattr(ann, "original_text", "") or "",
        )
        app.annotations[page_num].append(marker)
        count += 1
    return count


def process_export(body: Dict[str, Any]) -> bytes:
    from src.utils.pdf_annotation import draw_page_annotations
    from src.utils.pdf_ink import draw_page_ink
    from src.utils.preview_ink_store import normalize_ink_pages

    pdf_b64 = body.get("pdf_base64", "")
    annotations_raw = body.get("annotations") or {}
    ink_raw = body.get("ink_pages") or {}

    pdf_bytes = _decode_pdf(pdf_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    ink_pages = normalize_ink_pages(ink_raw)
    annotations: Dict[int, list] = {}
    for page_key, items in annotations_raw.items():
        annotations[int(page_key)] = items

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            strokes = ink_pages.get(page_num, [])
            if strokes:
                draw_page_ink(page, strokes)
            markers = annotations.get(page_num, [])
            if markers:
                marker_objs = []
                for m in markers:
                    if hasattr(m, "x"):
                        marker_objs.append(m)
                    else:
                        marker_objs.append(_dict_to_marker(m))
                draw_page_annotations(page, marker_objs)

        out = doc.tobytes()
        return out
    finally:
        doc.close()


def health() -> Dict[str, Any]:
    return {"ok": True, "backend": "web", "api_version": 2}
