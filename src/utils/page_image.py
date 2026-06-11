"""PDF / PPT 页面转图片工具"""
import base64
import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import fitz


@dataclass
class PageImageData:
    page_number: int
    png_bytes: bytes
    image_b64: str
    width: float
    height: float
    text_supplement: str = ""


def render_page_to_image(
    pdf_path: str,
    page_number: int,
    dpi: int = 150,
) -> Tuple[bytes, str, float, float]:
    """将 PDF 单页渲染为 PNG"""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number]
        page_width = page.rect.width
        page_height = page.rect.height

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        png_bytes = pix.tobytes("png")
        b64_str = base64.b64encode(png_bytes).decode("utf-8")
        return png_bytes, b64_str, page_width, page_height
    finally:
        doc.close()


def render_page_from_doc(
    pdf_doc: fitz.Document,
    page_number: int,
    dpi: int = 150,
) -> Tuple[bytes, str, float, float]:
    """从已打开的 PDF 文档渲染单页"""
    page = pdf_doc[page_number]
    page_width = page.rect.width
    page_height = page.rect.height

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    png_bytes = pix.tobytes("png")
    b64_str = base64.b64encode(png_bytes).decode("utf-8")
    return png_bytes, b64_str, page_width, page_height


def render_page_for_annotation(
    page_number: int,
    *,
    pdf_path: str = "",
    pdf_doc: Optional[fitz.Document] = None,
    source_path: str = "",
    dpi: int = 150,
) -> Tuple[bytes, str, float, float]:
    """将文档单页渲染为 PNG base64（PDF 与 PPTX 统一入口）"""
    original = source_path or pdf_path
    lower = original.lower()

    if lower.endswith(".pptx") and os.path.isfile(original):
        from src.utils.pptx_renderer import render_pptx_slide_to_image

        return render_pptx_slide_to_image(original, page_number)

    if pdf_doc is not None:
        return render_page_from_doc(pdf_doc, page_number, dpi=dpi)
    if pdf_path:
        return render_page_to_image(pdf_path, page_number, dpi=dpi)

    raise ValueError("无法渲染页面：缺少有效的 PDF 或 PPTX 路径")


def render_all_pages_for_annotation(
    total_pages: int,
    *,
    pdf_path: str = "",
    pdf_doc: Optional[fitz.Document] = None,
    source_path: str = "",
    dpi: int = 150,
    on_progress: Optional[Callable[[int, int], None]] = None,
    start_page: int = 0,
    end_page: Optional[int] = None,
) -> List[PageImageData]:
    """将文档页面渲染为 PNG base64；可选 start_page/end_page（0-based，含端点）"""
    last = total_pages - 1 if end_page is None else min(end_page, total_pages - 1)
    first = max(0, start_page)
    if first > last:
        return []

    job_total = last - first + 1
    pages: List[PageImageData] = []
    for page_num in range(first, last + 1):
        png_bytes, image_b64, width, height = render_page_for_annotation(
            page_num,
            pdf_path=pdf_path,
            pdf_doc=pdf_doc,
            source_path=source_path,
            dpi=dpi,
        )
        supplement = extract_page_text_for_annotation(
            page_num,
            pdf_doc=pdf_doc,
            source_path=source_path,
        )
        pages.append(
            PageImageData(
                page_number=page_num,
                png_bytes=png_bytes,
                image_b64=image_b64,
                width=width,
                height=height,
                text_supplement=supplement.strip(),
            )
        )
        if on_progress:
            on_progress(page_num - first + 1, job_total)
    return pages


def extract_page_text_for_annotation(
    page_number: int,
    *,
    pdf_doc: Optional[fitz.Document] = None,
    source_path: str = "",
) -> str:
    """提取页面文字（仅用于 UI 展示等非视觉批注场景）"""
    if source_path.lower().endswith(".pptx") and os.path.isfile(source_path):
        from src.utils.pptx_renderer import extract_pptx_slide_text

        return extract_pptx_slide_text(source_path, page_number)

    if pdf_doc is not None and 0 <= page_number < len(pdf_doc):
        text = (pdf_doc[page_number].get_text() or "").strip()
        if len(text) >= 80:
            return text
        try:
            _png, b64, _w, _h = render_page_from_doc(pdf_doc, page_number, dpi=150)
            from src.utils.image_ocr import ocr_image_b64

            ocr = (ocr_image_b64(b64) or "").strip()
            if ocr:
                return ocr
        except Exception:
            pass
        return text

    return ""
