"""按文本块生成原位中文翻译批注（覆盖模式）。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.models.config import LLMConfig
from src.utils.block_font_size import (
    GENERATED_INLINE_FONT_PT,
    font_size_from_fitz_spans,
    font_size_from_line_height,
)
from src.utils.text_paragraph_merge import (
    block_text_lines_are_single_paragraph,
    is_standalone_line,
    join_wrapped_lines,
)

import fitz

INLINE_TRANSLATE_PROMPT = """你是专业译者。下方 JSON 为 PDF/幻灯片上的文本块（id 与 text），坐标已按画面分行。

【语言 — 必须遵守】
- 原文为英文（或主要为英文）时，translation 必须是简体中文，禁止照抄英文原文。
- 短语、标题、流程名也要译成中文（如 Mass processes → 大批量流程 / 大规模流程）。
- 仅当原文本身已是中文时，可略润色或保持中文。

【分行规则 — 必须遵守】
1. 原文 text 只有一行（无换行）→ translation 只输出一行，不要扩写成长段。
2. 原文 text 含换行符 \\n（多行一块）→ 译文行数与原文一致，按行对应翻译，用 \\n 连接，不要合并成一段。
3. 不要把多个 id 的内容合并到一个 translation；每个 id 独立一条；返回的 id 必须与输入 JSON 中的 id 完全一致。
4. 编号列表项、短语、标题：短译即可；每条要点单独一行译文，禁止把多条要点写进一个 translation。
5. 参考讲义排版：每条英文要点对应一行中文，行数与原文行数相同。

严格只返回 JSON 数组，与 id 一一对应：[{{"id":0,"translation":"..."}}, ...]
不要 Markdown，不要其它说明。

