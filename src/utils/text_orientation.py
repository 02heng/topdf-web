"""批注文字横排 / 竖排显示。"""
from __future__ import annotations

ORIENTATION_HORIZONTAL = "horizontal"
ORIENTATION_VERTICAL = "vertical"

ORIENTATION_LABELS = {
    ORIENTATION_HORIZONTAL: "横向",
    ORIENTATION_VERTICAL: "竖向",
}

LABEL_TO_ORIENTATION = {v: k for k, v in ORIENTATION_LABELS.items()}


def normalize_orientation(value: str | None) -> str:
    if not value:
        return ORIENTATION_HORIZONTAL
    v = str(value).strip().lower()
    if v in (ORIENTATION_HORIZONTAL, ORIENTATION_VERTICAL):
        return v
    if v in LABEL_TO_ORIENTATION:
        return LABEL_TO_ORIENTATION[v]
    return ORIENTATION_HORIZONTAL


def format_text_for_orientation(text: str, orientation: str | None) -> str:
    """竖排：按行将字符自上而下排列（多行之间空一行）。"""
    if normalize_orientation(orientation) != ORIENTATION_VERTICAL:
        return text or ""
    raw = (text or "").replace("\r\n", "\n")
    if not raw:
        return ""
    columns = []
    for line in raw.split("\n"):
        columns.append("\n".join(line))
    return "\n\n".join(columns) if len(columns) > 1 else columns[0]
