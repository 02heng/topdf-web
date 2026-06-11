"""生成原位译文后，按 PDF 文本行坐标拆批注并贴到对应原文行右侧。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from src.utils.block_font_size import GENERATED_INLINE_FONT_PT
from src.utils.inline_source_bounds import source_bounds_for_marker

_LINE_SPLIT_RE = re.compile(r"[\n\r]+|[；;]\s*")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _text_matches(a: str, b: str) -> bool:
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    n = min(len(na), len(nb), 28)
    return n >= 8 and na[:n] == nb[:n]


def _split_translation_lines(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    lines = [ln.strip() for ln in _LINE_SPLIT_RE.split(raw) if ln.strip()]
    if len(lines) >= 2:
        return lines
    return [raw]


def _block_rect(b: Dict[str, Any]) -> Tuple[float, float, float, float]:
    x = float(b["x"])
    y = float(b["y"])
    w = max(float(b.get("width", 0) or 0), 1.0)
    h = max(float(b.get("height", 0) or 0), 1.0)
    return x, y, x + w, y + h


def _rects_overlap(
    ax0: float, ay0: float, ax1: float, ay1: float,
    bx0: float, by0: float, bx1: float, by1: float,
    pad: float = 6.0,
) -> bool:
    return not (
        ax1 + pad < bx0
        or bx1 + pad < ax0
        or ay1 + pad < by0
        or by1 + pad < ay0
    )


def _lines_in_source_region(
    page_lines: List[Dict[str, Any]],
    sx: float,
    sy: float,
    sw: float,
    sh: float,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for b in page_lines:
        bx0, by0, bx1, by1 = _block_rect(b)
        if _rects_overlap(sx, sy, sx + sw, sy + sh, bx0, by0, bx1, by1, pad=8):
            hits.append(b)
    hits.sort(key=lambda x: (float(x["y"]), float(x["x"])))
    return hits


def _lines_left_of_anchor(
    page_lines: List[Dict[str, Any]],
    anchor_x: float,
    anchor_y: float,
    band_h: float,
) -> List[Dict[str, Any]]:
    band_h = max(band_h, 40.0)
    y0 = anchor_y - band_h * 0.55
    y1 = anchor_y + band_h * 0.45
    hits: List[Dict[str, Any]] = []
    for b in page_lines:
        bx0, by0, bx1, by1 = _block_rect(b)
        cy = (by0 + by1) * 0.5
        if bx1 > anchor_x + 24:
            continue
        if cy < y0 or cy > y1:
            continue
        if len((b.get("text") or "").strip()) < 2:
            continue
        hits.append(b)
    if len(hits) < 2:
        hits = [
            b
            for b in page_lines
            if _block_rect(b)[2] <= anchor_x + 24
            and abs((_block_rect(b)[1] + _block_rect(b)[3]) * 0.5 - anchor_y) <= band_h
            and len((b.get("text") or "").strip()) >= 2
        ]
    hits.sort(key=lambda x: (float(x["y"]), float(x["x"])))
    return hits


def _pick_source_lines_for_marker(
    marker: Any,
    region_lines: List[Dict[str, Any]],
    page_lines: List[Dict[str, Any]],
    zh_count: int,
) -> List[Dict[str, Any]]:
    orig = (getattr(marker, "original_text", "") or "").strip()
    if "\n" in orig:
        parts = [p.strip() for p in orig.split("\n") if p.strip()]
        picked: List[Dict[str, Any]] = []
        used: set = set()
        for part in parts:
            for i, b in enumerate(region_lines):
                if i in used:
                    continue
                if _text_matches(part, b.get("text", "")):
                    picked.append(b)
                    used.add(i)
                    break
        if len(picked) >= 2:
            return picked

    if len(region_lines) >= zh_count >= 2:
        return region_lines[:zh_count]

    if orig and len(region_lines) >= 2:
        on = _normalize_text(orig)
        matched = [
            b
            for b in region_lines
            if _normalize_text(b.get("text", "")) in on
            or on.find(_normalize_text(b.get("text", ""))[: min(20, len(on))]) >= 0
        ]
        if len(matched) >= 2:
            return matched

    ax, ay = float(marker.x), float(marker.y)
    left = _lines_left_of_anchor(page_lines, ax, ay, float(getattr(marker, "box_height", 0) or 120))
    if len(left) >= zh_count >= 2:
        return left[:zh_count]
    return region_lines


def _marker_needs_reflow(marker: Any) -> bool:
    if getattr(marker, "display_mode", "marker") != "inline":
        return False
    zh_lines = _split_translation_lines(getattr(marker, "text", "") or "")
    if len(zh_lines) >= 2:
        return True
    h = float(getattr(marker, "box_height", 0) or 0)
    if h > 36 and len((getattr(marker, "text", "") or "").strip()) > 12:
        return True
    orig = (getattr(marker, "original_text", "") or "").strip()
    if "\n" in orig:
        return True
    return False


def _clone_marker_at_line(
    template: Any,
    line_block: Dict[str, Any],
    zh_line: str,
    page_w: float,
    page_h: float,
) -> Any:
    from src.services.inline_translation_service import _anchor_xy, _guess_placement

    placement = _guess_placement(
        line_block["width"],
        line_block["height"],
        page_w,
        page_h,
        line_block["y"],
    )
    ax, ay = _anchor_xy(line_block, placement)
    return type(template)(
        x=int(max(0, ax)),
        y=int(max(0, ay)),
        text=zh_line.strip(),
        color=getattr(template, "color", "#7C2D12"),
        display_mode="inline",
        original_text=(line_block.get("text") or "").strip(),
        placement=placement,
        box_width=int(line_block["width"]),
        box_height=int(line_block["height"]),
        source_x=int(line_block["x"]),
        source_y=int(line_block["y"]),
        font_size=getattr(template, "font_size", None) or GENERATED_INLINE_FONT_PT,
        font_family=getattr(template, "font_family", "") or "Microsoft YaHei",
        text_orientation=getattr(template, "text_orientation", "horizontal"),
    )


def _expand_marker_to_line_markers(
    marker: Any,
    page_lines: List[Dict[str, Any]],
    page_w: float,
    page_h: float,
) -> List[Any]:
    zh_lines = _split_translation_lines(getattr(marker, "text", "") or "")
    if len(zh_lines) < 2:
        return [marker]

    sx, sy, sw, sh = source_bounds_for_marker(marker)
    region = _lines_in_source_region(page_lines, sx, sy, sw, sh)
    if len(region) < 2:
        region = _lines_left_of_anchor(
            page_lines,
            float(marker.x),
            float(marker.y),
            max(sh, float(getattr(marker, "box_height", 0) or 0), 80.0),
        )
    picked = _pick_source_lines_for_marker(marker, region, page_lines, len(zh_lines))

    if len(picked) >= 2:
        n = min(len(picked), len(zh_lines))
        return [
            _clone_marker_at_line(marker, picked[i], zh_lines[i], page_w, page_h)
            for i in range(n)
        ]

    return [marker]


def reflow_inline_markers_by_text_positions(
    markers: List[Any],
    page_lines: List[Dict[str, Any]],
    page_w: float,
    page_h: float,
) -> List[Any]:
    """根据页面文本行 bbox，把合并的多行批注拆到各行原文右侧。"""
    if not markers or not page_lines:
        return markers

    out: List[Any] = []
    for m in markers:
        if _marker_needs_reflow(m):
            out.extend(_expand_marker_to_line_markers(m, page_lines, page_w, page_h))
        else:
            out.append(m)

    if len(out) < 2:
        return out

    from src.services.inline_translation_service import dedupe_inline_markers

    return dedupe_inline_markers(out)
