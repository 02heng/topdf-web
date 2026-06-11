"""手动添加批注时的样式预设（不同用途 = 不同显示模型）。"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Dict, List


def _default_font() -> str:
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform == "win32":
        return "Microsoft YaHei"
    return "Noto Sans CJK SC"


_FONT = _default_font()


@dataclass(frozen=True)
class AnnotationPreset:
    id: str
    label: str
    display_mode: str  # "inline" | "marker"
    color: str
    font_size: int
    font_family: str
    placement: str = "right"
    hint: str = ""


ANNOTATION_PRESETS: List[AnnotationPreset] = [
    AnnotationPreset(
        id="inline",
        label="原位译文",
        display_mode="inline",
        color="#7C2D12",
        font_size=12,
        font_family=_FONT,
        placement="right",
        hint="点击页面放置，文字直接显示在旁（可拖动、双击编辑）",
    ),
    AnnotationPreset(
        id="marker",
        label="标记批注",
        display_mode="marker",
        color="#7C3AED",
        font_size=11,
        font_family=_FONT,
        hint="点击页面放置数字标记，双击展开长文批注",
    ),
    AnnotationPreset(
        id="term",
        label="术语注释",
        display_mode="inline",
        color="#0369A1",
        font_size=10,
        font_family=_FONT,
        placement="right",
        hint="小号蓝色，适合术语/短语对照",
    ),
    AnnotationPreset(
        id="emphasis",
        label="重点提示",
        display_mode="inline",
        color="#DC2626",
        font_size=15,
        font_family=_FONT,
        placement="above",
        hint="红色较大字号，适合标题或重点句",
    ),
    AnnotationPreset(
        id="note",
        label="补充说明",
        display_mode="inline",
        color="#059669",
        font_size=11,
        font_family=_FONT,
        placement="below",
        hint="绿色，适合段落下方的补充说明",
    ),
    AnnotationPreset(
        id="custom",
        label="当前样式",
        display_mode="inline",
        color="#333333",
        font_size=12,
        font_family=_FONT,
        hint="使用右侧批注内容区已设置的字体/字号/颜色",
    ),
]

_PRESET_BY_LABEL: Dict[str, AnnotationPreset] = {p.label: p for p in ANNOTATION_PRESETS}
_PRESET_BY_ID: Dict[str, AnnotationPreset] = {p.id: p for p in ANNOTATION_PRESETS}


def get_preset_by_label(label: str) -> AnnotationPreset:
    return _PRESET_BY_LABEL.get(label, ANNOTATION_PRESETS[0])


def get_preset_labels() -> List[str]:
    return [p.label for p in ANNOTATION_PRESETS]
