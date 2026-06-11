"""批注正文清洗（去掉模型套话、复述提示词）"""

from __future__ import annotations

import re

_META_LINE = re.compile(
    r"^("
    r"好的[，,]?\s*"
    r"|已理解(整份|全文|文档|当前页|摘要)"
    r"|[\d]+[\.、．\)]\s*已理解"
    r"|请与[「\"']?开始批注"
    r"|直接写本页"
    r"|以下(是|为)?(本页|当前页)"
    r")",
    re.IGNORECASE,
)

_ACK_ONLY = re.compile(
    r"^(好的[，,]?)?\s*(已理解|明白|收到|确认).{0,60}$",
    re.IGNORECASE,
)


def sanitize_page_annotation(text: str) -> str:
    """去掉「好的，已理解…」等无用开场与步骤复述，保留实质批注。"""
    if not text or not text.strip():
        return text

    raw = text.replace("\r\n", "\n").strip()
    lines = raw.split("\n")
    kept: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _META_LINE.search(stripped):
            continue
        if _ACK_ONLY.match(stripped):
            continue
        kept.append(line.rstrip())

    result = "\n".join(kept).strip()
    while result:
        parts = re.split(r"\n\s*\n", result, maxsplit=1)
        first = parts[0].strip()
        if len(first) < 100 and re.search(r"(已理解|好的[，,]|确认已)", first):
            result = parts[1].strip() if len(parts) > 1 else ""
            continue
        break

    return result if result else raw


def format_annotation_list_preview(text: str, max_chars: int = 28) -> str:
    """批注管理列表单行预览：合并换行，超出用省略号。"""
    if not text:
        return "（空）"
    line = " ".join(text.replace("\r", "\n").split())
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1].rstrip() + "…"