输入：
{payload}
"""

INLINE_TRANSLATE_SINGLE_PROMPT = """将下列英文（或中英混合）短语译为简洁简体中文，只输出译文一行，不要解释、不要引号、不要 Markdown：
{text}"""

MAX_BLOCKS_PER_PAGE = 64
MAX_CHARS_PER_BLOCK = 800


def generate_inline_markers_for_page(app, page_num: int, llm_config: LLMConfig) -> List[Any]:
    """提取页内文本块 → 批量翻译 → 生成 inline AnnotationMarker 列表。"""
    from src.models.annotation_marker import AnnotationMarker

    if not app.pdf_doc or page_num < 0 or page_num >= app.total_pages:
        return []

    page = app.pdf_doc[page_num]
    pw, ph = page.rect.width, page.rect.height
    blocks = _collect_text_blocks(app, page_num, page, pw, ph, llm_config)
    if not blocks:
        return []

    from src.services.vision_annotation_service import VisionAnnotationService

    llm = VisionAnnotationService(llm_config)
    translations = _translate_blocks(llm, blocks)
    style = app.settings.annotation.style

    markers: List[AnnotationMarker] = []
    for block, zh in zip(blocks, translations):
        zh = (zh or "").strip()
        if not zh:
            zh = _finalize_chinese_translation(
                llm, (block.get("text") or "").strip(), ""
            )
        if not zh:
            continue
        markers.extend(
            _markers_for_block(block, zh, style, pw, ph, AnnotationMarker)
        )

    # 与 blocks 一致（含图内 OCR），避免补译/对齐仍只看 PDF 文字层
    page_lines = blocks
    markers = _fill_missing_line_translations(
        llm, markers, page_lines, style, pw, ph, AnnotationMarker
    )
    markers = dedupe_inline_markers(markers)
    if page_lines:
        from src.utils.inline_marker_reflow import reflow_inline_markers_by_text_positions

        markers = reflow_inline_markers_by_text_positions(
            markers, page_lines, pw, ph
        )
    if hasattr(app, "update_status") and markers:
        app.update_status(
            f"第 {page_num + 1} 页原位翻译完成，共 {len(markers)} 条（已按原文行对齐）"
        )
    return markers


def _page_line_positions(page: fitz.Page) -> List[Dict[str, Any]]:
    """当前页所有原文行的精确坐标（用于拆分批注与补译）。"""
    return _best_line_blocks_from_page(page)


def _best_line_blocks_from_page(page: fitz.Page) -> List[Dict[str, Any]]:
    """取行数最多的提取结果，尽量覆盖幻灯片每一条要点。"""
    candidates: List[List[Dict[str, Any]]] = []
    for extractor in (
        _blocks_from_fitz_word_lines,
        _blocks_from_fitz_lines,
        _blocks_from_fitz_dict_blocks,
    ):
        raw = extractor(page)
        if raw:
            candidates.append(_filter_and_rank_blocks(raw))
    if not candidates:
        return []
    blocks = max(candidates, key=len)
    blocks = _split_multiline_blocks(blocks)
    blocks = _split_heuristic_long_lines(blocks)
    return _dedupe_inline_line_blocks(blocks)


def _normalize_block_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _fill_missing_line_translations(
    llm,
    markers: List[Any],
    page_lines: List[Dict[str, Any]],
    style: Any,
    page_w: float,
    page_h: float,
    marker_cls: Any,
) -> List[Any]:
    """对页面上已识别但未生成译文的行逐条补译。"""
    if not page_lines:
        return markers

    covered: set = set()
    for m in markers:
        orig = _normalize_block_text_key(getattr(m, "original_text", "") or "")
        if orig:
            covered.add(orig)

    out = list(markers)
    for block in page_lines:
        src = (block.get("text") or "").strip()
        if len(src) < 2:
            continue
        key = _normalize_block_text_key(src)
        if key in covered:
            continue
        if any(_texts_same_region(src, c) for c in covered):
            continue
        if not _is_mostly_english(src):
            continue
        zh = _finalize_chinese_translation(llm, src, "")
        if not zh:
            continue
        out.extend(_markers_for_block(block, zh, style, page_w, page_h, marker_cls))
        covered.add(key)
    return out


def dedupe_inline_markers(markers: List[Any]) -> List[Any]:
    """去掉同一原文的重复批注，保留逐行译文（不合并相邻行）。"""
    if len(markers) < 2:
        return markers

    kept: List[Any] = []
    for m in markers:
        orig = (getattr(m, "original_text", "") or "").strip()
        if orig and any(
            (getattr(k, "original_text", "") or "").strip() == orig for k in kept
        ):
            continue
        kept.append(m)
    return kept


def _line_slice_block(
    block: Dict[str, Any], line_text: str, index: int, total: int
) -> Dict[str, Any]:
    y0 = float(block["y"])
    h = max(float(block.get("height", 0) or 0), 8.0 * total)
    line_h = h / max(total, 1)
    return {
        **block,
        "text": line_text,
        "y": y0 + index * line_h,
        "height": max(line_h, 8.0),
    }


def _markers_for_block(
    block: Dict[str, Any],
    zh: str,
    style: Any,
    page_w: float,
    page_h: float,
    marker_cls: Any,
) -> List[Any]:
    """按行生成原位批注：一行英文对应一行中文，贴在行右侧。"""
    orig_lines = [ln.strip() for ln in (block.get("text") or "").split("\n") if ln.strip()]
    zh_lines = [ln.strip() for ln in zh.split("\n") if ln.strip()]

    pairs: List[tuple] = []
    if len(orig_lines) >= 2 and len(zh_lines) >= 2:
        n = min(len(orig_lines), len(zh_lines))
        pairs = [
            (
                _line_slice_block(block, orig_lines[i], i, n),
                zh_lines[i],
            )
            for i in range(n)
        ]
    elif len(zh_lines) >= 2:
        n = len(zh_lines)
        pairs = [
            (_line_slice_block(block, orig_lines[0] if orig_lines else "", i, n), zh_lines[i])
            for i in range(n)
        ]
    else:
        pairs = [(block, zh)]

    out: List[Any] = []
    for sub_block, line_zh in pairs:
        line_zh = (line_zh or "").strip()
        if not line_zh:
            continue
        placement = _guess_placement(
            sub_block["width"],
            sub_block["height"],
            page_w,
            page_h,
            sub_block["y"],
        )
        ax, ay = _anchor_xy(sub_block, placement)
        out.append(
            marker_cls(
                x=int(max(0, ax)),
                y=int(max(0, ay)),
                text=line_zh,
                color=style.color or "#7C2D12",
                display_mode="inline",
                original_text=sub_block.get("text", ""),
                placement=placement,
                box_width=int(sub_block["width"]),
                box_height=int(sub_block["height"]),
                source_x=int(sub_block["x"]),
                source_y=int(sub_block["y"]),
                font_size=GENERATED_INLINE_FONT_PT,
                font_family=style.font_family or "Microsoft YaHei",
            )
        )
    return out


def _collect_text_blocks(
    app,
    page_num: int,
    page: fitz.Page,
    pw: float,
    ph: float,
    llm_config: Optional[LLMConfig] = None,
) -> List[Dict[str, Any]]:
    """按行提取可翻译块（原位翻译不合并段落，避免整页只译标题+一段）。"""
    from src.utils.page_ocr_positions import (
        _merge_blocks,
        clear_page_ocr_cache,
        ensure_page_ocr_positions,
        vision_native_for_inline,
    )

    blocks = _best_line_blocks_from_page(page)

    if not blocks:
        raw = list((app.text_positions or {}).get(page_num, []))
        if raw and _looks_like_pptx_emu(raw[0]):
            slide = getattr(app, "ppt_slide_emu", None) or (9144000, 6858000)
            sw, sh = slide
            blocks = [_pptx_item_to_pdf_block(item, sw, sh, pw, ph) for item in raw]
        elif raw:
            blocks = [_normalize_pdf_block(item, pw, ph) for item in raw]
        else:
            blocks = _blocks_from_fitz(page)
        blocks = _filter_and_rank_blocks(blocks)
        blocks = _split_multiline_blocks(blocks)
        blocks = _split_heuristic_long_lines(blocks)
        blocks = _dedupe_inline_line_blocks(blocks)

    text_paragraphs = len(blocks)
    use_vision = vision_native_for_inline(llm_config)
    # 全模态（含小米 mimo-v2.5）每次原位翻译都重新识图，避免只译左侧正文、漏掉图表内文字
    force_supplement = use_vision or text_paragraphs < 2
    if force_supplement:
        clear_page_ocr_cache(app, page_num)

    extra_blocks = ensure_page_ocr_positions(
        app,
        page_num,
        llm_config,
        force=force_supplement,
        text_layer_paragraphs=text_paragraphs,
    )
    if extra_blocks:
        merged = _merge_blocks(extra_blocks, blocks)
        blocks = _split_multiline_blocks(merged)
        blocks = _split_heuristic_long_lines(blocks)
        blocks = _dedupe_inline_line_blocks(_filter_and_rank_blocks(blocks))
        blocks = _dedupe_overlapping_blocks(blocks)

    return blocks[:MAX_BLOCKS_PER_PAGE]


def _looks_like_pptx_emu(item: Dict[str, Any]) -> bool:
    """python-pptx 坐标为 EMU，数值远大于 PDF 点。"""
    w = float(item.get("width", 0) or 0)
    x = float(item.get("x", 0) or 0)
    return w > 50_000 or x > 50_000


def _pptx_item_to_pdf_block(
    item: Dict[str, Any],
    slide_w_emu: int,
    slide_h_emu: int,
    page_w: float,
    page_h: float,
) -> Dict[str, Any]:
    def scale(v: float, slide_emu: int, page_pt: float) -> float:
        if slide_emu <= 0:
            return 0.0
        return float(v) / float(slide_emu) * page_pt

    x = scale(float(item.get("x", 0)), slide_w_emu, page_w)
    y = scale(float(item.get("y", 0)), slide_h_emu, page_h)
    w = scale(float(item.get("width", 0)), slide_w_emu, page_w)
    h = scale(float(item.get("height", 0)), slide_h_emu, page_h)
    fs = item.get("font_size")
    if fs is None and h >= 6:
        fs = font_size_from_line_height(h)
    out = {
        "text": str(item.get("text", "")).strip(),
        "x": x,
        "y": y,
        "width": max(w, 8),
        "height": max(h, 8),
    }
    if fs is not None:
        out["font_size"] = fs
    return out


def _normalize_pdf_block(item: Dict[str, Any], pw: float, ph: float) -> Dict[str, Any]:
    x = float(item.get("x", 0))
    y = float(item.get("y", 0))
    w = float(item.get("width", 0) or 0)
    h = float(item.get("height", 0) or 0)
    if w > pw * 1.5 or h > ph * 1.5:
        scale = app_canvas_scale_guess(pw, x, y)
        if scale > 1:
            x /= scale
            y /= scale
            w /= scale
            h /= scale
    h = max(h, 8)
    out = {
        "text": str(item.get("text", "")).strip(),
        "x": max(0, x),
        "y": max(0, y),
        "width": max(w, 8),
        "height": h,
    }
    fs = item.get("font_size")
    if fs is None and h >= 6:
        fs = font_size_from_line_height(h)
    if fs is not None:
        out["font_size"] = fs
    return out


def app_canvas_scale_guess(pw: float, x: float, y: float) -> float:
    if x > pw * 2 or y > pw * 2:
        return 2.0
    return 1.0


def _blocks_from_fitz_dict_blocks(page: fitz.Page) -> List[Dict[str, Any]]:
    """按 PyMuPDF 文本块提取；含列表/多行目录时按行拆块。"""
    out: List[Dict[str, Any]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        line_texts: List[str] = []
        spans: List[dict] = []
        x0 = y0 = x1 = y1 = None
        for line in block.get("lines", []):
            line_spans = line.get("spans", [])
            text = "".join(str(s.get("text", "")) for s in line_spans).strip()
            if text:
                line_texts.append(text)
            spans.extend(line_spans)
            bbox = line.get("bbox")
            if bbox and len(bbox) >= 4:
                if x0 is None:
                    x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                else:
                    x0 = min(x0, bbox[0])
                    y0 = min(y0, bbox[1])
                    x1 = max(x1, bbox[2])
                    y1 = max(y1, bbox[3])
        if len(line_texts) >= 2 and not block_text_lines_are_single_paragraph(
            line_texts
        ):
            for line in block.get("lines", []):
                line_spans = line.get("spans", [])
                text = "".join(str(s.get("text", "")) for s in line_spans).strip()
                bbox = line.get("bbox")
                if len(text) < 2 or not bbox or len(bbox) < 4:
                    continue
                lx0, ly0, lx1, ly1 = bbox[0], bbox[1], bbox[2], bbox[3]
                lh = max(ly1 - ly0, 8)
                lfs = font_size_from_fitz_spans(line_spans) or font_size_from_line_height(
                    lh
                )
                out.append(
                    {
                        "text": text,
                        "x": lx0,
                        "y": ly0,
                        "width": max(lx1 - lx0, 8),
                        "height": lh,
                        "font_size": lfs,
                    }
                )
            continue

        full = join_wrapped_lines(line_texts)
        if len(full) < 2 or x0 is None:
            continue
        block_h = max(y1 - y0, 8)
        line_heights: List[float] = []
        for line in block.get("lines", []):
            lb = line.get("bbox")
            if lb and len(lb) >= 4:
                line_heights.append(max(float(lb[3]) - float(lb[1]), 8.0))
        line_h = max(line_heights) if line_heights else block_h
        fs = font_size_from_fitz_spans(spans)
        if fs is None:
            fs = font_size_from_line_height(line_h)
        out.append(
            {
                "text": full,
                "x": x0,
                "y": y0,
                "width": max(x1 - x0, 8),
                "height": block_h,
                "font_size": fs,
            }
        )
    return out


def _blocks_from_fitz_word_lines(page: fitz.Page) -> List[Dict[str, Any]]:
    """按 PDF 词级 (block,line) 聚合成行，PPT 转 PDF 时比 span 行更细。"""
    out: List[Dict[str, Any]] = []
    try:
        words = page.get_text("words")
    except Exception:
        return out
    if not words:
        return out

    from collections import defaultdict

    groups: Dict[tuple, list] = defaultdict(list)
    for w in words:
        if len(w) < 8:
            continue
        text = str(w[4] or "").strip()
        if not text:
            continue
        block_no = int(w[5])
        line_no = int(w[6])
        groups[(block_no, line_no)].append(w)

    for key in sorted(groups.keys()):
        ws = sorted(groups[key], key=lambda item: (float(item[7]), float(item[0])))
        text = " ".join(str(item[4]).strip() for item in ws if str(item[4]).strip()).strip()
        if len(text) < 2:
            continue
        x0 = min(float(item[0]) for item in ws)
        y0 = min(float(item[1]) for item in ws)
        x1 = max(float(item[2]) for item in ws)
        y1 = max(float(item[3]) for item in ws)
        line_h = max(y1 - y0, 8)
        out.append(
            {
                "text": text,
                "x": x0,
                "y": y0,
                "width": max(x1 - x0, 8),
                "height": line_h,
                "font_size": font_size_from_line_height(line_h),
            }
        )
    return out


def _split_heuristic_long_lines(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把仍挤在一行里的多条英文要点拆成多行块。"""
    out: List[Dict[str, Any]] = []
    split_re = re.compile(r"(?<=[a-z,.!?])\s+(?=[A-Z][a-z])")
    for b in blocks:
        text = (b.get("text") or "").strip()
        if len(text) < 50:
            out.append(b)
            continue
        parts = [p.strip() for p in split_re.split(text) if len(p.strip()) >= 3]
        if len(parts) < 2:
            out.append(b)
            continue
        n = len(parts)
        y0 = float(b["y"])
        h = max(float(b.get("height", 0) or 0), 8.0 * n)
        line_h = h / n
        for i, part in enumerate(parts):
            out.append(
                {
                    **b,
                    "text": part,
                    "y": y0 + i * line_h,
                    "height": max(line_h, 8.0),
                }
            )
    out.sort(key=lambda x: (round(float(x["y"]), 1), float(x["x"])))
    return out


