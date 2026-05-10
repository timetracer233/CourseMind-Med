import os
import shutil
from pathlib import Path

import gradio as gr
import pandas as pd

from src.parsers import parse_file
from src.chunking import chunk_all
from src.rag import RAGEngine
from src.knowledge_extractor import extract_from_textbook
from src.graph_builder import build_graph_html
from src.integrator import integrate
from src.feedback import process_feedback
from src.report_generator import generate_report
from src.schemas import ParseStatus, DecisionAction
from src.llm_client import has_api_key

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- global state ----
textbooks: dict = {}
rag_engine = RAGEngine()
all_nodes: list = []
all_edges: list = []
decisions: list = []
integration_stats: dict = {}
feedback_history: list[tuple[str, str]] = []


def _status_table() -> pd.DataFrame:
    if not textbooks:
        return pd.DataFrame(columns=["文件名", "状态", "章节数", "总字数", "页数", "错误"])
    rows = []
    for tb in textbooks.values():
        rows.append({
            "文件名": tb.filename,
            "状态": tb.status.value,
            "章节数": len(tb.chapters),
            "总字数": tb.total_chars,
            "页数": tb.total_pages,
            "错误": tb.error if tb.status == ParseStatus.FAILED else "",
        })
    return pd.DataFrame(rows)


def _chapter_table() -> pd.DataFrame:
    rows = []
    for tb in textbooks.values():
        for ch in tb.chapters:
            rows.append({
                "教材": tb.filename,
                "章节标题": ch.title,
                "起始页": ch.page_start,
                "字数": ch.char_count,
            })
    if not rows:
        return pd.DataFrame(columns=["教材", "章节标题", "起始页", "字数"])
    return pd.DataFrame(rows)


def on_parse(files):
    global textbooks, rag_engine
    if not files:
        return _status_table(), _chapter_table(), "请先上传教材文件（PDF / MD / TXT）"

    count = 0
    for fp in files:
        if fp is None:
            continue
        dest = UPLOAD_DIR / Path(fp).name
        shutil.copy2(fp, str(dest))
        tb = parse_file(str(dest))
        textbooks[tb.filename] = tb
        count += 1

    # Rebuild RAG index
    all_chunks = chunk_all(textbooks)
    rag_engine.index(all_chunks)

    total_chapters = sum(len(tb.chapters) for tb in textbooks.values())
    total_chars = sum(tb.total_chars for tb in textbooks.values())
    done = sum(1 for tb in textbooks.values() if tb.status == ParseStatus.DONE)
    failed = sum(1 for tb in textbooks.values() if tb.status == ParseStatus.FAILED)
    msg = f"解析完成：{count} 个文件 | 成功 {done} / 失败 {failed} | {total_chapters} 个章节 | {total_chars:,} 字 | 检索后端：{rag_engine.backend}"

    return _status_table(), _chapter_table(), msg


def on_clear_files():
    global textbooks, rag_engine
    textbooks.clear()
    rag_engine = RAGEngine()
    return _status_table(), _chapter_table(), "已清空所有教材"


def on_build_graph():
    global all_nodes, all_edges
    all_nodes = []
    all_edges = []

    for tb in textbooks.values():
        if tb.status == ParseStatus.DONE:
            nodes, edges = extract_from_textbook(tb)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    if not all_nodes:
        return (
            "<p style='color:#888;text-align:center;padding:80px'>暂无知识点，请先在「教材管理」中上传并解析教材</p>",
            pd.DataFrame(columns=["名称", "类别", "教材", "章节", "定义"]),
            pd.DataFrame(columns=["源", "目标", "关系", "说明"]),
            "暂无知识点",
        )

    graph_path = build_graph_html(all_nodes, all_edges)
    if graph_path and os.path.exists(graph_path):
        graph_html = Path(graph_path).read_text(encoding="utf-8")
    else:
        graph_html = "<p style='color:red'>图谱生成失败</p>"

    node_df = pd.DataFrame([{
        "名称": n.name, "类别": n.category, "教材": n.textbook,
        "章节": n.chapter, "定义": n.definition[:120]
    } for n in all_nodes])

    edge_df = pd.DataFrame([{
        "源": e.source, "目标": e.target, "关系": e.relation_type, "说明": e.description
    } for e in all_edges])

    msg = f"图谱生成完成：{len(all_nodes)} 个节点，{len(all_edges)} 条边"
    return graph_html, node_df, edge_df, msg


