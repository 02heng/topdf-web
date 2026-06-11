from typing import Optional, Any
from src.models.config import LLMConfig

try:
    from crewai import LLM as CrewLLM
except Exception:
    CrewLLM = None


class SimpleLLM:
    """当 crewai 不可用时的轻量 LLM 替代品，基于 openai 库"""

    def __init__(self, model: str = "", temperature: float = 0.7,
                 max_tokens: int = 4096, api_key: str = "",
                 base_url: str = "", **kwargs):
        import openai
        self.model = model
        self._client = openai.OpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=base_url or None,
        )
        self._temperature = temperature
        self._max_tokens = max_tokens

    def call(self, messages: Any, **kwargs) -> str:
        resp = self._client.chat.completions.create(
            model=self.model.replace("openai/", "").replace("ollama/", "")
                  .replace("deepseek/", "").replace("xiaomi/", ""),
            messages=messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return resp.choices[0].message.content or ""


def _make_llm(model: str, temperature: float = 0.7, max_tokens: int = 4096,
              api_key: str = "", base_url: str = "", **kwargs) -> Any:
    """优先使用 crewai.LLM，不可用时回退到 SimpleLLM"""
    if CrewLLM is not None:
        return CrewLLM(model=model, temperature=temperature,
                       max_tokens=max_tokens, api_key=api_key,
                       base_url=base_url, **kwargs)
    return SimpleLLM(model=model, temperature=temperature,
                     max_tokens=max_tokens, api_key=api_key,
                     base_url=base_url, **kwargs)


CREWAI_AVAILABLE = CrewLLM is not None


class LLMService:
    """LLM 服务管理器"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.provider = config.provider
        self._llm = None

        if self.provider not in ["openai", "ollama", "deepseek", "xiaomi", "agnes"]:
            raise ValueError(f"不支持的 LLM 提供商: {self.provider}")

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm

    def _create_llm(self):
        if self.provider == "openai":
            return self._create_openai_llm()
        elif self.provider == "ollama":
            return self._create_ollama_llm()
        elif self.provider == "deepseek":
            return self._create_deepseek_llm()
        elif self.provider == "xiaomi":
            return self._create_xiaomi_llm()
        elif self.provider == "agnes":
            return self._create_agnes_llm()
        else:
            raise ValueError(f"不支持的提供商: {self.provider}")

    def _create_openai_llm(self):
        config = self.config.openai
        return _make_llm(
            model=f"openai/{config.model}",
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            api_key=config.api_key
        )

    def _create_ollama_llm(self):
        config = self.config.ollama
        return _make_llm(
            model=f"ollama/{config.model}",
            base_url=config.base_url,
            temperature=config.temperature
        )

    def _create_deepseek_llm(self):
        config = self.config.deepseek
        return _make_llm(
            model=f"deepseek/{config.model}",
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            api_key=config.api_key,
            base_url=config.base_url
        )

    def _create_xiaomi_llm(self):
        from src.models.config import xiaomi_effective_model

        config = self.config.xiaomi
        model = xiaomi_effective_model(config.model)
        return _make_llm(
            model=f"openai/{model}",
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            api_key=config.api_key,
            base_url=config.base_url.rstrip("/"),
        )

    def _create_agnes_llm(self):
        from src.models.config import agnes_effective_model

        config = self.config.agnes
        model = agnes_effective_model(config.model)
        return _make_llm(
            model=f"openai/{model}",
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            api_key=config.api_key,
            base_url=config.base_url.rstrip("/"),
        )

    def switch_provider(self, provider: str) -> None:
        if provider not in ["openai", "ollama", "deepseek", "xiaomi", "agnes"]:
            raise ValueError(f"不支持的提供商: {provider}")
        self.provider = provider
        self._llm = None

    def update_config(self, config: LLMConfig) -> None:
        self.config = config
        self.provider = config.provider
        self._llm = None
