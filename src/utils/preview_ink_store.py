"""预览手绘墨迹的序列化与按文件键读写。"""
from __future__ import annotations

from typing import Any, Dict, List

INK_TOOLS = frozenset({"pen", "highlighter"})


def normalize_ink_pages(raw: Any) -> Dict[int, List[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[int, List[Dict[str, Any]]] = {}
    for key, strokes in raw.items():
        try:
            page_num = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(strokes, list):
            continue
        kept = [s for s in strokes if isinstance(s, dict) and s.get("tool") in INK_TOOLS]
        if kept:
            out[page_num] = kept
    return out


def ink_pages_to_json(pages: Dict[int, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    return {str(k): v for k, v in sorted(pages.items())}


def ink_pages_from_json(data: Any) -> Dict[int, List[Dict[str, Any]]]:
    if not isinstance(data, dict):
        return {}
    return normalize_ink_pages(data)