def on_integrate():
    global decisions, integration_stats
    if len(textbooks) < 2:
        return (
            pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
            "需要至少 2 本已解析的教材才能进行跨教材整合",
            "",
        )
    if not all_nodes:
        return (
            pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
            "请先在「知识图谱」中构建图谱",
            "",
        )

    decisions, integration_stats = integrate(all_nodes)

    dec_rows = [{
        "决策ID": d.decision_id,
        "操作": d.action.value,
        "涉及知识点": ", ".join(d.affected_nodes),
        "结果": d.result_node,
        "理由": d.reason,
        "置信度": d.confidence,
        "状态": d.status.value,
    } for d in decisions]

    dec_df = pd.DataFrame(dec_rows) if dec_rows else pd.DataFrame(
        columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]
    )

    orig = integration_stats.get("original_chars", 0)
    integrated = integration_stats.get("integrated_chars", 0)
    ratio = integration_stats.get("compression_ratio", 0)

    stats_text = f"""### 压缩比统计

| 指标 | 数值 |
|------|------|
| 原始知识点字数 | {orig:,} |
| 整合后估算字数 | {integrated:,} |
| **压缩比** | **{ratio:.1%}** |
| 合并 | {integration_stats.get('merge_count', 0)} |
| 保留 | {integration_stats.get('keep_count', 0)} |
| 删除 | {integration_stats.get('remove_count', 0)} |
"""

    msg = f"整合完成：{len(decisions)} 条决策 | 压缩比 {ratio:.1%}"
    return dec_df, msg, stats_text


def on_ask(query):
    if not query or not query.strip():
        return "请输入问题", ""
    if not rag_engine.chunks:
        return "请先在「教材管理」中上传并解析教材，建立知识库索引后再提问。", ""

    answer, refs = rag_engine.ask(query.strip())

    ref_text = "### 引用来源\n\n"
    for i, r in enumerate(refs):
        ref_text += (
            f"**{i + 1}.** {r['教材']} / {r['章节']} / 第{r['页码']}页 "
            f"(相关度: {r['相关度']})\n\n> {r['原文片段']}\n\n"
        )

    return answer, ref_text


def on_feedback(user_input, chat_state):
    global decisions
    if not user_input or not user_input.strip():
        return chat_state, _decisions_df(), "请输入反馈指令"
    if not decisions:
        return chat_state, _decisions_df(), "暂无整合决策，请先执行跨教材整合"

    response, decisions = process_feedback(user_input.strip(), decisions)
    feedback_history.append((user_input, response))

    chat_state = chat_state or []
    chat_state.append({"role": "user", "content": user_input})
    chat_state.append({"role": "assistant", "content": response})

    return chat_state, _decisions_df(), response


def _decisions_df() -> pd.DataFrame:
    if not decisions:
        return pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"])
    return pd.DataFrame([{
        "决策ID": d.decision_id,
        "操作": d.action.value,
        "涉及知识点": ", ".join(d.affected_nodes),
        "结果": d.result_node,
        "理由": d.reason,
        "置信度": d.confidence,
        "状态": d.status.value,
    } for d in decisions])


def on_generate_report():
    report = generate_report(textbooks, all_nodes, all_edges, decisions, integration_stats)
    return report, "报告已生成并保存到 report/整合报告.md"


