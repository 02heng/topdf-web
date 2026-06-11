import sys
from typing import Optional
from pydantic import BaseModel, Field


def _default_font_family() -> str:
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform == "win32":
        return "Microsoft YaHei"
    return "Noto Sans CJK SC"

class OpenAIConfig(BaseModel):
    """OpenAI 配置"""
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.3
    max_tokens: int = 4096

class OllamaConfig(BaseModel):
    """Ollama 配置"""
    base_url: str = "http://localhost:11434"
    model: str = "llama3:70b"
    temperature: float = 0.3

class DeepSeekConfig(BaseModel):
    """DeepSeek 配置"""
    api_key: str = ""
    model: str = "deepseek-v4-pro"
    temperature: float = 0.3
    max_tokens: int = 4096
    base_url: str = "https://api.deepseek.com"


class AgnesConfig(BaseModel):
    """Agnes AI（OpenAI Chat Completions 兼容）https://www.agnes-ai.com/doc/agnes-20-flash"""
    api_key: str = ""
    model: str = "agnes-2.0-flash"
    temperature: float = 0.3
    max_tokens: int = 4096
    base_url: str = "https://apihub.agnes-ai.com/v1"


def agnes_effective_model(model: str = "") -> str:
    """文档要求 model 固定为 agnes-2.0-flash。"""
    name = (model or "agnes-2.0-flash").strip().lower()
    if not name or name.startswith("agnes"):
        return "agnes-2.0-flash"
    return model.strip()


class XiaomiMiMoConfig(BaseModel):
    """小米 MiMo API（OpenAI 兼容协议）"""
    api_key: str = ""
    model: str = "mimo-v2.5"
    temperature: float = 0.3
    max_tokens: int = 4096
    # token_plan：订阅套餐（plan-manage 页 tp- 密钥）；payg：按量 sk- 密钥
    api_mode: str = "token_plan"
    base_url: str = "https://token-plan-cn.xiaomimimo.com/v1"


def xiaomi_default_base_url(api_mode: str = "token_plan") -> str:
    if (api_mode or "").strip().lower() == "payg":
        return "https://api.xiaomimimo.com/v1"
    return "https://token-plan-cn.xiaomimimo.com/v1"


def xiaomi_effective_model(model: str = "") -> str:
    """
    本应用需全模态（PDF/幻灯片识图+翻译）。
    若设置里填了 pro/flash，实际请求仍走 mimo-v2.5，与小米后台统计一致。
    """
    name = (model or "mimo-v2.5").strip().lower()
    if name in ("mimo-v2.5-pro", "mimo-v2-flash", "mimo-v2.5-pro-preview"):
        return "mimo-v2.5"
    return model or "mimo-v2.5"


class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str = "openai"  # openai / ollama / deepseek / xiaomi / agnes
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)
    xiaomi: XiaomiMiMoConfig = Field(default_factory=XiaomiMiMoConfig)
    agnes: AgnesConfig = Field(default_factory=AgnesConfig)

class AnnotationStyle(BaseModel):
    """批注样式配置"""
    font_family: str = Field(default_factory=_default_font_family)
    font_size: int = 12
    color: str = "#333333"
    background: str = "#FFFFCC"

class AnnotationConfig(BaseModel):
    """批注配置"""
    mode: str = "overlay"  # "overlay" 原位翻译 / "sidebar" 标记+侧边栏
    detail_level: str = "detailed"  # "summary", "detailed", "custom"
    style: AnnotationStyle = Field(default_factory=AnnotationStyle)

class AppConfig(BaseModel):
    """应用配置"""
    language: str = "zh-CN"
    theme: str = "system"  # "light", "dark", "system"
    recent_files_limit: int = 10
    auto_save: bool = True

class Settings(BaseModel):
    """全局设置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    annotation: AnnotationConfig = Field(default_factory=AnnotationConfig)
    app: AppConfig = Field(default_factory=AppConfig)