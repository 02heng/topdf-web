"""将 OCR/按行切分的文本块合并为段落（仅合并自动换行续行，不合并列表项）。"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import statistics

from src.utils.block_font_size import font_size_from_line_height

_LIST_LINE_RE = re.compile(
    r"^(\d+[\.\)]\s+|[一二三四五六七八九十百千]+[、\.]\s*|[•\-\*●○◦▪]\s+)",
    re.UNICODE,
)


def is_standalone_line(text: str) -> bool:
    """编号/项目符号/独立标题行，应单独成块批注。"""
    t = (text or "").strip()
    if not t:
        return False
    if _LIST_LINE_RE.match(t):
        return True
    if len(t) <= 48 and t[0].isupper() and t.endswith(":"):
        return True
    # 幻灯片短句要点（如 “Sweets by the checkout,”）
    if len(t) <= 96 and t[0].isupper() and t.endswith(","):
        return True
    return False


def is_slide_bullet_line(text: str) -> bool:
    """幻灯片/讲义中的单行要点（应单独一条批注）。"""
    t = (text or "").strip()
    if not t or len(t) > 110:
        return False
    if is_standalone_line(t):
        return True
    if t[0].isupper() and not t.isupper() and len(t.split()) <= 16:
        return True
    return False


def block_text_lines_are_single_paragraph(line_texts: List[str]) -> bool:
    """多行文字是否仅为同一段落的折行，而非多条要点。"""
    if len(line_texts) < 2:
        return True
    for i in range(1, len(line_texts)):
        if not is_wrapped_continuation(line_texts[i - 1], line_texts[i]):
            return False
    return True


def are_stacked_independent_lines(
    prev_text: str,
    cur_text: str,
    gap: float,
    line_h: float,
) -> bool:
    """上下相邻、各自成句的要点行（非折行续写），应分别批注。"""
    prev = (prev_text or "").strip()
    cur = (cur_text or "").strip()
    if not prev or not cur:
        return False
    if is_wrapped_continuation(prev, cur):
        return False
    lh = max(line_h, 8.0)
    if gap < -6:
        return False
    if gap > lh * 2.8:
        return False
    if len(prev) > 130 or len(cur) > 130:
        return False
    return True


def is_wrapped_continuation(
    prev: str,
    cur: str,
    *,
    gap_pt: float | None = None,
    line_h_pt: float | None = None,
) -> bool:
    """上一行与下一行是否为同一段落的折行续写。"""
    prev = (prev or "").strip()
    cur = (cur or "").strip()
    if not prev or not cur:
        return False
    if is_slide_bullet_line(cur) or is_slide_bullet_line(prev):
        return False
    if is_standalone_line(cur) or is_standalone_line(prev):
        return False
    if prev.endswith("-"):
        return True
    if cur[0].islower():
        lh = max(line_h_pt or 12.0, 8.0)
        if gap_pt is not None and gap_pt >= lh * 0.45:
            if len(prev) <= 110 and len(cur) <= 110:
                return False
        return True
    if prev[-1] not in ".!?:;\"')」》":
        if cur[0].islower() or (not cur[0].isupper() and not _LIST_LINE_RE.match(cur)):
            return True
    return False


def join_wrapped_lines(texts: List[str]) -> str:
    if not texts:
        return ""
    result = texts[0].strip()
    for part in texts[1:]:
        t = part.strip()
        if not t:
            continue
        if result.endswith("-"):
            result = result[:-1] + t
        else:
            result = f"{result} {t}"
    return re.sub(r"\s+", " ", result).strip()


def _block_bottom(b: Dict[str, Any]) -> float:
    return float(b["y"]) + float(b["height"])


def _should_merge_into_paragraph(
    prev: Dict[str, Any],
    cur: Dict[str, Any],
    page_w: float,
) -> bool:
    prev_text = (prev.get("text") or "").strip()
    cur_text = (cur.get("text") or "").strip()
    if (
        is_standalone_line(prev_text)
        or is_standalone_line(cur_text)
        or is_slide_bullet_line(prev_text)
        or is_slide_bullet_line(cur_text)
    ):
        return False

    gap = float(cur["y"]) - _block_bottom(prev)
    prev_h = max(float(prev["height"]), 8.0)
    cur_h = max(float(cur["height"]), 8.0)
    line_h = max(prev_h, cur_h)

    px = float(prev["x"])
    cx = float(cur["x"])
    align_tol = max(28.0, page_w * 0.14)
    if abs(px - cx) <= align_tol * 1.5 and are_stacked_independent_lines(
        prev_text, cur_text, gap, line_h
    ):
        return False

    if not is_wrapped_continuation(
        prev_text, cur_text, gap_pt=gap, line_h_pt=line_h
    ):
        return False

    if gap < -4:
        return False
    if gap > line_h * 1.35:
        return False

    fs_prev = prev.get("font_size")
    fs_cur = cur.get("font_size")
    if fs_prev and fs_cur and abs(float(fs_prev) - float(fs_cur)) > 6:
        return False

    return abs(px - cx) <= align_tol * 1.5


def _merge_block_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [(b.get("text") or "").strip() for b in group]
    texts = [t for t in texts if t]
    if len(texts) <= 1:
        full = texts[0] if texts else ""
    elif any(is_standalone_line(t) for t in texts):
        full = "\n".join(texts)
    elif len(texts) >= 2 and not block_text_lines_are_single_paragraph(texts):
        full = "\n".join(texts)
    else:
        full = join_wrapped_lines(texts)
    x0 = min(float(b["x"]) for b in group)
    y0 = min(float(b["y"]) for b in group)
    x1 = max(float(b["x"]) + float(b["width"]) for b in group)
    y1 = max(float(b["y"]) + float(b["height"]) for b in group)
    h = max(y1 - y0, 8.0)

    font_sizes = [float(b["font_size"]) for b in group if b.get("font_size")]
    out: Dict[str, Any] = {
        "text": full,
        "x": x0,
        "y": y0,
        "width": max(x1 - x0, 8.0),
        "height": h,
    }
    if font_sizes:
        out["font_size"] = int(round(statistics.median(font_sizes)))
    else:
        avg_line_h = h / max(1, len(group))
        out["font_size"] = font_size_from_line_height(avg_line_h)
    return out


def lines_in_fitz_block_are_independent(block: Dict[str, Any]) -> bool:
    """PyMuPDF 文本块内多行是否为上下堆叠的独立要点（非折行段落）。"""
    entries: List[tuple] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(str(s.get("text", "")) for s in spans).strip()
        bbox = line.get("bbox")
        if len(text) < 2 or not bbox or len(bbox) < 4:
            continue
        entries.append(
            (
                text,
                float(bbox[1]),
                float(bbox[3]),
                float(bbox[0]),
            )
        )
    if len(entries) < 2:
        return False
    for i in range(1, len(entries)):
        prev_t, _, _, _ = entries[i - 1]
        cur_t, _, _, _ = entries[i]
        if is_wrapped_continuation(prev_t, cur_t):
            return False
    return all(len(t) <= 130 for t, *_ in entries)


def merge_blocks_into_paragraphs(
    blocks: List[Dict[str, Any]],
    page_w: float,
    page_h: float = 0,
) -> List[Dict[str, Any]]:
    """把同一栏、行距连续的块合并为一个段落。"""
    del page_h
    if len(blocks) < 2:
        return blocks

    ordered = sorted(blocks, key=lambda b: (round(float(b["y"]), 1), float(b["x"])))
    groups: List[List[Dict[str, Any]]] = []
    current = [ordered[0]]

    for b in ordered[1:]:
        if _should_merge_into_paragraph(current[-1], b, page_w):
            current.append(b)
        else:
            groups.append(current)
            current = [b]
    groups.append(current)

    return [_merge_block_group(g) for g in groups if g]