def on_load_example():
    """Create sample MD textbooks for demo."""
    sample_dir = Path("data/samples")
    sample_dir.mkdir(parents=True, exist_ok=True)

    sample_a = sample_dir / "医学基础_炎症与免疫.md"
    sample_a.write_text("""# 第一章 炎症的基本概念

炎症是机体对损伤因子的防御性反应，是活体组织对致炎因子所发生的一系列局部和全身性防御反应的总称。

## 1.1 炎症的临床表现

炎症的局部临床表现包括红、肿、热、痛和功能障碍。这些表现是由于局部血管扩张、通透性增高、白细胞渗出等病理过程所致。

## 1.2 炎症的分类

按病程长短可分为急性炎症和慢性炎症。
- 急性炎症：起病急骤，持续时间短，以渗出性病变为主。
- 慢性炎症：病程较长，以增生性病变为主。

# 第二章 免疫应答

免疫应答是机体识别和排除抗原性异物、维持自身稳定的全过程。包括固有免疫和适应性免疫两大类。

## 2.1 固有免疫

固有免疫又称非特异性免疫，是机体在种系发育和进化过程中形成的天然防御功能。主要特点包括：作用广泛、反应迅速、无记忆性。

## 2.2 适应性免疫

适应性免疫又称特异性免疫，是机体接触抗原后产生的针对该抗原的特异性免疫应答。具有特异性、记忆性和自我限制等特点。

# 第三章 病理生理学基础

病理生理学是研究疾病发生、发展规律和机制的科学。它探讨疾病时机体的功能代谢变化。

## 3.1 疾病概论

疾病是机体在致病因素作用下，自稳调节紊乱而发生的异常生命活动过程。包括致病因素、机体反应性和环境因素三方面。
""", encoding="utf-8")

    sample_b = sample_dir / "医学进阶_免疫与病理.md"
    sample_b.write_text("""# 第一章 免疫系统深度解析

免疫系统是机体执行免疫应答的组织系统，由免疫器官、免疫细胞和免疫分子组成。

## 1.1 免疫应答的精细调控

适应性免疫应答包括三个阶段：抗原识别阶段、淋巴细胞活化增殖阶段、效应阶段。T细胞和B细胞分别在细胞免疫和体液免疫中发挥核心作用。

## 1.2 炎症与免疫的关系

炎症反应与免疫应答密切相关。炎症是免疫系统清除病原体的重要机制，而免疫应答常常通过炎症反应来执行。

# 第二章 炎症的病理机制

炎症是机体对损伤因子的防御性反应，涉及血管反应、白细胞渗出和组织修复等多个环节。

## 2.1 炎症介质

炎症介质包括细胞源性介质（如组胺、前列腺素）和血浆源性介质（如补体系统、激肽系统）。

## 2.2 炎症的转归

炎症的转归取决于致炎因子的性质和机体状态。可能的结果包括：完全恢复、纤维化、转为慢性或扩散。
""", encoding="utf-8")

    return [str(sample_a), str(sample_b)], "样例教材已生成：医学基础_炎症与免疫.md + 医学进阶_免疫与病理.md"


# ---- Gradio UI ----
CSS = """
.status-done { color: #2ecc71; font-weight: bold; }
.status-failed { color: #e74c3c; }
.stats-box { background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 8px 0; }
footer { visibility: hidden; }
"""


