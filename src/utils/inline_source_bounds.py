"""原位译文对应的原文区域（PDF 点坐标）。"""
from __future__ import annotations

from typing import Any, Tuple


def source_bounds_for_marker(marker: Any) -> Tuple[float, float, float, float]:
    """返回 (source_x, source_y, width, height)，单位 PDF 点。"""
    w = float(getattr(marker, "box_width", 0) or 0)
    h = float(getattr(marker, "box_height", 0) or 0)
    sx = getattr(marker, "source_x", None)
    sy = getattr(marker, "source_y", None)
    if sx is not None and sy is not None and w > 0 and h > 0:
        return float(sx), float(sy), w, h
    return infer_source_bounds(
        float(marker.x),
        float(marker.y),
        w,
        h,
        getattr(marker, "placement", "right") or "right",
    )


def infer_source_bounds(
    anchor_x: float,
    anchor_y: float,
    width: float,
    height: float,
    placement: str,
) -> Tuple[float, float, float, float]:
    """由译文锚点反推原文框（与 inline_translation_service._anchor_xy 对应）。"""
    w = max(width, 8.0)
    h = max(height, 8.0)
    mid_y = h * 0.42
    if placement == "right":
        return max(0.0, anchor_x - w - 8), max(0.0, anchor_y - mid_y), w, h
    if placement == "below":
        return anchor_x, max(0.0, anchor_y - h - 4), w, h
    if placement == "above":
        return anchor_x - w * 0.02, max(0.0, anchor_y - h), w, h
    return max(0.0, anchor_x - w - 8), max(0.0, anchor_y - mid_y), w, h
