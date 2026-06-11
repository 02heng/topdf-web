"""基于页面图片的视觉批注服务"""
from __future__ import annotations

import uuid
from typing import List, Optional

import fitz
from openai import OpenAI

from src.models.annotation import Annotation
from src.models.config import LLMConfig
from src.utils.annotation_text import sanitize_page_annotation
from src.utils.image_ocr import ocr_image_b64
from src.services.prompt_cache import (
    build_annotation_stable_prefix,
    build_merge_stable_prefix,
    build_merge_suffix,
    build_page_content_suffix,
    build_partial_document_stable_prefix,
    build_partial_document_suffix,
)
from src.utils.page_image import (
    PageImageData,
    extract_page_text_for_annotation,
    render_page_for_annotation,
)

DEEPSEEK_SYSTEM = (
    "你是专业的文档批注助手。用户消息中已包含从 PDF/PPT 页面识别出的文字内容，"
    "请直接基于这些内容完成任务。"
    "禁止要求用户上传图片、禁止说「无法看到图片」或「请提供图片文件」。"
    "批注正文禁止写「好的」「已理解整份文档/摘要/当前页」等确认套话，"
    "禁止用编号罗列「已理解」步骤；直接写对本页内容的专业批注。"
)

# 原生视觉模型（OpenAI / Ollama）：消息中含 image_url 或 images 字段
VISION_ANNOTATION_PROMPT = """请根据消息中附带的页面图片，用中文生成本页批注。

要求：
1. 概括本页核心主题和关键信息
2. 解释专业术语（如有）
3. 指出重点和难点
4. 200-400 字，不要用 Markdown
5. 只输出批注正文：不要写「好的」「已理解文档/摘要」等开场白，不要复述任务步骤编号

【识图分行说明（供理解版面，批注正文仍按上要求写一段）】
画面上独立一行对应一条要点；编号列表每项一行。不要把多行列表在脑中合并成一段后再批注。"""

VISION_DOCUMENT_PROMPT = """请通读消息中整份 PDF/PPT 的全部页面，建立对「整份文档」的全局理解（不是逐页批注）。

请输出「文档全局理解」，供后续逐页批注参考，避免英文术语按日常含义误解。必须包含：
1. 文档类型与用途（这份材料在做什么、面向谁）
2. 所属领域/学科/行业（如医学、法律、计算机、金融、工程等）
3. 全文核心主题与论述主线（3-5 句）
4. 关键英文术语词典：列出重要英文词/缩写，给出在该领域下的准确中文含义
5. 易误解词：哪些英文容易望文生义，在本语境中的正确理解

不要输出逐页批注内容。"""

# DeepSeek V4 Pro（文本 API）：页面内容以 OCR/识别文字形式提供
TEXT_ANNOTATION_PROMPT = """以下「当前页内容」来自系统对该页渲染图的文字识别。仅针对本页生成中文批注。

要求：
1. 概括本页核心主题和关键信息
2. 解释专业术语（如有）；若提供了文档背景，解释英文时以该领域为准
3. 指出重点和难点
4. 200-400 字，不要用 Markdown
5. 只输出批注正文：禁止「好的，已理解…」、禁止「1. 已理解摘要…」等套话或步骤复述，不要要求上传图片

【文字识别分行说明】
识别结果按「一行一块」组织：单行原文对应单行理解；仅当原文块内自带换行时才是多行段落。不要把编号列表多项合并成一段理解。"""

TEXT_DOCUMENT_PROMPT = """以下「各页内容」来自整份 PDF/PPT 每一页渲染图的文字识别。请通读全部页面，输出「文档全局理解」（不是逐页批注）：

1. 文档类型与用途（在做什么、面向谁）
2. 所属领域/学科/行业
3. 全文核心主题与论述主线（3-5 句）
4. 关键英文术语词典：英文词/缩写 → 该领域下的准确中文含义
5. 易误解词：日常英语 vs 本文语境中的正确理解

请直接基于下方文字处理，不要要求用户提供图片，不要写逐页批注。"""

