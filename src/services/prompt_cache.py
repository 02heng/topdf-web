"""DeepSeek 前缀缓存友好的提示词组装（对齐 Reasonix：不可变前缀 + 仅末尾追加可变内容）。"""
from __future__ import annotations

# 与 vision_annotation_service.TEXT_ANNOTATION_PROMPT 保持一致，供逐页批注稳定前缀复用
TEXT_ANNOTATION_TASK = """以下「当前页内容」来自系统对该页渲染图的文字识别。仅针对本页生成中文批注。

要求：
1. 概括本页核心主题和关键信息
2. 解释专业术语（如有）；若提供了文档背景，解释英文时以该领域为准
3. 指出重点和难点
4. 200-400 字，不要用 Markdown
5. 只输出批注正文：禁止「好的，已理解…」、禁止「1. 已理解摘要…」等套话或步骤复述，不要要求上传图片

【文字识别分行说明】
识别结果按「一行一块」组织：单行原文对应单行理解；仅当原文块内自带换行时才是多行段落。不要把编号列表多项合并成一段理解。"""

# 文档理解：合并片段时固定前缀，片段正文仅追加在末尾
MERGE_SUMMARY_STABLE = (
    "以下是一份多页文档各片段的全局理解。请合并为一份完整的「文档全局理解」："
    "统一领域判断、主题主线、术语词典与易误解词说明；消除片段间矛盾。不要写逐页批注。"
)


def build_annotation_stable_prefix(
    document_context: str,
    *,
    total_pages: int,
) -> str:
    """
    同一文档逐页批注时，各请求 user 消息的字节级相同前缀。
    勿在此放入页码或本页正文。
    """
    doc = (document_context or "").strip() or "（无全局理解，请仅根据本页内容批注）"
    return (
        f"{TEXT_ANNOTATION_TASK}\n\n"
        "【文档背景（仅供理解术语与领域，勿在批注中复述、勿写「已理解」类语句）】\n"
        f"{doc}\n\n"
        f"全文共 {total_pages} 页。下方「当前页内容」区块仅含一页，只批注该页；"
        "直接写本页专业批注正文（200-400 字），不要开场白，不要编号列「已理解」步骤。\n\n"
        "【当前页内容】\n"
    )


def build_page_content_suffix(page_number: int, page_body: str) -> str:
    """仅页码与正文变化，置于 user 消息最末尾以最大化前缀缓存命中。"""
    return f"--- 第 {page_number:04d} 页 ---\n{page_body}"


def build_partial_document_stable_prefix(
    *,
    total_pages: int,
) -> str:
    """分批理解文档时，各批请求共享的固定说明（页码范围放在可变后缀）。"""
    return (
        "以下是整份文档的一个连续页码片段（页码范围见片段标题）。"
        "请提炼：领域/行业线索、片段主题、关键英文术语及准确含义、易误解词。不要写逐页批注。\n\n"
        f"全文共 {total_pages} 页。\n\n"
        "【片段页面】\n"
    )


def build_partial_document_suffix(start_page: int, end_page: int, pages_block: str) -> str:
    return (
        f"--- 第 {start_page:04d} 页 至 第 {end_page:04d} 页 ---\n"
        f"{pages_block}"
    )


def build_merge_stable_prefix(*, total_pages: int) -> str:
    return f"{MERGE_SUMMARY_STABLE}\n\n全文共 {total_pages} 页。\n\n【各片段理解】\n"


def build_merge_suffix(partials: list[str]) -> str:
    parts = [
        f"【片段 {i + 1:02d}】\n{text}"
        for i, text in enumerate(partials)
    ]
    return "\n\n---\n\n".join(parts)
