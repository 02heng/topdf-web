try:
    from crewai import Agent
    from crewai import LLM
except Exception:
    Agent = None
    LLM = None


def create_translator_agent(llm):
    """创建翻译员智能体"""
    if Agent is None:
        raise ImportError("crewai 未安装，多智能体功能不可用")
    return Agent(
        role="专业文档翻译员",
        goal="将英文技术文档准确翻译成中文，保留专业术语",
        backstory="""
        你是一位拥有 10 年经验的专业翻译员，精通计算机科学、
        人工智能、软件工程等领域的术语翻译。你的翻译风格准确、
        流畅，善于处理长难句和专业概念。
        
        你的工作原则：
        1. 保持原文的逻辑结构
        2. 专业术语首次出现时附带英文原文
        3. 对于难以直译的概念，提供意译解释
        4. 保持翻译的自然流畅
        """,
        verbose=True,
        allow_delegation=False,
        llm=llm
    )
