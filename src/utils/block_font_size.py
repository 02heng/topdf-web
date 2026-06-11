"""根据原文档文本块推断批注字号（PDF 点 / pt）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

MIN_FONT_PT = 8
MAX_FONT_PT = 32
DEFAULT_FONT_PT = 12
# 批注内容侧栏编辑区显示字号
UI_ANNOTATION_FONT_PT = 12
# 原位翻译等自动生成的画布译文字号
GENERATED_INLINE_FONT_PT = 10


def clamp_font_size_pt(size: float, *, fallback: int = DEFAULT_FONT_PT) -> int:
    try:
        v = int(round(float(size)))
    except (TypeError, ValueError):
        return max(MIN_FONT_PT, min(MAX_FONT_PT, fallback))
    if v <= 0:
        return max(MIN_FONT_PT, min(MAX_FONT_PT, fallback))
    return max(MIN_FONT_PT, min(MAX_FONT_PT, v))


def font_size_from_line_height(height_pt: float) -> int:
    """文本行/形状框高度（pt）→ 近似字号。"""
    if height_pt < 6:
        return DEFAULT_FONT_PT
    return clamp_font_size_pt(height_pt * 0.76)


def font_size_from_fitz_spans(spans: List[dict]) -> Optional[int]:
    sizes: List[float] = []
    for s in spans:
        try:
            sz = float(s.get("size", 0) or 0)
        except (TypeError, ValueError):
            continue
        if sz >= 4:
            sizes.append(sz)
    if not sizes:
        return None
    return clamp_font_size_pt(max(sizes))


def font_size_from_pptx_shape(shape) -> Optional[int]:
    try:
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    if run.font and run.font.size:
                        return clamp_font_size_pt(run.font.size.pt)
    except Exception:
        pass
    return None


def infer_font_size_pt(block: Dict[str, Any], *, fallback: int = DEFAULT_FONT_PT) -> int:
    if block.get("font_size") is not None:
        return clamp_font_size_pt(block["font_size"], fallback=fallback)
    h = float(block.get("height", 0) or 0)
    if h >= 6:
        return font_size_from_line_height(h)
    return clamp_font_size_pt(fallback)
