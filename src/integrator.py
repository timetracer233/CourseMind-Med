from difflib import SequenceMatcher
from src.schemas import KnowledgeNode, IntegrationDecision, DecisionAction, DecisionStatus
from src.config import MERGE_SIM_THRESHOLD


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def integrate(nodes: list[KnowledgeNode]) -> tuple[list[IntegrationDecision], dict]:
    """Generate merge/keep/remove decisions across textbooks."""
    decisions: list[IntegrationDecision] = []
    decision_id = 0

    if not nodes:
        return decisions, {
            "total_nodes": 0, "total_decisions": 0,
            "merge_count": 0, "keep_count": 0, "remove_count": 0,
            "original_chars": 0, "integrated_chars": 0, "compression_ratio": 0.0,
        }

    # Step 1: Group nodes by normalized name (exact match)
    name_to_nodes: dict[str, list[KnowledgeNode]] = {}
    for n in nodes:
        norm = n.name.strip()
        if norm not in name_to_nodes:
            name_to_nodes[norm] = []
        name_to_nodes[norm].append(n)

    merged_names: set[str] = set()

    # Step 2: Exact duplicates across textbooks → MERGE
    for norm_name, node_list in name_to_nodes.items():
        textbooks = set(n.textbook for n in node_list)
        if len(textbooks) > 1:
            decision_id += 1
            affected = [n.name for n in node_list]
            decisions.append(IntegrationDecision(
                decision_id=f"D{decision_id:03d}",
                action=DecisionAction.MERGE,
                affected_nodes=affected,
                result_node=norm_name,
                reason=f"同名知识点出现在 {len(textbooks)} 本教材中（{', '.join(sorted(textbooks))}），建议合并为「{norm_name}」",
                confidence=1.0,
            ))
            merged_names.add(norm_name)

    # Step 3: Similar names across different textbooks → MERGE
    unmerged = {k: v for k, v in name_to_nodes.items() if k not in merged_names}
    names_list = list(unmerged.keys())
    processed_sim: set[str] = set()

    for i, name_a in enumerate(names_list):
        if name_a in processed_sim:
            continue
        group = [name_a]
        for j, name_b in enumerate(names_list):
            if i >= j:
                continue
            if name_b in processed_sim:
                continue
            sim = _name_similarity(name_a, name_b)
            if sim >= MERGE_SIM_THRESHOLD:
                group.append(name_b)
                processed_sim.add(name_b)

        if len(group) > 1:
            # Check if across textbooks
            all_textbooks = set()
            for gn in group:
                for nn in unmerged[gn]:
                    all_textbooks.add(nn.textbook)
            if len(all_textbooks) > 1:
                decision_id += 1
                decisions.append(IntegrationDecision(
                    decision_id=f"D{decision_id:03d}",
                    action=DecisionAction.MERGE,
                    affected_nodes=group,
                    result_node=group[0],
                    reason=f"跨教材相似知识点（相似度≥{MERGE_SIM_THRESHOLD}），建议合并为「{group[0]}」",
                    confidence=round(_name_similarity(group[0], group[-1]), 2),
                ))
                for gn in group:
                    merged_names.add(gn)
            else:
                decision_id += 1
                decisions.append(IntegrationDecision(
                    decision_id=f"D{decision_id:03d}",
                    action=DecisionAction.KEEP,
                    affected_nodes=group,
                    result_node=group[0],
                    reason=f"同教材内相似概念，保留「{group[0]}」",
                    confidence=0.9,
                ))

        processed_sim.add(name_a)

    # Step 4: Remaining unmerged nodes → KEEP
    for norm_name in name_to_nodes:
        if norm_name not in merged_names and norm_name not in processed_sim:
            # Don't add KEEP for nodes already covered by a group
            pass

    # If no decisions at all, generate KEEP for everything
    if not decisions:
        for norm_name, node_list in name_to_nodes.items():
            decision_id += 1
            affected = [n.name for n in node_list]
            textbooks = set(n.textbook for n in node_list)
            decisions.append(IntegrationDecision(
                decision_id=f"D{decision_id:03d}",
                action=DecisionAction.KEEP,
                affected_nodes=affected,
                result_node=norm_name,
                reason=f"独有知识点，来自 {len(textbooks)} 本教材，建议保留" if len(textbooks) == 1
                else f"同教材知识点，建议保留「{norm_name}」",
                confidence=0.95,
            ))

    # Step 5: Mark short definitions for removal
    for d in list(decisions):
        if d.action == DecisionAction.MERGE and len(d.affected_nodes) > 1:
            # Check secondary nodes for short definitions
            for name in d.affected_nodes[1:]:
                found_short = False
                for n in nodes:
                    if n.name == name and len(n.definition) < 10:
                        found_short = True
                        break
                if found_short:
                    decision_id += 1
                    decisions.append(IntegrationDecision(
                        decision_id=f"D{decision_id:03d}",
                        action=DecisionAction.REMOVE,
                        affected_nodes=[name],
                        result_node=d.result_node,
                        reason=f"合并后「{name}」定义过短，建议删除，内容已并入「{d.result_node}」",
                        confidence=0.85,
                    ))

    # Step 6: Calculate stats
    total_chars = sum(len(n.definition) for n in nodes)
    merge_count = sum(1 for d in decisions if d.action == DecisionAction.MERGE)
    keep_count = sum(1 for d in decisions if d.action == DecisionAction.KEEP)
    remove_count = sum(1 for d in decisions if d.action == DecisionAction.REMOVE)

    # Estimate integrated size: unique nodes * avg def length + dedup savings
    unique_nodes = len(name_to_nodes) - merge_count
    avg_def_len = total_chars / max(len(nodes), 1)
    integrated_chars = int(unique_nodes * avg_def_len)
    compression_ratio = round(min(integrated_chars / max(total_chars, 1), 1.0), 4)

    stats = {
        "total_nodes": len(nodes),
        "total_decisions": len(decisions),
        "merge_count": merge_count,
        "keep_count": keep_count,
        "remove_count": remove_count,
        "original_chars": total_chars,
        "integrated_chars": integrated_chars,
        "compression_ratio": compression_ratio,
    }
    return decisions, stats