def _dedupe_inline_line_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅去掉坐标与文字完全相同的重复行，不合并相邻要点。"""
    kept: List[Dict[str, Any]] = []
    seen: set = set()
    for b in blocks:
        text = (b.get("text") or "").strip()
        if len(text) < 2:
            continue
        key = (
            round(float(b["x"]), 1),
            round(float(b["y"]), 1),
            _normalize_block_text_key(text),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(b)
    kept.sort(key=lambda b: (round(float(b["y"]), 1), float(b["x"])))
    return kept


def _blocks_from_fitz_lines(page: fitz.Page) -> List[Dict[str, Any]]:
    """按 PDF 文本行提取框，与渲染位置一致（适合 PPT 转 PDF 后的幻灯片）。"""
    out: List[Dict[str, Any]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(str(s.get("text", "")) for s in spans).strip()
            if len(text) < 2:
                continue
            bbox = line.get("bbox")
            if not bbox and spans:
                bbox = spans[0].get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
            line_h = max(y1 - y0, 8)
            fs = font_size_from_fitz_spans(spans)
            if fs is None:
                fs = font_size_from_line_height(line_h)
            out.append(
                {
                    "text": text,
                    "x": x0,
                    "y": y0,
                    "width": max(x1 - x0, 8),
                    "height": line_h,
                    "font_size": fs,
                }
            )
    return out


def _blocks_from_fitz(page: fitz.Page) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for block in page.get_text("blocks"):
        if len(block) < 7 or block[6] != 0:
            continue
        text = (block[4] or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
        line_h = max(y1 - y0, 8)
        out.append(
            {
                "text": text,
                "x": x0,
                "y": y0,
                "width": max(x1 - x0, 8),
                "height": line_h,
                "font_size": font_size_from_line_height(line_h),
            }
        )
    return out


def _block_rect(b: Dict[str, Any]) -> Tuple[float, float, float, float]:
    x = float(b["x"])
    y = float(b["y"])
    w = max(float(b.get("width", 0) or 0), 1.0)
    h = max(float(b.get("height", 0) or 0), 1.0)
    return x, y, x + w, y + h


def _overlap_ratio(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax0, ay0, ax1, ay1 = _block_rect(a)
    bx0, by0, bx1, by1 = _block_rect(b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    return inter / max(1.0, min(area_a, area_b))


def _texts_same_region(t1: str, t2: str) -> bool:
    a = re.sub(r"\s+", " ", (t1 or "").strip().lower())
    b = re.sub(r"\s+", " ", (t2 or "").strip().lower())
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    n = min(len(a), len(b), 32)
    return n >= 10 and a[:n] == b[:n]


def _dedupe_overlapping_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去掉同一区域被重复提取的段落，避免模型对同一段原文翻译两次。"""
    if len(blocks) < 2:
        return blocks

    ranked = sorted(
        blocks,
        key=lambda b: (
            -len((b.get("text") or "").strip()),
            -(float(b.get("width", 0) or 0) * float(b.get("height", 0) or 0)),
        ),
    )
    kept: List[Dict[str, Any]] = []
    for b in ranked:
        duplicate = False
        for k in kept:
            overlap = _overlap_ratio(b, k)
            if overlap >= 0.55:
                duplicate = True
                break
            if overlap >= 0.35 and _texts_same_region(
                b.get("text", ""), k.get("text", "")
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(b)
    kept.sort(key=lambda b: (round(float(b["y"]), 1), float(b["x"])))
    return kept


def _split_multiline_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将仍含换行的块按行拆成独立块，便于逐条原位批注与对齐。"""
    out: List[Dict[str, Any]] = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if "\n" not in text:
            out.append(b)
            continue
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 2:
            out.append(b)
            continue
        n = len(lines)
        y0 = float(b["y"])
        h = max(float(b.get("height", 0) or 0), 8.0 * n)
        line_h = h / n
        fs = b.get("font_size")
        for i, ln in enumerate(lines):
            row = {
                **b,
                "text": ln,
                "y": y0 + i * line_h,
                "height": max(line_h, 8.0),
            }
            if fs is not None:
                row["font_size"] = fs
            out.append(row)
    out.sort(key=lambda x: (round(float(x["y"]), 1), float(x["x"])))
    return out


def _filter_and_rank_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    seen: List[Tuple[float, float, str]] = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if len(text) < 2:
            continue
        if len(text) > MAX_CHARS_PER_BLOCK:
            text = text[:MAX_CHARS_PER_BLOCK]
            b = {**b, "text": text}
        if re.fullmatch(r"[\d\s\W]+", text):
            continue
        cy = float(b["y"]) + float(b["height"]) / 2
        cx = float(b["x"])
        if any(abs(cy - sy) < 4 and abs(cx - sx) < 6 and text == st for sx, sy, st in seen):
            continue
        seen.append((cx, cy, text))
        kept.append(b)
    kept.sort(key=lambda b: (round(float(b["y"]), 1), float(b["x"])))
    return kept


def _guess_placement(w: float, h: float, page_w: float, page_h: float, y: float) -> str:
    line_h = max(h, 8)
    if y < page_h * 0.18 and w > page_w * 0.35 and line_h > 32:
        return "above"
    if line_h <= 40 and w < page_w * 0.88:
        return "right"
    if line_h > 44 and w > 200:
        return "below"
    return "right"


def _anchor_xy(block: Dict[str, Any], placement: str) -> Tuple[float, float]:
    """返回 PDF 点坐标下的锚点（与 canvas anchor 对应）。"""
    x = float(block["x"])
    y = float(block["y"])
    w = float(block["width"])
    h = float(block["height"])
    mid_y = y + h * 0.5
    if placement == "right":
        return x + w + 6, mid_y
    if placement == "below":
        return x, y + h + 4
    if placement == "above":
        return x + w * 0.02, max(0, y - 2)
    return x + w + 8, mid_y


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text or ""))


def _is_mostly_english(text: str) -> bool:
    t = (text or "").strip()
    if not t or _contains_cjk(t):
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ord(c) < 0x0250)
    return latin / len(letters) >= 0.75


def _translation_still_english(source: str, translation: str) -> bool:
    src = (source or "").strip()
    zh = (translation or "").strip()
    if not zh:
        return _is_mostly_english(src)
    if not _is_mostly_english(src):
        return False
    if _contains_cjk(zh):
        return False
    if zh.lower() == src.lower():
        return True
    return _is_mostly_english(zh)


def _translate_single_phrase(llm, text: str) -> str:
    src = (text or "").strip()
    if not src:
        return ""
    if not _is_mostly_english(src):
        return src
    prompt = INLINE_TRANSLATE_SINGLE_PROMPT.format(text=src)
    try:
        raw = (llm.complete_text(prompt) or "").strip()
    except Exception:
        return ""
    raw = re.sub(r"^[\"'「『]|[\"'」』]$", "", raw).strip()
    if _translation_still_english(src, raw):
        return ""
    return raw


def _finalize_chinese_translation(llm, source: str, translation: str) -> str:
    src = (source or "").strip()
    zh = (translation or "").strip()
    if not src:
        return ""
    if not _is_mostly_english(src):
        return zh or src
    if not _translation_still_english(src, zh):
        return zh
    retry = _translate_single_phrase(llm, src)
    return retry or zh or ""


def _apply_batch_translations(
    by_id: Dict[int, str],
    chunk_len: int,
    start: int,
    parsed: List[Dict[str, Any]],
) -> None:
    id_to_local = {}
    for item in parsed:
        try:
            rid = int(item.get("id", -1))
        except (TypeError, ValueError):
            continue
        tr = str(item.get("translation", "") or item.get("text", "")).strip()
        if not tr:
            continue
        if 0 <= rid < chunk_len:
            id_to_local[rid] = tr
        elif start <= rid < start + chunk_len:
            id_to_local[rid - start] = tr

    for local_i, tr in id_to_local.items():
        by_id[start + local_i] = tr

    if len(parsed) == chunk_len:
        for local_i, item in enumerate(parsed):
            if start + local_i in by_id:
                continue
            tr = str(item.get("translation", "") or item.get("text", "")).strip()
            if tr:
                by_id[start + local_i] = tr


def _translate_blocks(llm, blocks: List[Dict[str, Any]]) -> List[str]:
    batch_size = 18
    by_id: Dict[int, str] = {}

    for start in range(0, len(blocks), batch_size):
        chunk_blocks = blocks[start : start + batch_size]
        chunk_payload = [
            {"id": i, "text": (b.get("text") or "").strip()}
            for i, b in enumerate(chunk_blocks)
        ]
        prompt = INLINE_TRANSLATE_PROMPT.format(
            payload=json.dumps(chunk_payload, ensure_ascii=False)
        )
        raw = llm.complete_text(prompt)
        parsed = _parse_translation_array(raw)
        _apply_batch_translations(by_id, len(chunk_blocks), start, parsed)

    out: List[str] = []
    for i, block in enumerate(blocks):
        src = (block.get("text") or "").strip()
        zh = _finalize_chinese_translation(llm, src, by_id.get(i, ""))
        out.append(zh)
    return out


def _parse_translation_array(text: str) -> List[Dict[str, Any]]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]
