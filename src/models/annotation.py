from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class Annotation(BaseModel):
    """批注模型"""
    id: str
    page_number: int
    content: str  # 批注内容（中文）
    original_text: Optional[str] = None  # 原文
    position_x: float = 0.0
    position_y: float = 0.0
    width: float = 200.0
    height: float = 100.0
    created_at: datetime = Field(default_factory=datetime.now)
    agent_role: str = ""  # 生成批注的智能体角色
    
    def to_overlay_format(self) -> dict:
        """转换为覆盖模式格式"""
        return {
            "id": self.id,
            "content": self.content,
            "position": {"x": self.position_x, "y": self.position_y},
            "size": {"width": self.width, "height": self.height}
        }
    
    def to_sidebar_format(self) -> dict:
        """转换为侧边栏模式格式"""
        return {
            "id": self.id,
            "page": self.page_number,
            "content": self.content,
            "original": self.original_text,
            "agent": self.agent_role
        }