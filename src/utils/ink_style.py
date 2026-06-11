"""手绘墨迹（笔 / 荧光笔）的显示与导出样式。"""
from __future__ import annotations

# 荧光笔在白纸上的叠加强度（0~1，越小越淡；约 0.18 接近实体荧光笔）
HIGHLIGHTER_OPACITY = 0.18


def blend_hex_over_white(hex_color: str, opacity: float | None = None) -> str:
    """将颜色按透明度叠在白色背景上，用于 Tk 等不支持通道透明时的预览。"""
    alpha = HIGHLIGHTER_OPACITY if opacity is None else max(0.0, min(1.0, opacity))
    raw = (hex_color or "#ef4444").strip().lstrip("#")
    if len(raw) != 6:
        return hex_color or "#ef4444"
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        return hex_color or "#ef4444"
    inv = 1.0 - alpha
    r = int(r * alpha + 255 * inv)
    g = int(g * alpha + 255 * inv)
    b = int(b * alpha + 255 * inv)
    return f"#{r:02x}{g:02x}{b:02x}"
