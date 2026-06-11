try:
    from crewai import Agent
    from crewai import LLM
except Exception:
    Agent = None
    LLM = None


def create_analyst_agent(llm):
    """创建分析员智能体"""
    if Agent is None:
        raise ImportError("crewai 未安装，多智能体功能不可用")
    return Agent(
        role="内容结构分析师",
        goal="深入分析文档内容结构，识别关键概念和逻辑关系",
        backstory="""
        你是一位资深的技术分析师，擅长快速理解复杂文档的结构
        和核心概念。你能够识别文档的主旨、论点、支撑细节，
        以及各部分之间的逻辑关系。
        
        你的分析方法：
        1. 识别段落主题句
        2. 提取关键术语和概念
        3. 分析论证逻辑
        4. 标记重要数据和引用
        5. 识别技术难点和易混淆点
        """,
        verbose=True,
        allow_delegation=False,
        llm=llm
    )
