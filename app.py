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
from src.sankey import build_sankey
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
    global textbooks, rag_engine, all_nodes, all_edges, decisions, integration_stats
    if not files:
        return _status_table(), _chapter_table(), "请先上传教材文件（PDF / MD / TXT）"

    # Clear all global state before parsing new files
    textbooks.clear()
    rag_engine = RAGEngine()
    all_nodes.clear()
    all_edges.clear()
    decisions.clear()
    integration_stats.clear()

    count = 0
    for fp in files:
        if fp is None:
            continue
        dest = UPLOAD_DIR / Path(fp).name
        shutil.copy2(fp, str(dest))
        tb = parse_file(str(dest))
        textbooks[tb.filename] = tb
        count += 1

    all_chunks = chunk_all(textbooks)
    rag_engine.index(all_chunks)

    total_chapters = sum(len(tb.chapters) for tb in textbooks.values())
    total_chars = sum(tb.total_chars for tb in textbooks.values())
    done = sum(1 for tb in textbooks.values() if tb.status == ParseStatus.DONE)
    failed = sum(1 for tb in textbooks.values() if tb.status == ParseStatus.FAILED)
    msg = f"解析完成：{count} 个文件 | 成功 {done} / 失败 {failed} | {total_chapters} 个章节 | {total_chars:,} 字"

    return _status_table(), _chapter_table(), msg


def on_clear_files():
    global textbooks, rag_engine, all_nodes, all_edges, decisions, integration_stats
    textbooks.clear()
    rag_engine = RAGEngine()
    all_nodes.clear()
    all_edges.clear()
    decisions.clear()
    integration_stats.clear()
    return _status_table(), _chapter_table(), "已清空所有教材"


def on_build_graph():
    global all_nodes, all_edges
    all_nodes = []
    all_edges = []

    # Warn if chapters are too few
    total_ch = sum(len(tb.chapters) for tb in textbooks.values())
    if total_ch <= 2:
        gr.Warning("该教材章节识别较少，图谱节点可能稀疏，建议尝试其他教材或加载样例教材。", duration=5)

    try:
        for tb in textbooks.values():
            if tb.status == ParseStatus.DONE:
                nodes, edges = extract_from_textbook(tb)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
    except Exception as e:
        err_msg = str(e)[:200]
        gr.Warning(f"处理超时或出错：{err_msg[:60]}。请尝试加载样例教材或减少章节数。", duration=5)
        return (
            f"<p style='color:#c62828;text-align:center;padding:40px'>知识抽取时出错。<br>可能原因：教材文件过大、API 超时或网络波动。<br><small>{err_msg}</small><br><br>建议：加载样例教材测试，或减少教材章节数后重试。</p>",
            pd.DataFrame(columns=["名称", "类别", "教材", "章节", "定义"]),
            pd.DataFrame(columns=["源", "目标", "关系", "说明"]),
            f"知识抽取失败：{err_msg[:80]}",
        )

    if not all_nodes:
        return (
            "<p style='color:#888;text-align:center;padding:80px'>暂无知识点，请先在左侧上传并解析教材</p>",
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
            "<p style='color:#888;text-align:center'>—</p>",
        )
    if not all_nodes:
        return (
            pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
            "请先在「知识图谱」中构建图谱",
            "",
            "<p style='color:#888;text-align:center'>—</p>",
        )

    decisions, integration_stats = integrate(all_nodes, sum(tb.total_chars for tb in textbooks.values()))

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

    stats_text = f"""| 指标 | 数值 |
|------|------|
| 原始知识点字数 | {orig:,} |
| 整合后估算字数 | {integrated:,} |
| **压缩比** | **{ratio:.1%}** |
| 合并 | {integration_stats.get('merge_count', 0)} |
| 保留 | {integration_stats.get('keep_count', 0)} |
| 删除 | {integration_stats.get('remove_count', 0)} |
"""

    sankey_html = build_sankey(all_nodes, decisions)

    msg = f"整合完成：{len(decisions)} 条决策 | 压缩比 {ratio:.1%}"
    return dec_df, msg, stats_text, sankey_html


def on_ask(query):
    if not query or not query.strip():
        return "请输入问题", ""
    if not rag_engine.chunks:
        return "请先在左侧上传并解析教材，建立知识库索引后再提问。", ""

    answer, refs = rag_engine.ask(query.strip())

    no_answer = "未找到相关信息" in answer or "未找到" in answer
    ref_text = ""
    if refs:
        ref_text = "### 检索结果\n\n" if no_answer else "### 引用来源\n\n"
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
    names = "_".join([Path(tb).stem[:15] for tb in textbooks.keys()][:3])
    fname = f"report/整合报告_{names}.md" if names else "report/整合报告.md"
    return report, f"报告已保存到 {fname}"


def on_load_example():
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

    return [str(sample_a), str(sample_b)], "样例教材已生成"


# ---- Gradio UI ----
CSS = """
footer { visibility: hidden; }
"""


