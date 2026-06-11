import os
from typing import List, Optional
from src.models.document import Document
from src.models.page import Page
from .base_parser import BaseParser


class LiteParseParser(BaseParser):
    """基于 LiteParse 的 PDF 文档解析器"""

    def __init__(self):
        self._parser = None

    def _get_parser(self):
        """懒加载 LiteParse 解析器"""
        if self._parser is None:
            try:
                from liteparse import LiteParse
                self._parser = LiteParse(ocr_enabled=True)
            except ImportError:
                raise ImportError("请安装 liteparse: pip install liteparse")
        return self._parser

    def parse(self, file_path: str) -> Document:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not self.supports_format(file_path):
            raise ValueError(f"不支持的文件格式: {file_path}")

        doc = Document(file_path=file_path, file_type="pdf")

        parser = self._get_parser()
        result = parser.parse(file_path)

        # 遍历每一页
        for page_data in result.pages:
            page_num = page_data.page_num - 1  # LiteParse 是 1-indexed
            text = page_data.text
            width = page_data.width
            height = page_data.height

            # 提取文本项（包含位置信息）
            text_items = []
            if hasattr(page_data, 'text_items') and page_data.text_items:
                for item in page_data.text_items:
                    text_items.append({
                        "text": item.text if hasattr(item, 'text') else str(item),
                        "x": item.x if hasattr(item, 'x') else 0,
                        "y": item.y if hasattr(item, 'y') else 0,
                        "width": item.width if hasattr(item, 'width') else 0,
                        "height": item.height if hasattr(item, 'height') else 0,
                    })

            page_model = Page(
                page_number=page_num + 1,
                content=text,
                images=[],
                width=width,
                height=height,
            )

            # 保存文本项位置信息到页面模型
            page_model._text_items = text_items

            doc.add_page(page_model)

        return doc

    def supports_format(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    def get_text_with_positions(self, file_path: str) -> List[dict]:
        """获取带位置信息的文本"""
        parser = self._get_parser()
        result = parser.parse(file_path, output_format="json")

        pages_data = []
        for page_data in result.pages:
            page_info = {
                "page_num": page_data.page_num,
                "width": page_data.width,
                "height": page_data.height,
                "text": page_data.text,
                "text_items": []
            }

            if hasattr(page_data, 'text_items') and page_data.text_items:
                for item in page_data.text_items:
                    page_info["text_items"].append({
                        "text": item.text if hasattr(item, 'text') else str(item),
                        "x": item.x if hasattr(item, 'x') else 0,
                        "y": item.y if hasattr(item, 'y') else 0,
                        "width": item.width if hasattr(item, 'width') else 0,
                        "height": item.height if hasattr(item, 'height') else 0,
                    })

            pages_data.append(page_info)

        return pages_data
