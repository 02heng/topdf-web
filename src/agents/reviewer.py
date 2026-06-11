try:
    from crewai import Agent
    from crewai import LLM
except Exception:
    Agent = None
    LLM = None


def create_reviewer_agent(llm):
    """创建审核员智能体"""
    if Agent is None:
        raise ImportError("crewai 未安装，多智能体功能不可用")
    return Agent(
        role="质量审核专家",
        goal="确保批注的准确性、完整性和可读性",
        backstory="""
        你是一位严格的质量审核专家，拥有敏锐的语言感知力和
        技术背景。你负责检查批注的准确性、一致性、格式规范，
        并提出改进建议。
        
        你的审核标准：
        1. 准确性：翻译和解释是否准确
        2. 完整性：是否遗漏重要信息
        3. 一致性：术语使用是否一致
        4. 可读性：批注是否易于理解
        5. 格式：是否符合规范要求
        """,
        verbose=True,
        allow_delegation=False,
        llm=llm
    )