def create_app():
    theme = gr.themes.Soft(primary_hue="blue")

    with gr.Blocks(title="CourseMind-Med") as demo:
        gr.Markdown("# CourseMind-Med")
        gr.Markdown("通用教材知识整合智能体 — 上传、解析、图谱、整合、问答、报告")

        if not has_api_key():
            gr.Markdown("⚠️ 未配置 DEEPSEEK_API_KEY，知识抽取和问答将使用规则兜底。请在 `.env` 中配置 API Key。")

        with gr.Row():
            # ===== LEFT SIDEBAR =====
            with gr.Column(scale=1, min_width=280):
                gr.Markdown("### 教材管理")
                file_input = gr.File(
                    label="上传教材（PDF/MD/TXT）",
                    file_types=[".pdf", ".md", ".txt"],
                    file_count="multiple",
                )
                with gr.Row():
                    parse_btn = gr.Button("解析教材", variant="primary", size="sm")
                    load_example_btn = gr.Button("加载样例", variant="secondary", size="sm")
                clear_btn = gr.Button("清空教材", variant="secondary", size="sm")
                parse_msg = gr.Markdown("准备就绪")

                gr.Markdown("#### 文件状态")
                status_table = gr.Dataframe(
                    _status_table(), label="处理状态", interactive=False, wrap=True, max_height=200,
                )
                gr.Markdown("#### 章节列表")
                chapter_table = gr.Dataframe(
                    _chapter_table(), label="章节详情", interactive=False, wrap=True, max_height=300,
                )

                parse_btn.click(fn=on_parse, inputs=[file_input], outputs=[status_table, chapter_table, parse_msg])
                clear_btn.click(fn=on_clear_files, inputs=[], outputs=[status_table, chapter_table, parse_msg])
                load_example_btn.click(fn=on_load_example, inputs=[], outputs=[file_input, parse_msg])

            # ===== RIGHT: Tabs =====
            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("知识图谱"):
                        with gr.Row():
                            build_graph_btn = gr.Button("抽取知识点 / 构建图谱", variant="primary")
                            graph_msg = gr.Markdown("点击按钮构建")
                        graph_html = gr.HTML(
                            "<p style='color:#888;text-align:center;padding:60px'>点击上方按钮生成可交互知识图谱（可缩放、拖拽、悬停查看详情）</p>",
                        )
                        with gr.Accordion("节点 / 边详情", open=False):
                            with gr.Row():
                                node_table = gr.Dataframe(
                                    pd.DataFrame(columns=["名称", "类别", "教材", "章节", "定义"]),
                                    label="节点", interactive=False, wrap=True,
                                )
                                edge_table = gr.Dataframe(
                                    pd.DataFrame(columns=["源", "目标", "关系", "说明"]),
                                    label="边", interactive=False, wrap=True,
                                )
                        build_graph_btn.click(fn=on_build_graph, inputs=[], outputs=[graph_html, node_table, edge_table, graph_msg])

                    with gr.Tab("跨教材整合"):
                        integrate_btn = gr.Button("执行跨教材整合", variant="primary")
                        integrate_msg = gr.Markdown("请先构建知识图谱")
                        with gr.Row():
                            with gr.Column(scale=2):
                                decision_table = gr.Dataframe(
                                    pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
                                    label="整合决策", interactive=False, wrap=True,
                                )
                            with gr.Column(scale=1):
                                gr.Markdown("#### 压缩统计")
                                stats_display = gr.Markdown("")
                        gr.Markdown("#### 整合流向桑基图")
                        sankey_html = gr.HTML("<p style='color:#888;text-align:center'>—</p>")
                        integrate_btn.click(fn=on_integrate, inputs=[], outputs=[decision_table, integrate_msg, stats_display, sankey_html])

                    with gr.Tab("RAG 问答"):
                        with gr.Row():
                            question_input = gr.Textbox(label="问题", placeholder="例如：炎症的定义是什么？", scale=3)
                            ask_btn = gr.Button("提问", variant="primary", scale=1)
                        with gr.Row():
                            with gr.Column():
                                gr.Markdown("#### 答案")
                                answer_output = gr.Markdown("等待提问...")
                            with gr.Column():
                                gr.Markdown("#### 引用来源")
                                ref_output = gr.Markdown("")
                        ask_btn.click(fn=on_ask, inputs=[question_input], outputs=[answer_output, ref_output])

                    with gr.Tab("教师反馈"):
                        gr.Markdown("支持指令：**保留 / 删除 / 不要合并 / 为什么合并** + 知识点名称")
                        feedback_chat = gr.Chatbot(label="反馈对话", height=250)
                        with gr.Row():
                            feedback_input = gr.Textbox(label="指令", placeholder="例如：不要合并 炎症 和 炎症反应", scale=3)
                            feedback_btn = gr.Button("发送", variant="primary", scale=1)
                        feedback_msg = gr.Markdown("")
                        feedback_decision_table = gr.Dataframe(
                            pd.DataFrame(columns=["决策ID", "操作", "涉及知识点", "结果", "理由", "置信度", "状态"]),
                            label="当前决策", interactive=False, wrap=True,
                        )
                        feedback_btn.click(fn=on_feedback, inputs=[feedback_input, feedback_chat], outputs=[feedback_chat, feedback_decision_table, feedback_msg])

                    with gr.Tab("整合报告"):
                        report_btn = gr.Button("生成整合报告", variant="primary")
                        report_msg = gr.Markdown("点击按钮生成报告")
                        report_preview = gr.Markdown("报告将在此处预览...")
                        report_btn.click(fn=on_generate_report, inputs=[], outputs=[report_preview, report_msg])
                        with gr.Accordion("问题反馈 / 联系我们", open=False):
                            gr.Markdown("如有问题或建议，请通过 GitHub Issues 反馈：[github.com/timetracer233/CourseMind-Med/issues](https://github.com/timetracer233/CourseMind-Med/issues)")
                            fb_input = gr.Textbox(label="快速反馈", placeholder="输入建议或遇到的问题...", lines=2)
                            fb_btn = gr.Button("提交反馈", variant="secondary", size="sm")
                            fb_btn.click(fn=lambda _: gr.Info("感谢反馈！", duration=3), inputs=[fb_input], outputs=[])

        return demo


demo = create_app()

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=3, max_size=10).launch(
        server_name="0.0.0.0", server_port=7860, share=True,
        css=CSS, theme=gr.themes.Soft(primary_hue="blue"),
    )
