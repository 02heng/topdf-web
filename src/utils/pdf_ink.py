"""将 Web 预览中的手绘墨迹（笔 / 荧光笔）写入 PDF 页面。"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import fitz

from src.utils.ink_style import HIGHLIGHTER_OPACITY
from src.utils.pdf_annotation import hex_to_rgb

INK_TOOLS = frozenset({"pen", "highlighter"})


def _stroke_width_pt(stroke: Dict[str, Any], page_width: float) -> float:
    if stroke.get("width_norm") is not None:
        return max(0.8, float(stroke["width_norm"]) * page_width)
    width = float(stroke.get("width", 2) or 2)
    return max(0.8, width)


def _points_to_pdf(
    stroke: Dict[str, Any],
    page_width: float,
    page_height: float,
) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for p in stroke.get("points") or []:
        try:
            nx = float(p.get("x", 0))
            ny = float(p.get("y", 0))
        except (TypeError, ValueError):
            continue
        pts.append((nx * page_width, ny * page_height))
    return pts


def draw_ink_stroke(page: fitz.Page, stroke: Dict[str, Any]) -> None:
    tool = str(stroke.get("tool", "pen"))
    if tool not in INK_TOOLS:
        return
    pts = _points_to_pdf(stroke, page.rect.width, page.rect.height)
    if len(pts) < 2:
        return

    color = hex_to_rgb(str(stroke.get("color", "#ef4444")))
    width = _stroke_width_pt(stroke, page.rect.width)
    is_hi = tool == "highlighter"
    opacity = HIGHLIGHTER_OPACITY if is_hi else 1.0

    shape = page.new_shape()
    shape.draw_polyline(pts)
    shape.finish(
        color=color,
        width=width,
        lineCap=1,
        lineJoin=1,
        stroke_opacity=opacity,
    )
    shape.commit()


def draw_page_ink(page: fitz.Page, strokes: List[Dict[str, Any]]) -> None:
    if not strokes:
        return
    for stroke in strokes:
        if isinstance(stroke, dict):
            draw_ink_stroke(page, stroke)


def draw_document_ink(doc: fitz.Document, ink_by_page: Dict[int, List[Dict[str, Any]]]) -> None:
    for page_num, strokes in ink_by_page.items():
        if not strokes or page_num < 0 or page_num >= doc.page_count:
            continue
        draw_page_ink(doc[page_num], strokes)
