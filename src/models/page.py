from typing import List, Optional
from pydantic import BaseModel, Field
from .annotation import Annotation

class Page(BaseModel):
    """页面模型"""
    page_number: int
    content: str
    images: List[str] = Field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    annotations: List[Annotation] = Field(default_factory=list)
    
    def add_annotation(self, annotation: Annotation) -> None:
        self.annotations.append(annotation)
    
    def get_annotations(self) -> List[Annotation]:
        return self.annotations