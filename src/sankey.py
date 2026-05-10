"""Sankey diagram: textbook → knowledge points → integration decisions."""
from src.schemas import KnowledgeNode, IntegrationDecision, DecisionAction


def build_sankey(
    nodes: list[KnowledgeNode],
    decisions: list[IntegrationDecision],
) -> str:
    """Generate a Plotly Sankey diagram HTML fragment."""
    import plotly.graph_objects as go

    if not nodes or not decisions:
        return "<p style='color:#888;text-align:center;padding:40px'>暂无整合数据，请先执行跨教材整合</p>"

    # Build node lists (3 columns: textbooks | knowledge points | decisions)
    textbooks = list(dict.fromkeys(n.textbook for n in nodes))
    tk_labels = [f"教材: {tb[:20]}" for tb in textbooks]

    # Map node names to unique knowledge labels
    seen_kp: set[str] = set()
    kp_labels: list[str] = []
    node_to_kp: dict[str, str] = {}
    for n in nodes:
        if n.name not in seen_kp:
            label = f"{n.name}"
            kp_labels.append(label)
            node_to_kp[n.name] = label
            seen_kp.add(n.name)

    dec_labels: list[str] = []
    dec_ids: dict[str, str] = {}
    for d in decisions:
        label = f"{d.action.value}: {d.result_node[:10]}"
        dec_labels.append(label)
        dec_ids[d.decision_id] = label

    all_labels = tk_labels + kp_labels + dec_labels

    # Links: textbook → knowledge point, knowledge point → decision
    source: list[int] = []
    target: list[int] = []
    value: list[int] = []
    link_colors: list[str] = []

    MERGE_COLOR = "rgba(46,204,113,0.4)"
    KEEP_COLOR = "rgba(52,152,219,0.4)"
    REMOVE_COLOR = "rgba(231,76,60,0.4)"
    TB_COLORS = [
        "rgba(52,152,219,0.3)",
        "rgba(155,89,182,0.3)",
        "rgba(241,196,15,0.3)",
        "rgba(230,126,34,0.3)",
    ]

    # Link textbooks → knowledge points
    for n in nodes:
        if n.name in node_to_kp:
            tb_idx = textbooks.index(n.textbook) if n.textbook in textbooks else 0
            kp_idx = kp_labels.index(node_to_kp[n.name])
            source.append(tb_idx)
            target.append(len(tk_labels) + kp_idx)
            value.append(1)
            link_colors.append(TB_COLORS[min(tb_idx, len(TB_COLORS) - 1)])

    # Link knowledge points → decisions
    for d in decisions:
        dec_idx = len(tk_labels) + len(kp_labels) + dec_labels.index(dec_ids[d.decision_id])
        color = MERGE_COLOR if d.action == DecisionAction.MERGE else (
            KEEP_COLOR if d.action == DecisionAction.KEEP else REMOVE_COLOR)
        for name in d.affected_nodes:
            if name in node_to_kp:
                kp_idx = kp_labels.index(node_to_kp[name])
                source.append(len(tk_labels) + kp_idx)
                target.append(dec_idx)
                value.append(1)
                link_colors.append(color)

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15, thickness=20,
            label=all_labels,
            color=["#3498db"] * len(tk_labels) + ["#95a5a6"] * len(kp_labels) + ["#2ecc71"] * len(dec_labels),
        ),
        link=dict(
            source=source, target=target, value=value,
            color=link_colors,
        ),
    )])

    fig.update_layout(
        title="教材知识点整合流向",
        font=dict(size=11),
        height=max(400, len(all_labels) * 25),
        margin=dict(l=10, r=10, t=30, b=10),
    )

    return fig.to_html(include_plotlyjs="cdn", full_html=False)
