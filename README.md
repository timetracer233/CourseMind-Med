# 医教精华压缩 Agent

面向多本教材的通用知识整合智能体。系统支持上传多本教材，自动解析章节、抽取知识点、构建可交互知识图谱、跨教材去重整合，并提供带原文引用的 RAG 问答和教师反馈修正。

**医学教材优先验证，架构可迁移到其他学科。**

## 核心功能

- 多格式教材解析：PDF（PyMuPDF）、Markdown、TXT
- 中文章节识别：支持"第X章""第X节"等常见教材结构
- 知识图谱：pyvis 生成可交互图谱，支持缩放、拖拽、节点悬停
- 跨教材整合：基于名称相似度识别重复知识点，输出 merge/keep/remove 决策
- 压缩比统计：展示原始字数、整合后估算字数、压缩比
- RAG 问答：基于教材 chunk 检索回答，返回教材、章节、页码引用
- 教师反馈：支持"保留/删除/不要合并/为什么合并"四类指令修改决策
- 整合报告：生成 Markdown 格式报告

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web UI | Gradio | 5 小时最快方案 |
| LLM | DeepSeek API | 中文能力强 |
| PDF 解析 | PyMuPDF | 逐页解析，保留页码 |
| 向量化 | MiniMax embo-01 API | 构建知识库用 `type=db`，提问用 `type=query` |
| 检索兜底 | sklearn TF-IDF | MiniMax API 不可用时保证系统不中断 |
| 图谱 | pyvis | 快速生成可交互 HTML 图谱 |
| 语言 | Python 3.10+ | |

**当前版本使用快速模式**：PDF 默认只处理前 60 页或前 8 章，保证演示稳定。完整模式可通过配置调整。

## 环境要求

- Python 3.10 或以上
- DeepSeek API Key
- MiniMax API Key / Group ID（用于 embedding，可选但推荐）

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制环境变量模板：

```bash
cp .env.example .env
```

在 `.env` 中填写：

```text
DEEPSEEK_API_KEY=你的 DeepSeek API Key
MINIMAX_API_KEY=你的 MiniMax API Key
MINIMAX_GROUP_ID=你的 MiniMax Group ID
```

如不配置 MiniMax Key，RAG 检索会自动回退到本地 TF-IDF；如不配置 DeepSeek Key，知识抽取和问答生成会使用规则/原文片段兜底，仍可演示核心流程。

## 本地运行

```bash
python app.py
```

打开终端输出的本地地址（默认 `http://localhost:7860`），即可使用系统。

## 使用流程

1. 在"教材管理"中上传 PDF / Markdown / TXT 教材
2. 点击"解析教材"，查看文件状态、章节和字数
3. 点击"抽取知识点 / 构建图谱"，生成交互式知识图谱
4. 点击"执行跨教材整合"，查看 merge/keep/remove 决策和压缩比
5. 进入"RAG 问答"，输入教材相关问题，获得带引用的回答
6. 在"教师反馈"中用自然语言指令修改整合决策
7. 点击"生成整合报告"，导出 Markdown 报告

## 黄金演示路径

比赛演示推荐使用 1-2 本小型医学教材或系统内置样例，完整走通以下路径：

```
上传教材 → 解析章节 → 构建图谱 → 跨教材整合 → RAG带引用问答 → 教师反馈 → 生成报告
```

点击页面中的"加载样例教材"按钮可自动生成两本演示用 Markdown 教材（医学基础_炎症与免疫.md + 医学进阶_免疫与病理.md）。

## 部署

### 魔搭创空间（推荐）

1. 本机确认 `python app.py` 可运行
2. 推送代码到公开 GitHub 仓库
3. 在魔搭创空间创建 Gradio 应用空间
4. 上传或同步仓库代码
5. 在空间环境变量中配置 `DEEPSEEK_API_KEY`
6. 等待依赖安装和应用启动
7. 打开公网链接测试

### Gradio share 保底

如魔搭部署临时失败，可在本机修改 `app.py` 末尾：

```python
demo.launch(share=True)
```

获取临时公网链接作为保底方案。

## 仓库注意事项

不要提交教材 PDF 文件。`.gitignore` 已排除：

```text
*.pdf
data/textbooks/
data/uploads/
data/samples/
```

评审时应通过前端上传赛方教材，而不是依赖仓库内置 PDF。

## 文档

- [开发总计划](开发总计划.md)
- [开发执行手册](docs/开发执行手册.md)
- [黄金演示路径](docs/黄金演示路径.md)
- [赛题交付检查清单](docs/赛题交付检查清单.md)
- [需求分析](docs/需求分析.md)
- [系统设计](docs/系统设计.md)
- [Agent 架构说明](docs/Agent架构说明.md)
- [接口文档](docs/接口文档.md)
- [整合报告](report/整合报告.md)
