import uuid
from typing import List, Optional

try:
    from crewai import Crew, Task
    CREWAI_AVAILABLE = True
except Exception:
    Crew = None
    Task = None
    CREWAI_AVAILABLE = False

from src.models.config import LLMConfig
from src.models.page import Page
from src.models.annotation import Annotation
from src.services.llm_service import LLMService
from src.utils.annotation_text import sanitize_page_annotation
from src.utils.page_image import PageImageData
from src.utils.page_text import get_page_readable_text
from src.agents import (
    create_translator_agent,
    create_analyst_agent,
    create_annotator_agent,
    create_reviewer_agent,
)

MAX_DOC_PAGES_PER_BATCH = 10


class CrewService:
    """CrewAI 多智能体编排：文档理解 + 逐页翻译/分析/批注/审核"""

    def __init__(self, config: LLMConfig):
        if not CREWAI_AVAILABLE:
            raise ImportError("crewai 未安装，多智能体功能不可用。请使用单模型模式。")
        self.llm_service = LLMService(config)
        self._agents = None

    @property
    def agents(self):
        if self._agents is None:
            self._agents = self._create_agents()
        return self._agents

    def _create_agents(self) -> dict:
        llm = self.llm_service.llm
        return {
            "translator": create_translator_agent(llm),
            "analyst": create_analyst_agent(llm),
            "annotator": create_annotator_agent(llm),
            "reviewer": create_reviewer_agent(llm),
        }

    def _extract_crew_output(self, result) -> str:
        text = ""
        if result is not None:
            tasks_output = getattr(result, "tasks_output", None)
            if tasks_output:
                last = tasks_output[-1]
                text = str(getattr(last, "raw", None) or getattr(last, "output", None) or "").strip()
            if not text:
                text = str(getattr(result, "raw", None) or result or "").strip()
        return sanitize_page_annotation(text)

    def _run_crew(self, tasks: List[Task]) -> str:
        crew = Crew(
            agents=list(self.agents.values()),
            tasks=tasks,
            verbose=True,
        )
        return self._extract_crew_output(crew.kickoff())

    def _build_pages_text_block(self, pages: List[PageImageData]) -> str:
        parts: list[str] = []
        for page in pages:
            body = get_page_readable_text(page) or "（本页未识别到文字）"
            parts.append(f"--- 第 {page.page_number + 1} 页 ---\n{body}")
        return "\n\n".join(parts)

    def create_document_tasks(
        self,
        pages_text: str,
        *,
        total_pages: int,
        source_path: str = "",
        batch_hint: str = "",
    ) -> List[Task]:
        hint = f"文档：{source_path}，共 {total_pages} 页。" if source_path else f"共 {total_pages} 页。"
        if batch_hint:
            hint += f" {batch_hint}"

        analyze_task = Task(
            description=(
                "通读以下页面文字，输出「文档全局理解」（不要写逐页批注）。须包含：\n"
                "1. 文档类型与用途\n"
                "2. 所属领域/学科\n"
                "3. 全文核心主题与论述主线（3-5 句）\n"
                "4. 关键英文术语及在该领域下的准确中文含义\n"
                "5. 易误解词说明\n\n"
                f"{hint}\n\n{pages_text}"
            ),
            expected_output="结构化的文档全局理解正文",
            agent=self.agents["analyst"],
        )

        review_task = Task(
            description=(
                "审核并完善上述全局理解：术语一致、消除矛盾。"
                "只输出最终全局理解正文；禁止「好的」「已理解」等套话；不要逐页批注。"
            ),
            expected_output="审核通过的全局理解正文",
            agent=self.agents["reviewer"],
            context=[analyze_task],
        )
        return [analyze_task, review_task]

    def create_document_merge_tasks(self, partial_summaries: List[str], total_pages: int) -> List[Task]:
        combined = "\n\n---\n\n".join(
            f"【片段 {i + 1}】\n{text}" for i, text in enumerate(partial_summaries)
        )
        analyze_task = Task(
            description=(
                f"以下是一份共 {total_pages} 页文档各片段的全局理解，请合并为一份完整全局理解：\n"
                "统一领域、主题主线、术语词典与易误解词；消除片段矛盾。不要逐页批注。\n\n"
                f"{combined}"
            ),
            expected_output="合并后的完整全局理解",
            agent=self.agents["analyst"],
        )
        review_task = Task(
            description="审核合并结果，输出最终全局理解正文。禁止套话，不要逐页批注。",
            expected_output="最终全局理解正文",
            agent=self.agents["reviewer"],
            context=[analyze_task],
        )
        return [analyze_task, review_task]

    def analyze_document_context(
        self,
        page_images: List[PageImageData],
        *,
        total_pages: int,
        source_path: str = "",
    ) -> str:
        """多智能体：分析员 + 审核员 通读文档"""
        if not page_images:
            return "（未能读取页面内容，将逐页单独批注）"

        if len(page_images) <= MAX_DOC_PAGES_PER_BATCH:
            block = self._build_pages_text_block(page_images)
            return self._run_crew(
                self.create_document_tasks(
                    block, total_pages=total_pages, source_path=source_path
                )
            )

        partials: List[str] = []
        for start in range(0, len(page_images), MAX_DOC_PAGES_PER_BATCH):
            batch = page_images[start : start + MAX_DOC_PAGES_PER_BATCH]
            block = self._build_pages_text_block(batch)
            sp = batch[0].page_number + 1
            ep = batch[-1].page_number + 1
            partials.append(
                self._run_crew(
                    self.create_document_tasks(
                        block,
                        total_pages=total_pages,
                        source_path=source_path,
                        batch_hint=f"（第 {sp}-{ep} 页片段）",
                    )
                )
            )

        return self._run_crew(
            self.create_document_merge_tasks(partials, total_pages)
        )

    def create_page_tasks(
        self,
        page: Page,
        *,
        document_context: str = "",
        page_text: str = "",
    ) -> List[Task]:
        """单页四智能体：翻译 → 分析 → 批注 → 审核"""
        content = (page_text or page.content or "").strip()
        if not content:
            content = "（本页未提取到文字，请结合文档背景做专业概括批注）"

        doc_block = ""
        if document_context.strip():
            doc_block = (
                "\n\n【整份文档背景（仅供理解术语与领域；批注中禁止复述、禁止写「已理解」套话）】\n"
                f"{document_context.strip()}\n"
            )

        page_no = page.page_number + 1
        page_intro = f"【当前第 {page_no} 页内容】\n{content}{doc_block}\n"

        translate_task = Task(
            description=(
                "将以下页面内容翻译成流畅中文（若已是中文则润色并保留术语对照）：\n\n"
                f"{page_intro}\n"
                "要求：保持结构；专业术语首次出现标注英文。"
            ),
            expected_output="中文译文",
            agent=self.agents["translator"],
        )

        analyze_task = Task(
            description=(
                "分析下列译文，识别：核心主题、关键术语、逻辑结构、重点与难点。\n"
                "须结合文档背景正确理解英文专业词。\n\n"
                "内容：\n{translate_task.output}"
            ),
            expected_output="结构化分析报告",
            agent=self.agents["analyst"],
            context=[translate_task],
        )

        annotate_task = Task(
            description=(
                "基于分析与文档背景，撰写本页中文批注（200-400 字）：\n"
                "术语解释、背景补充、难点提示；只写批注正文，不要开场白或「已理解」步骤。\n\n"
                f"页面原文要点：\n{content}\n"
                "分析：{analyze_task.output}"
            ),
            expected_output="本页批注正文",
            agent=self.agents["annotator"],
            context=[translate_task, analyze_task],
        )

        review_task = Task(
            description=(
                "审核批注：准确性、术语一致、完整性、可读性；有问题直接修正。"
                "输出最终批注正文，禁止套话。\n\n"
                "待审核：{annotate_task.output}"
            ),
            expected_output="审核通过的本页批注正文",
            agent=self.agents["reviewer"],
            context=[annotate_task],
        )

        return [translate_task, analyze_task, annotate_task, review_task]

    def process_page_with_context(
        self,
        page: Page,
        *,
        document_context: str = "",
        page_text: str = "",
    ) -> List[Annotation]:
        """多智能体处理单页"""
        tasks = self.create_page_tasks(
            page,
            document_context=document_context,
            page_text=page_text,
        )
        content = self._run_crew(tasks)
        if not content:
            content = "（多智能体未生成批注内容）"

        marker_size = 22
        x = max(float(page.width or 800) - marker_size - 12, 12)
        y = 24.0

        return [
            Annotation(
                id=str(uuid.uuid4()),
                page_number=page.page_number,
                content=content,
                original_text=page_text[:500] if page_text else None,
                position_x=x,
                position_y=y,
                width=160,
                height=100,
                agent_role="multi-agent",
            )
        ]

    def process_page(self, page: Page) -> List[Annotation]:
        """兼容旧接口：无文档背景的单页多智能体"""
        return self.process_page_with_context(page)

    def _parse_crew_result(self, result, page_number: int) -> List[Annotation]:
        return [
            Annotation(
                id=str(uuid.uuid4()),
                page_number=page_number,
                content=self._extract_crew_output(result),
                agent_role="multi-agent",
            )
        ]

    def switch_llm_provider(self, provider: str) -> None:
        self.llm_service.switch_provider(provider)
        self._agents = None
