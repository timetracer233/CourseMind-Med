# CourseMind-Med

通用教材知识整合智能体 —— 上传多本教材，自动解析章节、构建知识图谱、跨教材去重整合，提供带原文引用的 RAG 问答。

医学教材优先验证，架构可迁移到其他学科。

## 功能

| 功能 | 说明 |
|------|------|
| 多格式解析 | PDF（PyMuPDF）、Markdown、TXT；自动识别中文章节 |
| 知识图谱 | 可交互图谱，支持缩放、拖拽、悬停查看节点详情 |
| 跨教材整合 | 识别重复知识点，自动生成 merge / keep / remove 决策 |
| 压缩统计 | 显示原始字数、整合后字数、压缩比 |
| RAG 问答 | 基于教材内容回答，附教材、章节、页码引用 |
| 教师反馈 | 支持"保留 / 删除 / 不要合并 / 为什么合并"四类指令 |
| 整合报告 | 自动生成 Markdown 报告 |

## 快速开始

### 环境

- Python 3.10+
- DeepSeek API Key

### 安装

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 运行

```bash
python app.py
```

浏览器打开 `http://localhost:7860`。

点击 **"加载样例教材"** 可自动生成两份医学样例，无需准备文件即可体验完整流程。

## 使用流程

1. **教材管理** — 上传教材 → 解析 → 查看章节和字数
2. **知识图谱** — 抽取知识点 → 生成可交互图谱
3. **跨教材整合** — 执行去重 → 查看决策表和压缩比
4. **RAG 问答** — 输入问题 → 获取带来源引用的答案
5. **教师反馈** — 输入指令 → 修改整合决策
6. **整合报告** — 生成并预览 Markdown 报告

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 界面 | Gradio |
| 大语言模型 | DeepSeek API |
| 检索 | sklearn TF-IDF（本地轻量向量化） |
| PDF 解析 | PyMuPDF |
| 知识图谱 | pyvis |

## 部署

### 魔搭创空间

1. 推送代码到 GitHub
2. 在魔搭创空间创建 Gradio 应用
3. 在环境变量中配置 `DEEPSEEK_API_KEY`
4. 启动并测试公网链接

### Gradio Share（保底）

```python
# 修改 app.py 末尾
demo.launch(share=True)
```

## 注意事项

- 请勿将教材 PDF 提交到仓库（`.gitignore` 已排除 `*.pdf`）
- `.env` 文件包含 API Key，已通过 `.gitignore` 排除
- PDF 默认只处理前 60 页（快速模式），可通过 `.env` 调整

## 文档

- [开发总计划](开发总计划.md)
- [需求分析](docs/需求分析.md)
- [系统设计](docs/系统设计.md)
- [Agent 架构说明](docs/Agent架构说明.md)
- [接口文档](docs/接口文档.md)
- [黄金演示路径](docs/黄金演示路径.md)
- [赛题交付检查清单](docs/赛题交付检查清单.md)
- [开发执行手册](docs/开发执行手册.md)
- [整合报告](report/整合报告.md)