def create_app():
    with gr.Blocks(title="医教精华压缩 Agent") as demo:
        gr.Markdown("# 医教精华压缩 Agent")
        gr.Markdown("通用教材知识整合智能体 · 上传教材 → 解析章节 → 知识图谱 → 跨教材整合 → RAG问答 → 教师反馈 → 整合报告")

        if not has_api_key():
            gr.Markdown("---\n⚠️ **未配置 DEEPSEEK_API_KEY**：知识抽取和 RAG 问答将使用规则兜底模式。请在 `.env` 文件中配置 `DEEPSEEK_API_KEY` 以获得完整 LLM 功能。")

        with gr.Tabs():
            # ============ Tab 1: 教材管理 ============
            with gr.Tab("教材管理"):
                gr.Markdown("### 上传教材文件（PDF / Markdown / TXT）")
                with gr.Row():
                    file_input = gr.File(
                        label="选择教材文件",
                        file_types=[".pdf", ".md", ".txt"],
                        file_count="multiple",
                    )
                with gr.Row():
                    parse_btn = gr.Button("解析教材", variant="primary", size="lg")
                    clear_btn = gr.Button("清空所有教材", variant="secondary", size="lg")
                    load_example_btn = gr.Button("加载样例教材", variant="secondary", size="lg")

                parse_msg = gr.Markdown("准备就绪，请上传教材文件")

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("#### 文件状态")
                        status_table = gr.Dataframe(
                            _status_table(),
                            label="教材处理状态",
                            interactive=False,
                            wrap=True,
                        )
                    with gr.Column(scale=1):
                        gr.Markdown("#### 章节列表")
                        chapter_table = gr.Dataframe(
                            _chapter_table(),
                            label="章节详情",
                            interactive=False,
                            wrap=True,
                        )

                parse_btn.click(
                    fn=on_parse,
                    inputs=[file_input],
                    outputs=[status_table, chapter_table, parse_msg],
                )
                clear_btn.click(
                    fn=on_clear_files,
                    inputs=[],
                    outputs=[status_table, chapter_table, parse_msg],
                )
                load_example_btn.click(
                    fn=on_load_example,
                    inputs=[],
                    outputs=[file_input, parse_msg],
                )

            # ============ Tab 2: 知识图谱 ============
            with gr.Tab("知识图谱"):
                gr.Markdown("### 交互式知识图谱")
                build_graph_btn = gr.Button("抽取知识点 / 构建图谱", variant="primary", size="lg")
                graph_msg = gr.Markdown("请先点击按钮构建图谱")

                graph_html = gr.HTML(
                    value="<p style='color:#888;text-align:center;padding:80px'>点击上方按钮生成可交互知识图谱</p>",
                    label="知识图谱（可缩放/拖拽/悬停）",
                )

                with gr.Accordion("节点列表", open=False):
                    node_table = gr.Dataframe(
                        pd.DataFrame(columns=["名称", "类别", "教材", "章节", "定义"]),
                        label="知识点节点",
                        interactive=False,
                        wrap=True,
                    )
                with gr.Accordion("边列表", open=False):
                    edge_table = gr.Dataframe(
                        pd.DataFrame(columns=["源", "目标", "关系", "说明"]),
                        label="知识点关系",
                        interactive=False,
                        wrap=True,
                    )

                build_graph_btn.click(
                    fn=on_build_graph,
                    inputs=[],
                    outputs=[graph_html, node_table, edge_table, graph_msg],
                )

            # ============ Tab 3: 跨教材整合 ============
            with gr.Tab("跨教材整合"):
                gr.Markdown("### 跨教材知识点去重与整合决策")
                integrate_btn = gr.Button("执行跨教材整合", variant="primary", size="lg")
                integrate_msg = gr.Markdown("请先构建知识图谱，然后点击执行整合")

                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("#### 整合决策表")
                        decision_table = gr.Dataframe(
                            pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
                            label="整合决策",
                            interactive=False,
                            wrap=True,
                        )
                    with gr.Column(scale=1):
                        gr.Markdown("#### 压缩统计")
                        stats_display = gr.Markdown("")

                integrate_btn.click(
                    fn=on_integrate,
                    inputs=[],
                    outputs=[decision_table, integrate_msg, stats_display],
                )

            # ============ Tab 4: RAG 问答 ============
            with gr.Tab("RAG 问答"):
                gr.Markdown("### 基于教材内容的问答（带原文引用）")
                with gr.Row():
                    with gr.Column(scale=3):
                        question_input = gr.Textbox(
                            label="输入问题",
                            placeholder="例如：炎症的定义是什么？",
                            lines=2,
                        )
                    with gr.Column(scale=1):
                        ask_btn = gr.Button("提问", variant="primary", size="lg")

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("#### 答案")
                        answer_output = gr.Markdown("等待提问...")
                    with gr.Column(scale=1):
                        gr.Markdown("#### 引用来源")
                        ref_output = gr.Markdown("")

                ask_btn.click(
                    fn=on_ask,
                    inputs=[question_input],
                    outputs=[answer_output, ref_output],
                )

            # ============ Tab 5: 教师反馈 ============
            with gr.Tab("教师反馈"):
                gr.Markdown("### 教师反馈修改整合决策")
                gr.Markdown("""
支持以下指令：
- **保留 <知识点名称>** — 将删除改为保留
- **删除 <知识点名称>** — 将保留改为删除
- **不要合并 <A> 和 <B>** — 取消合并决策
- **为什么合并 <知识点名称>** — 查看合并理由
""")
                feedback_chat = gr.Chatbot(label="反馈对话", height=300)
                with gr.Row():
                    feedback_input = gr.Textbox(
                        label="输入指令",
                        placeholder="例如：不要合并 炎症 和 炎症反应",
                        scale=3,
                    )
                    feedback_btn = gr.Button("发送", variant="primary", scale=1)

                feedback_msg = gr.Markdown("")
                gr.Markdown("#### 更新后的决策表")
                feedback_decision_table = gr.Dataframe(
                    pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
                    label="当前决策",
                    interactive=False,
                    wrap=True,
                )

                feedback_btn.click(
                    fn=on_feedback,
                    inputs=[feedback_input, feedback_chat],
                    outputs=[feedback_chat, feedback_decision_table, feedback_msg],
                )

            # ============ Tab 6: 整合报告 ============
            with gr.Tab("整合报告"):
                gr.Markdown("### 生成整合报告")
                report_btn = gr.Button("生成整合报告", variant="primary", size="lg")
                report_msg = gr.Markdown("点击按钮生成 Markdown 格式的整合报告")

                report_preview = gr.Markdown(
                    "报告将在此处预览...",
                    label="报告预览",
                )

                report_btn.click(
                    fn=on_generate_report,
                    inputs=[],
                    outputs=[report_preview, report_msg],
                )

        return demo


demo = create_app()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, css=CSS, theme=gr.themes.Soft())
