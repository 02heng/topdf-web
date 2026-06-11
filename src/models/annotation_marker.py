"""PDF 页内批注标记（Electron 后端与工程持久化共用）。"""
from __future__ import annotations

from typing import Any, Dict, List


class AnnotationMarker:
    """批注标记数据类（无 GUI 依赖）"""

    def __init__(
        self,
        x: int,
        y: int,
        text: str,
        color: str = "#7C3AED",
        *,
        display_mode: str = "marker",
        original_text: str = "",
        placement: str = "right",
        box_width: int = 0,
        box_height: int = 0,
        source_x: int | None = None,
        source_y: int | None = None,
        text_orientation: str = "horizontal",
        font_size: int = 12,
        font_family: str = "",
        style_kind: str = "inline",
    ):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.display_mode = display_mode
        self.original_text = original_text
        self.placement = placement
        self.box_width = box_width
        self.box_height = box_height
        self.source_x = source_x
        self.source_y = source_y
        self.text_orientation = text_orientation or "horizontal"
        self.font_size = font_size
        self.font_family = font_family
        self.style_kind = style_kind


def marker_to_dict(m: AnnotationMarker) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "x": m.x,
        "y": m.y,
        "text": m.text,
        "color": m.color,
    }
    if m.display_mode != "marker":
        d["display_mode"] = m.display_mode
    if m.original_text:
        d["original_text"] = m.original_text
    if m.placement:
        d["placement"] = m.placement
    if m.box_width:
        d["box_width"] = m.box_width
    if m.box_height:
        d["box_height"] = m.box_height
    if m.source_x is not None:
        d["source_x"] = m.source_x
    if m.source_y is not None:
        d["source_y"] = m.source_y
    if m.font_size:
        d["font_size"] = m.font_size
    if m.font_family:
        d["font_family"] = m.font_family
    orient = m.text_orientation or ""
    if orient and orient != "horizontal":
        d["text_orientation"] = orient
    if m.style_kind:
        d["style_kind"] = m.style_kind
    return d


def serialize_annotations_for_web(
    annotations: Dict[int, List[AnnotationMarker]],
) -> Dict[str, list]:
    """与预览 Web 端一致：含 index，跳过空页。"""
    ann_pages: Dict[str, list] = {}
    for page_num, markers in annotations.items():
        if not markers:
            continue
        page_items = []
        for i, m in enumerate(markers):
            item = marker_to_dict(m)
            item["index"] = i + 1
            page_items.append(item)
        ann_pages[str(page_num)] = page_items
    return ann_pages
