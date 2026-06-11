from typing import List, Optional
from pydantic import BaseModel, Field
from .page import Page

class Document(BaseModel):
    """文档模型"""
    file_path: str
    file_type: str  # "pdf" 或 "ppt"
    title: Optional[str] = None
    author: Optional[str] = None
    pages: List[Page] = Field(default_factory=list)
    
    @property
    def total_pages(self) -> int:
        return len(self.pages)
    
    def add_page(self, page: Page) -> None:
        self.pages.append(page)
    
    def get_page(self, page_number: int) -> Optional[Page]:
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None