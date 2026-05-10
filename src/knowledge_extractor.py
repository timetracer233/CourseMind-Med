import re
from src.schemas import Textbook, KnowledgeNode, KnowledgeEdge
from src.llm_client import chat_json, has_api_key

EXTRACT_PROMPT = """你是一个医学教材知识工程师。请从以下教材章节中抽取核心知识点和它们之间的关系。

示例输入章节："炎症的基本概念"
示例输入内容："炎症是机体对损伤因子的防御性反应。炎症的局部临床表现包括红、肿、热、痛和功能障碍。"
示例输出：
{{
  "nodes": [
    {{
      "name": "炎症",
      "definition": "机体对损伤因子的防御性反应",
      "category": "核心概念",
      "chapter": "炎症的基本概念",
      "page": 1,
      "confidence": 0.95
    }},
    {{
      "name": "损伤因子",
      "definition": "引起组织损伤的致炎因子",
      "category": "概念",
      "chapter": "炎症的基本概念",
      "page": 1,
      "confidence": 0.85
    }}
  ],
  "edges": [
    {{
      "source": "损伤因子",
      "target": "炎症",
      "relation_type": "prerequisite",
      "description": "损伤因子是炎症的诱因"
    }}
  ]
}}

---
现在请从以下教材章节中抽取核心知识点和它们之间的关系。

章节: {chapter}
教材: {textbook}
内容:
{text}

请输出 JSON，格式如下：
{{
  "nodes": [
    {{
      "name": "知识点名称",
      "definition": "一句话定义",
      "category": "核心概念|机制|方法|现象|结构",
      "chapter": "{chapter}",
      "page": {page},
      "confidence": 0.0-1.0
    }}
  ],
  "edges": [
    {{
      "source": "知识点A",
      "target": "知识点B",
      "relation_type": "contains|prerequisite|parallel|applies_to",
      "description": "简短关系描述"
    }}
  ]
}}

要求：
- 每章最多抽取8个核心知识点
- 只抽取医学相关知识点
- 关系类型只用 contains/prerequisite/parallel/applies_to
- 如果内容太少可返回空列表"""


def _rule_extract(tb: Textbook) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    """Rule-based fallback when LLM is unavailable."""
    nodes = []
    edges = []
    chinese_words = re.compile(r"[一-鿿]{2,6}")

    for ch in tb.chapters:
        # use chapter title as a node
        name = ch.title.strip()
        if name:
            words = chinese_words.findall(ch.text[:1000])
            freq = {}
            for w in words:
                if len(w) >= 2:
                    freq[w] = freq.get(w, 0) + 1
            top_words = sorted(freq.items(), key=lambda x: -x[1])[:5]
            definition = ch.text[:100].replace("\n", " ")
            nodes.append(KnowledgeNode(
                name=name,
                definition=definition,
                category="核心概念",
                chapter=ch.title,
                page=ch.page_start,
                textbook=tb.filename,
                confidence=0.7,
            ))
            for w, _ in top_words:
                if w != name:
                    nodes.append(KnowledgeNode(
                        name=w,
                        definition="",
                        category="概念",
                        chapter=ch.title,
                        page=ch.page_start,
                        textbook=tb.filename,
                        confidence=0.5,
                    ))

    # create edges between nodes in same chapter
    for i in range(len(nodes) - 1):
        if nodes[i].chapter == nodes[i + 1].chapter:
            edges.append(KnowledgeEdge(
                source=nodes[i].name,
                target=nodes[i + 1].name,
                relation_type="parallel",
                description=f"{nodes[i].name}与{nodes[i + 1].name}同属{nodes[i].chapter}",
            ))

    return nodes, edges


def extract_from_textbook(tb: Textbook) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    if not has_api_key():
        return _rule_extract(tb)

    all_nodes = []
    all_edges = []

    for ch in tb.chapters:
        prompt = EXTRACT_PROMPT.format(
            chapter=ch.title,
            textbook=tb.filename,
            text=ch.text[:1500],
            page=ch.page_start,
        )
        result = chat_json([{"role": "user", "content": prompt}])
        if result is None:
            continue
        nodes_data = result.get("nodes", [])
        edges_data = result.get("edges", [])
        for n in nodes_data:
            all_nodes.append(KnowledgeNode(
                name=n.get("name", ""),
                definition=n.get("definition", ""),
                category=n.get("category", "核心概念"),
                chapter=n.get("chapter", ch.title),
                page=n.get("page", ch.page_start),
                textbook=n.get("textbook", tb.filename),
                confidence=float(n.get("confidence", 1.0)),
            ))
        for e in edges_data:
            all_edges.append(KnowledgeEdge(
                source=e.get("source", ""),
                target=e.get("target", ""),
                relation_type=e.get("relation_type", "parallel"),
                description=e.get("description", ""),
            ))

    if not all_nodes:
        return _rule_extract(tb)

    return all_nodes, all_edges
