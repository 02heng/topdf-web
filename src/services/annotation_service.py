"""批注处理服务模块"""
from typing import List, Callable, Optional

from src.models.document import Document
from src.models.page import Page
from src.models.annotation import Annotation
from src.models.config import LLMConfig
from src.services.llm_service import LLMService, CREWAI_AVAILABLE
from src.utils.page_image import PageImageData, extract_page_text_for_annotation, render_page_for_annotation
from src.utils.page_text import get_page_readable_text


class AnnotationService:
    """批注处理服务"""

    def __init__(self, config: LLMConfig):
        self.llm_service = LLMService(config)
        self._crew_service = None
        self._progress_callback: Optional[Callable] = None
        self._is_paused = False
        self._is_cancelled = False

    @property
    def crew_service(self):
        if self._crew_service is None:
            from src.services.crew_service import CrewService
            self._crew_service = CrewService(self.llm_service.config)
        return self._crew_service

    @property
    def crew_available(self) -> bool:
        return CREWAI_AVAILABLE

    def set_progress_callback(self, callback: Callable) -> None:
        """设置进度回调函数"""
        self._progress_callback = callback

    def pause(self) -> None:
        """暂停处理"""
        self._is_paused = True

    def resume(self) -> None:
        """继续处理"""
        self._is_paused = False

    def cancel(self) -> None:
        """取消处理"""
        self._is_cancelled = True

    def process_document(self, document: Document) -> Document:
        """处理整个文档，生成批注"""
        total_pages = document.total_pages

        for i, page in enumerate(document.pages):
            # 检查取消状态
            if self._is_cancelled:
                break

            # 检查暂停状态
            while self._is_paused:
                import time
                time.sleep(0.1)

            # 更新进度
            if self._progress_callback:
                self._progress_callback(
                    current=i + 1,
                    total=total_pages,
                    status=f"正在处理第 {i + 1} 页..."
                )

            # 处理单页
            if self.crew_available:
                annotations = self.crew_service.process_page(page)
            else:
                annotations = []

            # 添加批注到页面
            for annotation in annotations:
                page.add_annotation(annotation)

        return document

    def process_page(
        self,
        page: Page,
        pdf_path: str = "",
        pdf_doc=None,
        source_path: str = "",
        document_context: str = "",
        total_pages: int = 0,
        page_image: Optional[PageImageData] = None,
        *,
        multi_agent: bool = False,
        cache_friendly: bool = False,
    ) -> List[Annotation]:
        """处理单页：multi_agent=True 时走 Crew；cache_friendly 时走前缀稳定的单模型（利于 DeepSeek 缓存）"""
        if multi_agent and not cache_friendly and self.crew_available and (
            pdf_path or pdf_doc is not None or source_path or page_image
        ):
            try:
                return self._process_page_multi_agent(
                    page,
                    pdf_path=pdf_path,
                    pdf_doc=pdf_doc,
                    source_path=source_path,
                    document_context=document_context,
                    page_image=page_image,
                )
            except Exception:
                pass

        if pdf_path or pdf_doc is not None or source_path or page_image is not None:
            return self._process_page_vision(
                page,
                pdf_path=pdf_path,
                pdf_doc=pdf_doc,
                source_path=source_path,
                document_context=document_context,
                total_pages=total_pages,
                page_image=page_image,
                cache_friendly=cache_friendly,
            )
        if self.crew_available:
            return self.crew_service.process_page(page)
        return []

    def _process_page_vision(
        self,
        page: Page,
        *,
        pdf_path: str = "",
        pdf_doc=None,
        source_path: str = "",
        document_context: str = "",
        total_pages: int = 0,
        page_image: Optional[PageImageData] = None,
        cache_friendly: bool = False,
    ) -> List[Annotation]:
        from src.services.vision_annotation_service import VisionAnnotationService

        vision_service = VisionAnnotationService(self.llm_service.config)
        if page_image is not None:
            return vision_service.annotate_page_from_image(
                page_image,
                document_context=document_context,
                total_pages=total_pages,
                cache_friendly=cache_friendly,
            )
        return vision_service.annotate_page_from_pdf(
            pdf_path=pdf_path,
            page_number=page.page_number,
            pdf_doc=pdf_doc,
            source_path=source_path,
            document_context=document_context,
            total_pages=total_pages,
            cache_friendly=cache_friendly,
        )

    def _process_page_multi_agent(
        self,
        page: Page,
        *,
        pdf_path: str = "",
        pdf_doc=None,
        source_path: str = "",
        document_context: str = "",
        page_image: Optional[PageImageData] = None,
    ) -> List[Annotation]:
        page_text = ""
        if page_image is not None:
            page_text = get_page_readable_text(page_image)
            if not page.width:
                page.width = page_image.width
            if not page.height:
                page.height = page_image.height
        else:
            supplement = extract_page_text_for_annotation(
                page.page_number,
                pdf_doc=pdf_doc,
                source_path=source_path or pdf_path,
            )
            try:
                _, image_b64, width, height = render_page_for_annotation(
                    page.page_number,
                    pdf_path=pdf_path,
                    pdf_doc=pdf_doc,
                    source_path=source_path,
                )
                stub = PageImageData(
                    page_number=page.page_number,
                    png_bytes=b"",
                    image_b64=image_b64,
                    width=width,
                    height=height,
                    text_supplement=supplement,
                )
                page_text = get_page_readable_text(stub) or supplement
                page.width = width
                page.height = height
            except Exception:
                page_text = supplement

        return self.crew_service.process_page_with_context(
            page,
            document_context=document_context,
            page_text=page_text,
        )

    def analyze_document_context(
        self,
        page_images,
        *,
        total_pages: int,
        source_path: str = "",
        multi_agent: bool = False,
        cache_friendly: bool = False,
    ) -> str:
        """文档全局理解：multi_agent 时由分析员+审核员通读；cache_friendly 时用稳定前缀单模型"""
        if multi_agent and not cache_friendly and self.crew_available and page_images:
            try:
                return self.crew_service.analyze_document_context(
                    page_images,
                    total_pages=total_pages,
                    source_path=source_path,
                )
            except Exception:
                pass

        from src.services.vision_annotation_service import VisionAnnotationService

        vision_service = VisionAnnotationService(self.llm_service.config)
        vision_service.ensure_vision_provider()
        return vision_service.analyze_document_from_images(
            page_images,
            total_pages=total_pages,
            source_path=source_path,
            cache_friendly=cache_friendly,
        )

    def render_document_page_images(
        self,
        *,
        total_pages: int,
        pdf_path: str = "",
        pdf_doc=None,
        source_path: str = "",
        on_progress=None,
        start_page: int = 0,
        end_page: Optional[int] = None,
    ):
        """将文档每页渲染为 base64 图片；可选页码范围（0-based，含端点）"""
        from src.utils.page_image import render_all_pages_for_annotation

        return render_all_pages_for_annotation(
            total_pages,
            pdf_path=pdf_path,
            pdf_doc=pdf_doc,
            source_path=source_path,
            on_progress=on_progress,
            start_page=start_page,
            end_page=end_page,
        )

    def switch_llm_provider(self, provider: str) -> None:
        """切换 LLM 提供商"""
        self.llm_service.switch_provider(provider)
        self._crew_service = None
