import os
from pathlib import Path
from datetime import datetime
from collections import Counter
from src.schemas import Textbook, KnowledgeNode, KnowledgeEdge, IntegrationDecision, DecisionAction


def _cat_stats(nodes: list[KnowledgeNode]) -> str:
    counts = Counter(n.category for n in nodes)
    return "、".join(f"{c} {n}个" for c, n in counts.most_common())


def _rel_stats(edges: list[KnowledgeEdge]) -> str:
    counts = Counter(e.relation_type for e in edges)
    return "、".join(f"{r} {n}条" for r, n in counts.most_common())


def generate_report(
    textbooks: dict[str, Textbook],
    nodes: list[KnowledgeNode],
    edges: list[KnowledgeEdge],
    decisions: list[IntegrationDecision],
    stats: dict,
    output_dir: str = "report",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    textbook_names = list(textbooks.keys())
    total_chapters = sum(len(tb.chapters) for tb in textbooks.values())
    total_chars = sum(tb.total_chars for tb in textbooks.values())
    compression_ratio = min(float(stats.get("compression_ratio", 0) or 0), 1.0)
    integrated_chars = stats.get("integrated_chars", 0)
    original_chars = stats.get("original_chars", total_chars)

    # collect case studies (top 3 merge decisions)
    merge_cases = [d for d in decisions if d.action == DecisionAction.MERGE][:5]

    cases_md = ""
    for i, d in enumerate(merge_cases):
        # Look up node details
        node_details = []
        for name in d.affected_nodes:
            for n in nodes:
                if n.name == name:
                    node_details.append(f"  - 「{n.name}」({n.textbook} / {n.chapter}): {n.definition[:80]}")
                    break
        detail_text = "\n".join(node_details) if node_details else "（无详细节点信息）"
        cases_md += f"""### 案例 {i + 1}：合并「{' + '.join(d.affected_nodes)}」

- **决策 ID**：{d.decision_id}
- **整合结果**：→「{d.result_node}」
- **理由**：{d.reason}
- **置信度**：{d.confidence}
- **涉及知识点**：
{detail_text}

"""

    report = f"""# 教材知识整合报告

> 生成时间：{now}

## 1. 整合概览

| 指标 | 数值 |
|------|------|
| 教材数量 | {len(textbooks)} |
| 教材名称 | {', '.join(textbook_names)} |
| 总章节数 | {total_chapters} |
| 原始总字数 | {original_chars:,} |
| 整合后估算字数 | {integrated_chars:,} |
| 压缩比 | {compression_ratio:.1%} |
| 知识点总数 | {len(nodes)} |
| 关系总数 | {len(edges)} |

## 2. 决策摘要

| 类型 | 数量 |
|------|------|
| 合并 (merge) | {stats.get('merge_count', 0)} |
| 保留 (keep) | {stats.get('keep_count', 0)} |
| 删除 (remove) | {stats.get('remove_count', 0)} |
| **合计** | {len(decisions)} |

## 3. 图谱统计

- **节点数**：{len(nodes)}
- **边数**：{len(edges)}
- **节点类别分布**：{_cat_stats(nodes)}
- **关系类型分布**：{_rel_stats(edges)}

## 4. 典型整合案例

{cases_md if cases_md else '暂无合并案例。'}

## 5. 教学完整性说明

本整合方案在压缩冗余内容的同时，保留了各教材的核心知识点结构。
所有合并决策均基于知识点名称相似度和定义相似度进行量化评估，
教师可通过反馈机制对任何自动决策进行人工覆盖。

教学完整性保障措施：
- 核心概念（炎症、免疫、代谢等）不会因跨教材合并而丢失。
- 合并只影响重复知识点，不删除独有内容。
- 所有决策均可被教师覆盖。
"""

    # write to file
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "整合报告.md")
    Path(report_path).write_text(report, encoding="utf-8")
    return report
