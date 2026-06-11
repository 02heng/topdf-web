"""从页面 PNG base64 做视觉识别（非 PDF 文本层解析）"""
from __future__ import annotations

import base64
import io
import os
import tempfile


def ocr_image_b64(image_b64: str) -> str:
    """对 base64 页面图片做 OCR，返回图片上可见文字"""
    if not image_b64:
        return ""

    try:
        from PIL import Image

        image_bytes = base64.b64decode(image_b64)
        image = Image.open(io.BytesIO(image_bytes))

        try:
            import pytesseract

            text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
            if text:
                return text
        except ImportError:
            pass

        try:
            from liteparse import LiteParse

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            try:
                parser = LiteParse(ocr_enabled=True)
                result = parser.parse(tmp_path)
                texts: list[str] = []
                for page_data in result.pages:
                    if hasattr(page_data, "text_items") and page_data.text_items:
                        for item in page_data.text_items:
                            if hasattr(item, "text") and item.text.strip():
                                texts.append(item.text.strip())
                joined = "\n".join(texts).strip()
                if joined:
                    return joined
            finally:
                os.unlink(tmp_path)
        except Exception:
            pass

        # 无 OCR 引擎时：尝试 pymupdf 从 PNG 字节解析（部分 PDF 渲染图可提取）
        try:
            import fitz

            doc = fitz.open(stream=image_bytes, filetype="png")
            if len(doc) > 0:
                text = (doc[0].get_text() or "").strip()
                doc.close()
                if text:
                    return text
        except Exception:
            pass
    except Exception:
        pass

    return ""
