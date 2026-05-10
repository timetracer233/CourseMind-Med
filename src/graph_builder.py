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


def _node_color(node: KnowledgeNode) -> str:
    return COLORS.get(node.category, DEFAULT_COLOR)


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

    # track node sizes by frequency
    name_count: dict[str, int] = {}
    for n in nodes:
        name_count[n.name] = name_count.get(n.name, 0) + 1

    # deduplicate nodes by name
    seen_names: set[str] = set()
    unique_nodes: list[KnowledgeNode] = []
    for n in nodes:
        if n.name not in seen_names:
            seen_names.add(n.name)
            unique_nodes.append(n)

    for n in unique_nodes:
        size = 10 + name_count.get(n.name, 1) * 4
        label = f"{n.name}"
        title = f"<b>{n.name}</b><br>类别: {n.category}<br>教材: {n.textbook}<br>章节: {n.chapter}<br>页码: {n.page}<br>{n.definition}"
        net.add_node(n.name, label=label, title=title, color=_node_color(n), size=size)

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
