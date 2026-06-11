"""PDF 批注渲染工具"""
import os
import re
import sys
from typing import List, Optional, Tuple

import fitz

ICON_SIZE = 20.0
CONTENT_WIDTH = 300.0
TITLE_HEIGHT = 18.0
PADDING = 8.0
FONT_SIZE = 8.0
LINE_HEIGHT = 11.0
CONTENT_MIN_HEIGHT = 60.0
CONTENT_MAX_HEIGHT = 420.0


def markdown_to_plain(text: str) -> str:
    """将 Markdown 转为纯文本，保留完整批注内容"""
    if not text:
        return ""
    result = str(text)
    result = re.sub(r"#{1,6}\s*", "", result)
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", result)
    result = re.sub(r"`(.+?)`", r"\1", result)
    result = re.sub(r"^---+\s*$", "", result, flags=re.MULTILINE)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def hex_to_rgb(color_hex: str) -> Tuple[float, float, float]:
    color_hex = color_hex.lstrip("#")
    if len(color_hex) != 6:
        return (1.0, 0.42, 0.42)
    return (
        int(color_hex[0:2], 16) / 255,
        int(color_hex[2:4], 16) / 255,
        int(color_hex[4:6], 16) / 255,
    )


def _cjk_font_candidates() -> List[str]:
    """按平台返回中文字体候选路径（优先 TTF/TTC）"""
    if sys.platform == "darwin":
        return [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            os.path.expanduser("~/Library/Fonts/SimHei.ttf"),
            os.path.expanduser("~/Library/Fonts/msyh.ttc"),
        ]
    if sys.platform == "win32":
        return [
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
    return [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]


def _find_cjk_fontfile() -> Optional[str]:
    for path in _cjk_font_candidates():
        if os.path.exists(path):
            return path
    return None


def _get_cjk_font() -> Tuple[Optional[str], Optional[fitz.Font], str]:
    """
    获取中文字体，返回 (fontfile路径, Font对象, PDF内置字体名备用)
    """
    fontfile = _find_cjk_fontfile()
    if fontfile:
        try:
            return fontfile, fitz.Font(fontfile=fontfile), "china-ss"
        except Exception:
            pass
    return None, None, "china-ss"


def _estimate_content_height(text: str) -> float:
    inner = CONTENT_WIDTH - PADDING * 2
    chars_per_line = max(10, int(inner / 7.5))
    lines = 0
    for paragraph in text.split("\n"):
        p = paragraph.strip()
        if not p:
            lines += 1
            continue
        lines += max(1, (len(p) + chars_per_line - 1) // chars_per_line)
    body_h = lines * LINE_HEIGHT + PADDING
    total = TITLE_HEIGHT + body_h + PADDING
    return min(max(total, CONTENT_MIN_HEIGHT), CONTENT_MAX_HEIGHT)


def _wrap_line(text: str, font: fitz.Font, font_size: float, max_width: float) -> Tuple[str, str]:
    if font.text_length(text, fontsize=font_size) <= max_width:
        return text, ""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.text_length(text[:mid], fontsize=font_size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    if lo <= 0:
        return text[:1], text[1:]
    return text[:lo], text[lo:]


def _write_body_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    font: fitz.Font,
    font_size: float = FONT_SIZE,
) -> None:
    """用 TextWriter 写入完整中文批注"""
    tw = fitz.TextWriter(page.rect)
    x = rect.x0
    y = rect.y0 + font_size
    max_width = max(rect.width, 20)
    color = (0.08, 0.08, 0.08)

    for paragraph in text.split("\n"):
        remaining = paragraph.strip()
        if not remaining:
            y += LINE_HEIGHT
            continue
        while remaining:
            if y > rect.y1:
                tw.write_text(page, color=color)
                return
            line, remaining = _wrap_line(remaining, font, font_size, max_width)
            tw.append(fitz.Point(x, y), line, font=font, fontsize=font_size)
            y += LINE_HEIGHT

    tw.write_text(page, color=color)


def _draw_icon_marker(
    page: fitz.Page,
    x: float,
    y: float,
    index: int,
    border_rgb: Tuple[float, float, float],
) -> None:
    """绘制小位置标记（20×20）"""
    icon_rect = fitz.Rect(x, y, x + ICON_SIZE, y + ICON_SIZE)
    shape = page.new_shape()
    shape.draw_rect(icon_rect)
    shape.finish(
        fill=(1.0, 0.96, 0.45),
        fill_opacity=0.98,
        color=border_rgb,
        width=1.2,
    )
    shape.commit()

    fontfile, font, fallback_name = _get_cjk_font()
    label_rect = fitz.Rect(x, y + 1, x + ICON_SIZE, y + ICON_SIZE - 1)
    if fontfile:
        page.insert_textbox(
            label_rect,
            str(index),
            fontfile=fontfile,
            fontsize=11,
            color=(0.1, 0.1, 0.1),
            align=fitz.TEXT_ALIGN_CENTER,
        )
    else:
        page.insert_textbox(
            label_rect,
            str(index),
            fontname=fallback_name,
            fontsize=11,
            color=(0.1, 0.1, 0.1),
            align=fitz.TEXT_ALIGN_CENTER,
        )


def _draw_content_panel(
    page: fitz.Page,
    x: float,
    y: float,
    plain_text: str,
    index: int,
    border_rgb: Tuple[float, float, float],
) -> float:
    """绘制批注内容大框，直接嵌入完整中文"""
    page_rect = page.rect
    height = _estimate_content_height(plain_text)

    box_x = max(4.0, min(x, page_rect.width - CONTENT_WIDTH - 4))
    box_y = y
    if box_y + height > page_rect.height - 4:
        box_y = max(4.0, page_rect.height - height - 4)

    rect = fitz.Rect(box_x, box_y, box_x + CONTENT_WIDTH, box_y + height)

    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=(1.0, 0.98, 0.75), fill_opacity=0.97, color=border_rgb, width=1.5)
    shape.commit()

    title_rect = fitz.Rect(box_x, box_y, box_x + CONTENT_WIDTH, box_y + TITLE_HEIGHT)
    shape = page.new_shape()
    shape.draw_rect(title_rect)
    shape.finish(fill=border_rgb, fill_opacity=1.0, color=border_rgb, width=0)
    shape.commit()

    fontfile, font, fallback_name = _get_cjk_font()

    title_rect = fitz.Rect(box_x + 6, box_y + 2, box_x + CONTENT_WIDTH - 6, box_y + TITLE_HEIGHT)
    body_rect = fitz.Rect(
        box_x + PADDING,
        box_y + TITLE_HEIGHT + 4,
        box_x + CONTENT_WIDTH - PADDING,
        box_y + height - PADDING,
    )

    title_kwargs = dict(fontsize=9, color=(1, 1, 1), align=fitz.TEXT_ALIGN_LEFT)
    if fontfile:
        page.insert_textbox(title_rect, f"批注 {index}", fontfile=fontfile, **title_kwargs)
    else:
        page.insert_textbox(title_rect, f"批注 {index}", fontname=fallback_name, **title_kwargs)

    if font:
        _write_body_text(page, body_rect, plain_text, font)
    elif fontfile:
        page.insert_textbox(
            body_rect,
            plain_text,
            fontfile=fontfile,
            fontsize=FONT_SIZE,
            color=(0.08, 0.08, 0.08),
            align=fitz.TEXT_ALIGN_LEFT,
        )
    else:
        page.insert_textbox(
            body_rect,
            plain_text,
            fontname=fallback_name,
            fontsize=FONT_SIZE,
            color=(0.08, 0.08, 0.08),
            align=fitz.TEXT_ALIGN_LEFT,
        )

    return height


def add_hover_sticky_note(
    page: fitz.Page,
    x: float,
    y: float,
    text: str,
    index: int = 1,
    color_hex: str = "#FF6B6B",
) -> float:
    """
    导出批注：
    - 小方块：位置标记（20×20）
    - 大方块：完整批注正文（直接绘制中文，不依赖 PDF 弹出层）
    """
    plain_text = markdown_to_plain(text)
    if not plain_text:
        plain_text = str(text).strip()
    if not plain_text:
        return 0.0

    page_rect = page.rect
    x = max(4.0, min(x, page_rect.width - ICON_SIZE - 4))
    y = max(4.0, min(y, page_rect.height - ICON_SIZE - 4))

    border_rgb = hex_to_rgb(color_hex)

    _draw_icon_marker(page, x, y, index, border_rgb)

    content_y = y + ICON_SIZE + 6
    content_height = _draw_content_panel(
        page, x, content_y, plain_text, index, border_rgb
    )

    return ICON_SIZE + 6 + content_height


def draw_page_annotations(page: fitz.Page, annotations: list) -> None:
    """导出批注（marker.x/y 为 PDF 页坐标）"""
    if not annotations:
        return

    for i, item in enumerate(annotations):
        text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
        color = item.get("color", "#FF6B6B") if isinstance(item, dict) else getattr(item, "color", "#FF6B6B")

        if isinstance(item, dict):
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
        else:
            x = float(getattr(item, "x", 0))
            y = float(getattr(item, "y", 0))

        add_hover_sticky_note(
            page, x=x, y=y, text=text, index=i + 1, color_hex=color
        )
