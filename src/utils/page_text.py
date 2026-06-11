"""页面可读文本（OCR + PDF 文本层）"""

from __future__ import annotations

from src.utils.image_ocr import ocr_image_b64
from src.utils.page_image import PageImageData, extract_page_text_for_annotation


def get_page_readable_text(page: PageImageData) -> str:
    """供多智能体 / 文档理解使用的本页文字"""
    ocr_text = ocr_image_b64(page.image_b64)
    if ocr_text:
        return ocr_text.strip()
    if page.text_supplement:
        return page.text_supplement.strip()
    return ""
