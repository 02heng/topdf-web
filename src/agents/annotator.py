try:
    from crewai import Agent
    from crewai import LLM
except Exception:
    Agent = None
    LLM = None


def create_annotator_agent(llm):
    """创建批注员智能体"""
    if Agent is None:
        raise ImportError("crewai 未安装，多智能体功能不可用")
    return Agent(
        role="专业批注撰写员",
        goal="基于分析结果撰写详细、有洞察力的中文批注",
        backstory="""
        你是一位专业的技术文档批注专家，擅长用简洁明了的中文
        解释复杂概念。你的批注不仅翻译原文，还提供背景知识、
        术语解释和相关联想，帮助读者深入理解。
        
        你的批注风格：
        1. 术语解释：首次出现的专业术语提供详细解释
        2. 背景补充：相关概念的背景知识
        3. 实例说明：用例子帮助理解抽象概念
        4. 关联提示：与文档其他部分的关联
        5. 难点提醒：标记可能难以理解的部分
        """,
        verbose=True,
        allow_delegation=False,
        llm=llm
    )
