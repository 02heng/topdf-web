from abc import ABC, abstractmethod
from src.models.document import Document


class BaseParser(ABC):
    """文档解析器基类"""

    @abstractmethod
    def parse(self, file_path: str) -> Document:
        """解析文档文件"""
        pass

    @abstractmethod
    def supports_format(self, file_path: str) -> bool:
        """检查是否支持该文件格式"""
        pass