TEXT_PARTIAL_DOCUMENT_PROMPT = """以下是整份文档第 {start_page} 页到第 {end_page} 页（共 {total_pages} 页）的内容片段。
请提炼：领域/行业线索、片段主题、关键英文术语及准确含义、易误解词。不要写逐页批注。"""

MERGE_SUMMARY_PROMPT = """以下是一份 {total_pages} 页文档各片段的全局理解。请合并为一份完整的「文档全局理解」：
统一领域判断、主题主线、术语词典与易误解词说明；消除片段间矛盾。不要写逐页批注。"""

PAGE_CONTEXT_HEADER = """【文档背景（仅供理解术语与领域，勿在批注中复述、勿写「已理解」类语句）】
{document_context}

【当前页】第 {page_number} 页 / 共 {total_pages} 页

请直接写本页专业批注正文（200-400 字）。解释英文时参考上文领域与术语；不要开场白，不要编号列「已理解」步骤。

【当前页内容】"""

MAX_PAGES_PER_VISION_REQUEST = 12


class VisionAnnotationService:
    """将文档页面转为 base64 图片并调用模型阅读、批注"""

    def __init__(self, config: LLMConfig):
        self.config = config

    def supports_vision(self) -> bool:
        return self.config.provider in (
            "openai",
            "ollama",
            "deepseek",
            "xiaomi",
            "agnes",
        )

    def ensure_vision_provider(self) -> None:
        if not self.supports_vision():
            raise RuntimeError(
                "请使用 OpenAI（gpt-4o）、小米 MiMo（mimo-v2.5）、Agnes（agnes-2.0-flash）、"
                "Ollama 视觉模型，或 DeepSeek 视觉模型。"
            )

    def _xiaomi_api_model(self) -> str:
        from src.models.config import xiaomi_effective_model

        return xiaomi_effective_model(self.config.xiaomi.model)

    def _deepseek_model(self) -> str:
        return (self.config.deepseek.model or "deepseek-v4-pro").lower()

    def _deepseek_native_vision(self) -> bool:
        name = self._deepseek_model()
        return any(k in name for k in ("vl", "vision", "janus"))

    def _uses_text_pipeline(self) -> bool:
        """仅纯文本模型走 OCR/文字层；全模态提供商直接识图。"""
        return self.config.provider == "deepseek" and not self._deepseek_native_vision()

    def _agnes_api_model(self) -> str:
        from src.models.config import agnes_effective_model

        return agnes_effective_model(self.config.agnes.model)

    def _agnes_request_kwargs(self, *, thinking: bool) -> dict:
        if not thinking:
            return {}
        return {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
        }

    def _call_text_pipeline_llm(
        self,
        content: str,
        *,
        thinking: bool = False,
        log_cache_usage: bool = False,
    ) -> str:
        if self.config.provider == "agnes":
            return self._call_agnes_text(content, thinking=thinking)
        return self._call_deepseek_text(
            content,
            thinking=thinking,
            log_cache_usage=log_cache_usage,
        )

    def _deepseek_v4(self) -> bool:
        name = self._deepseek_model()
        return name.startswith("deepseek-v4") or name in ("deepseek-chat", "deepseek-reasoner")

    def annotate_page_from_image(
        self,
        page_image: PageImageData,
        *,
        document_context: str = "",
        total_pages: int = 0,
        cache_friendly: bool = False,
    ) -> List[Annotation]:
        self.ensure_vision_provider()

        content = sanitize_page_annotation(
            self._annotate_pages(
                [page_image],
                document_context=document_context,
                page_number=page_image.page_number + 1,
                total_pages=total_pages,
                thinking=False,
                cache_friendly=cache_friendly,
            )
        )

        return [
            Annotation(
                id=str(uuid.uuid4()),
                page_number=page_image.page_number,
                content=content,
                original_text=None,
                position_x=max(page_image.width - 36, 12),
                position_y=24,
                width=160,
                height=100,
                agent_role="vision",
            )
        ]

    def annotate_page_from_pdf(
        self,
        pdf_path: str,
        page_number: int,
        pdf_doc: Optional[fitz.Document] = None,
        source_path: str = "",
        document_context: str = "",
        total_pages: int = 0,
        *,
        cache_friendly: bool = False,
    ) -> List[Annotation]:
        original = source_path or pdf_path
        _, image_b64, width, height = render_page_for_annotation(
            page_number,
            pdf_path=pdf_path,
            pdf_doc=pdf_doc,
            source_path=original,
        )
        supplement = extract_page_text_for_annotation(
            page_number,
            pdf_doc=pdf_doc,
            source_path=original,
        )
        page_image = PageImageData(
            page_number=page_number,
            png_bytes=b"",
            image_b64=image_b64,
            width=width,
            height=height,
            text_supplement=supplement.strip(),
        )
        return self.annotate_page_from_image(
            page_image,
            document_context=document_context,
            total_pages=total_pages or (len(pdf_doc) if pdf_doc else 0),
            cache_friendly=cache_friendly,
        )

    def analyze_document_from_images(
        self,
        page_images: List[PageImageData],
        *,
        total_pages: int,
        source_path: str = "",
        cache_friendly: bool = False,
    ) -> str:
        if not page_images:
            return "（未能生成页面图片，将逐页单独批注）"

        doc_prompt = (
            TEXT_DOCUMENT_PROMPT if self._uses_text_pipeline() else VISION_DOCUMENT_PROMPT
        )
        if len(page_images) <= MAX_PAGES_PER_VISION_REQUEST:
            if cache_friendly and self._uses_text_pipeline():
                stable = f"{doc_prompt}\n\n全文共 {total_pages} 页。\n\n【各页内容】\n"
                suffix = self._build_text_pages_block(page_images)
                return self._call_text_pipeline_llm(
                    stable + suffix,
                    thinking=True,
                    log_cache_usage=True,
                )
            prompt = doc_prompt
            if not cache_friendly and source_path:
                prompt += f"\n\n文档：{source_path}，共 {total_pages} 页"
            return self._understand_pages(page_images, prompt, thinking=True)

        partials: List[str] = []
        for batch_start in range(0, len(page_images), MAX_PAGES_PER_VISION_REQUEST):
            batch = page_images[batch_start : batch_start + MAX_PAGES_PER_VISION_REQUEST]
            start_page = batch[0].page_number + 1
            end_page = batch[-1].page_number + 1
            if cache_friendly and self._uses_text_pipeline():
                stable = build_partial_document_stable_prefix(total_pages=total_pages)
                suffix = build_partial_document_suffix(
                    start_page,
                    end_page,
                    self._build_text_pages_block(batch),
                )
                partials.append(
                    self._call_text_pipeline_llm(
                        stable + suffix,
                        thinking=True,
                        log_cache_usage=True,
                    )
                )
            elif self._uses_text_pipeline():
                prompt = TEXT_PARTIAL_DOCUMENT_PROMPT.format(
                    start_page=start_page,
                    end_page=end_page,
                    total_pages=total_pages,
                )
                if source_path:
                    prompt += f"\n\n文档：{source_path}，共 {total_pages} 页"
                partials.append(self._understand_pages(batch, prompt, thinking=True))
            else:
                prompt = (
                    f"请通读文档第 {start_page} 页到第 {end_page} 页（共 {total_pages} 页）的截图片段。"
                    "提炼领域、主题、关键英文术语及易误解词，不要写逐页批注。"
                )
                if source_path:
                    prompt += f"\n\n文档：{source_path}"
                partials.append(self._understand_pages(batch, prompt, thinking=True))

        if cache_friendly and self._uses_text_pipeline():
            merge_user = build_merge_stable_prefix(
                total_pages=total_pages
            ) + build_merge_suffix(partials)
            return self._call_text_pipeline_llm(
                merge_user,
                thinking=True,
                log_cache_usage=True,
            )

        merge_prompt = (
            MERGE_SUMMARY_PROMPT.format(total_pages=total_pages)
            + ("\n\n文档：" + source_path if source_path else "")
            + "\n\n"
            + "\n\n---\n\n".join(
                f"【片段 {i + 1}】\n{text}" for i, text in enumerate(partials)
            )
        )
        return self._call_text_only(merge_prompt, thinking=True)

    def _page_readable_text(self, page: PageImageData) -> str:
        ocr_text = ocr_image_b64(page.image_b64)
        if ocr_text:
            return ocr_text
        if page.text_supplement:
            return page.text_supplement
        return "（本页未识别到可读文字，请根据上下文做概括性说明）"

    def _build_text_pages_block(self, pages: List[PageImageData]) -> str:
        parts: list[str] = []
        for page in pages:
            page_no = page.page_number + 1
            body = self._page_readable_text(page)
            parts.append(f"--- 第 {page_no} 页 ---\n{body}")
        return "\n\n".join(parts)

    def _annotate_pages(
        self,
        pages: List[PageImageData],
        *,
        document_context: str,
        page_number: int,
        total_pages: int,
        thinking: bool,
        cache_friendly: bool = False,
    ) -> str:
        if self._uses_text_pipeline():
            if cache_friendly:
                page_body = self._page_readable_text(pages[0]) if pages else ""
                stable = build_annotation_stable_prefix(
                    document_context,
                    total_pages=total_pages or page_number,
                )
                suffix = build_page_content_suffix(page_number, page_body)
                prompt = stable + suffix
            else:
                page_body = self._build_text_pages_block(pages)
                header = TEXT_ANNOTATION_PROMPT
                if document_context.strip():
                    header = PAGE_CONTEXT_HEADER.format(
                        document_context=document_context.strip(),
                        page_number=page_number,
                        total_pages=total_pages,
                    )
                prompt = f"{header}\n\n{page_body}"
            return self._call_text_pipeline_llm(
                prompt,
                thinking=thinking,
                log_cache_usage=cache_friendly,
            )

        prompt = VISION_ANNOTATION_PROMPT
        if document_context.strip():
            if cache_friendly:
                prompt = (
                    build_annotation_stable_prefix(
                        document_context,
                        total_pages=total_pages or page_number,
                    )
                    + build_page_content_suffix(
                        page_number,
                        "（见附带页面图片）",
                    )
                    + "\n\n"
                    + VISION_ANNOTATION_PROMPT
                )
            else:
                prompt = (
                    f"【文档背景（勿复述，勿写「已理解」套话）】\n"
                    f"{document_context.strip()}\n\n"
                    f"只批注第 {page_number} 页（共 {total_pages} 页），直接写批注正文。\n\n"
                    + prompt
                )
        if self.config.provider == "xiaomi":
            return self._call_xiaomi_vision_multi([p.image_b64 for p in pages], prompt)
        return self._call_openai_vision_multi([p.image_b64 for p in pages], prompt)

    def _understand_pages(
        self,
        pages: List[PageImageData],
        prompt: str,
        *,
        thinking: bool,
    ) -> str:
        if self._uses_text_pipeline():
            full = f"{prompt}\n\n{self._build_text_pages_block(pages)}"
            return self._call_text_pipeline_llm(full, thinking=thinking)

        if self.config.provider == "ollama":
            return self._call_ollama_vision_multi(
                [p.image_b64 for p in pages],
                prompt,
            )
        if self.config.provider == "xiaomi":
            return self._call_xiaomi_vision_multi([p.image_b64 for p in pages], prompt)
        return self._call_openai_vision_multi([p.image_b64 for p in pages], prompt)

    def complete_text(self, prompt: str, *, thinking: bool = False) -> str:
        """纯文本补全（供原位翻译等轻量任务）。"""
        return self._call_text_only(prompt, thinking=thinking)

    def _call_text_only(self, prompt: str, *, thinking: bool = False) -> str:
        provider = self.config.provider
        if provider == "openai":
            return self._call_openai_text(prompt)
        if provider == "deepseek":
            return self._call_deepseek_text(prompt, thinking=thinking)
        if provider == "ollama":
            return self._call_ollama_text(prompt)
        if provider == "xiaomi":
            return self._call_xiaomi_text(prompt)
        if provider == "agnes":
            return self._call_agnes_text(prompt, thinking=thinking)
        raise ValueError(f"不支持的 LLM 提供商: {provider}")

    def _deepseek_request_kwargs(self, *, thinking: bool) -> dict:
        if not self._deepseek_v4():
            return {}
        kwargs: dict = {
            "extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}},
        }
        if thinking:
            kwargs["reasoning_effort"] = "high"
        return kwargs

    def _call_openai_compatible_vision(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        images_b64: List[str],
        prompt: str,
    ) -> str:
        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url.rstrip("/")
        client = OpenAI(**client_kwargs)

        content: list = []
        for image_b64 in images_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high",
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()

    def _call_openai_vision_multi(self, images_b64: List[str], prompt: str) -> str:
        cfg = self.config.openai
        return self._call_openai_compatible_vision(
            api_key=cfg.api_key,
            base_url="",
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            images_b64=images_b64,
            prompt=prompt,
        )

    def _call_xiaomi_vision_multi(self, images_b64: List[str], prompt: str) -> str:
        cfg = self.config.xiaomi
        return self._call_openai_compatible_vision(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=self._xiaomi_api_model(),
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            images_b64=images_b64,
            prompt=prompt,
        )

    def _call_ollama_vision_multi(self, images_b64: List[str], prompt: str) -> str:
        import json
        import urllib.request

        cfg = self.config.ollama
        url = f"{cfg.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "images": images_b64,
            "stream": False,
            "options": {"temperature": cfg.temperature},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["message"]["content"].strip()

    def _call_openai_compatible_text(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        content: str,
    ) -> str:
        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url.rstrip("/")
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()

    def _call_openai_text(self, content: str) -> str:
        cfg = self.config.openai
        return self._call_openai_compatible_text(
            api_key=cfg.api_key,
            base_url="",
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            content=content,
        )

    def _call_xiaomi_text(self, content: str) -> str:
        cfg = self.config.xiaomi
        return self._call_openai_compatible_text(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=self._xiaomi_api_model(),
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            content=content,
        )

    def _call_agnes_text(self, content: str, *, thinking: bool = False) -> str:
        cfg = self.config.agnes
        client = OpenAI(
            api_key=cfg.api_key,
            base_url=(cfg.base_url or "https://apihub.agnes-ai.com/v1").rstrip("/"),
        )
        response = client.chat.completions.create(
            model=self._agnes_api_model(),
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            messages=[{"role": "user", "content": content}],
            **self._agnes_request_kwargs(thinking=thinking),
        )
        return (response.choices[0].message.content or "").strip()

    def _call_deepseek_text(
        self,
        content: str,
        *,
        thinking: bool = False,
        log_cache_usage: bool = False,
    ) -> str:
        cfg = self.config.deepseek
        client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        response = client.chat.completions.create(
            model=cfg.model or "deepseek-v4-pro",
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            messages=[
                {"role": "system", "content": DEEPSEEK_SYSTEM},
                {"role": "user", "content": content},
            ],
            **self._deepseek_request_kwargs(thinking=thinking),
        )
        if log_cache_usage:
            self._log_deepseek_cache_usage(response)
        message = response.choices[0].message
        text = (message.content or "").strip()
        if not text and getattr(message, "reasoning_content", None):
            text = str(message.reasoning_content).strip()
        return text

    @staticmethod
    def _log_deepseek_cache_usage(response) -> None:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
        miss = int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0)
        if hit + miss <= 0:
            return
        import logging

        pct = 100.0 * hit / (hit + miss)
        logging.getLogger(__name__).info(
            "DeepSeek 前缀缓存: hit=%s miss=%s (%.1f%%)",
            hit,
            miss,
            pct,
        )

    def _call_ollama_text(self, content: str) -> str:
        import json
        import urllib.request

        cfg = self.config.ollama
        url = f"{cfg.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "options": {"temperature": cfg.temperature},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["message"]["content"].strip()
