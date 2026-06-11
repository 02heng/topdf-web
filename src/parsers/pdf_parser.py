import fitz  # PyMuPDF
import os
from typing import List
from src.models.document import Document
from src.models.page import Page
from .base_parser import BaseParser


class PDFParser(BaseParser):
    """PDF 文档解析器"""

    def parse(self, file_path: str) -> Document:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not self.supports_format(file_path):
            raise ValueError(f"不支持的文件格式: {file_path}")

        doc = Document(file_path=file_path, file_type="pdf")

        pdf_document = fitz.open(file_path)
        try:
            metadata = pdf_document.metadata
            if metadata:
                doc.title = metadata.get("title")
                doc.author = metadata.get("author")

            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                text = page.get_text("text")
                images = self._extract_images(page)
                rect = page.rect

                page_model = Page(
                    page_number=page_num + 1,
                    content=text,
                    images=images,
                    width=rect.width,
                    height=rect.height,
                )
                doc.add_page(page_model)

        except Exception as e:
            raise ValueError(f"PDF 解析错误: {str(e)}")
        finally:
            pdf_document.close()

        return doc

    def supports_format(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    def _extract_images(self, page) -> List[str]:
        images = []
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            images.append(f"image_{xref}")
        return images
