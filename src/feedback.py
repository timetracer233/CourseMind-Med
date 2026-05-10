from src.schemas import IntegrationDecision, DecisionAction, DecisionStatus


def process_feedback(
    user_input: str,
    decisions: list[IntegrationDecision],
) -> tuple[str, list[IntegrationDecision]]:
    """Process teacher feedback and update decisions. Supports 4 commands."""
    msg = user_input.strip()
    updated = list(decisions)
    response = ""

    if msg.startswith("保留 "):
        name = msg[3:].strip()
        found = False
        for d in updated:
            if name in d.affected_nodes:
                if d.action == DecisionAction.REMOVE:
                    d.action = DecisionAction.KEEP
                    d.status = DecisionStatus.OVERRIDDEN
                    d.reason += f" | 教师手动保留「{name}」"
                    found = True
        response = f"已将「{name}」改为保留。" if found else f"未找到包含「{name}」的决策。"

    elif msg.startswith("删除 "):
        name = msg[3:].strip()
        found = False
        for d in updated:
            if name in d.affected_nodes:
                if d.action == DecisionAction.KEEP:
                    d.action = DecisionAction.REMOVE
                    d.status = DecisionStatus.OVERRIDDEN
                    d.reason += f" | 教师手动删除「{name}」"
                    found = True
        response = f"已将「{name}」改为删除。" if found else f"未找到包含「{name}」的决策。"

    elif msg.startswith("不要合并 "):
        parts = msg[5:].strip()
        names = [x.strip() for x in parts.replace("和", " ").replace("与", " ").split() if x.strip()]
        found = False
        for d in updated:
            if d.action == DecisionAction.MERGE and any(n in d.affected_nodes for n in names):
                d.action = DecisionAction.KEEP
                d.status = DecisionStatus.OVERRIDDEN
                d.reason += f" | 教师要求不要合并「{', '.join(names)}」"
                found = True
        response = f"已将相关合并决策标记为 overridden。" if found else f"未找到包含这些知识点的合并决策。"

    elif msg.startswith("为什么合并 ") or msg.startswith("为什么 "):
        name = msg.replace("为什么合并 ", "").replace("为什么 ", "").strip()
        found = False
        for d in updated:
            if d.action == DecisionAction.MERGE and name in d.affected_nodes:
                response = f"决策 {d.decision_id}：合并「{' + '.join(d.affected_nodes)}」→「{d.result_node}」\n原因：{d.reason}\n置信度：{d.confidence}"
                found = True
                break
        if not found:
            response = f"未找到与「{name}」相关的合并决策。"

    else:
        response = "支持的指令：\n- 保留 <知识点名称>\n- 删除 <知识点名称>\n- 不要合并 <知识点A> 和 <知识点B>\n- 为什么合并 <知识点名称>"

    return response, updated
