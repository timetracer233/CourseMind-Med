import tempfile
from pyvis.network import Network
from src.schemas import KnowledgeNode, KnowledgeEdge


COLORS = {
    "核心概念": "#e74c3c",
    "机制": "#3498db",
    "方法": "#2ecc71",
    "现象": "#f39c12",
    "结构": "#9b59b6",
    "概念": "#1abc9c",
}
DEFAULT_COLOR = "#95a5a6"

SHAPES = ["dot", "box", "diamond", "triangle", "star"]


def _node_color(node: KnowledgeNode) -> str:
    return COLORS.get(node.category, DEFAULT_COLOR)


def _node_shape(textbook: str, tb_index: dict[str, int]) -> str:
    idx = tb_index.get(textbook, 0)
    return SHAPES[min(idx, len(SHAPES) - 1)]


def build_graph_html(
    nodes: list[KnowledgeNode],
    edges: list[KnowledgeEdge],
    width: str = "100%",
    height: str = "600px",
) -> str:
    net = Network(height=height, width=width, directed=True, notebook=False, cdn_resources="in_line")
    net.set_options("""
    var options = {
      "physics": {"barnesHut": {"gravitationalConstant": -3000, "springLength": 200}},
      "interaction": {"hover": true, "tooltipDelay": 100},
      "nodes": {"font": {"size": 14}}
    }
    """)

    # Build textbook -> index mapping for shapes
    tb_list = list(dict.fromkeys(n.textbook for n in nodes))
    tb_index = {tb: i for i, tb in enumerate(tb_list)}

    # Track node sizes by frequency
    name_count: dict[str, int] = {}
    for n in nodes:
        name_count[n.name] = name_count.get(n.name, 0) + 1

    # Deduplicate nodes by name
    seen_names: set[str] = set()
    unique_nodes: list[KnowledgeNode] = []
    for n in nodes:
        if n.name not in seen_names:
            seen_names.add(n.name)
            unique_nodes.append(n)

    for n in unique_nodes:
        size = 10 + name_count.get(n.name, 1) * 4
        label = f"{n.name}"
        title = (
            f"<b>{n.name}</b><br>"
            f"类别: {n.category}<br>"
            f"教材: {n.textbook}<br>"
            f"章节: {n.chapter}<br>"
            f"页码: {n.page}<br>"
            f"置信度: {n.confidence:.0%}<br>"
            f"{n.definition}"
        )
        shape = _node_shape(n.textbook, tb_index)
        net.add_node(n.name, label=label, title=title, color=_node_color(n), size=size, shape=shape)

    # Legend for textbook shapes
    for tb, idx in tb_index.items():
        short_name = tb[:12] + ("..." if len(tb) > 12 else "")
        legend_label = f"教材{idx + 1}: {short_name}"
        net.add_node(legend_label, label=legend_label, color="#ffffff", size=1, shape=SHAPES[idx],
                     font={"size": 10, "color": "#666"}, physics=False)

    edge_set = set()
    for e in edges:
        if e.source not in seen_names or e.target not in seen_names:
            continue
        key = (e.source, e.target, e.relation_type)
        if key in edge_set:
            continue
        edge_set.add(key)
        net.add_edge(e.source, e.target, title=f"{e.relation_type}: {e.description}", label=e.relation_type)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(net.html)
        return f.name

    return ""
