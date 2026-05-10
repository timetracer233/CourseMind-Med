import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.schemas import Chunk
from src.llm_client import chat, has_api_key
from src.config import TOP_K


class RAGEngine:
    """Lightweight TF-IDF retrieval engine (hackathon fast mode)."""

    def __init__(self):
        self.chunks: list[Chunk] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self.backend = "empty"

    def index(self, chunks: list[Chunk]):
        self.chunks = chunks
        if not chunks:
            self.vectorizer = None
            self.matrix = None
            self.backend = "empty"
            return
        self.vectorizer = TfidfVectorizer(max_features=5000, analyzer="char_wb", ngram_range=(1, 3))
        self.matrix = self.vectorizer.fit_transform([c.text for c in chunks])
        self.backend = "tfidf"

    def search(self, query: str) -> list[tuple[Chunk, float]]:
        if self.vectorizer is None or self.matrix is None:
            return []
        q_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self.matrix).flatten()
        top_indices = np.argsort(sims)[::-1][:TOP_K]
        return [(self.chunks[i], float(sims[i])) for i in top_indices if sims[i] > 0]

    @staticmethod
    def build_prompt(query: str, results: list[tuple[Chunk, float]]) -> str:
        contexts = []
        for i, (chunk, score) in enumerate(results):
            contexts.append(
                f"[来源{i + 1}] 教材:{chunk.textbook} 章节:{chunk.chapter} 页码:{chunk.page} 相关度:{score:.2f}\n{chunk.text}"
            )
        ctx_text = "\n\n".join(contexts)
        return f"""你是一个医学教材知识助手。请只基于以下教材原文回答问题。如果上下文中找不到答案，请明确说"当前知识库中未找到相关信息"。不要使用上下文之外的知识。回答请用中文。

教材内容：
{ctx_text}

问题：{query}

请回答并在末尾附上来源引用（教材、章节、页码）。"""

    def ask(self, query: str) -> tuple[str, list[dict]]:
        results = self.search(query)
        if not results:
            return "请先上传并解析教材，建立知识库索引后再提问。", []

        refs = [
            {"教材": c.textbook, "章节": c.chapter, "页码": c.page, "相关度": f"{s:.3f}", "原文片段": c.text[:200]}
            for c, s in results
        ]

        if not has_api_key():
            top_chunk = results[0][0]
            fallback = f"（未配置 DeepSeek API Key，显示最相关原文）\n\n{top_chunk.text}\n\n---\n来源: {top_chunk.textbook} / {top_chunk.chapter} / 第{top_chunk.page}页"
            return fallback, refs

        prompt = self.build_prompt(query, results)
        answer = chat([{"role": "user", "content": prompt}])
        if not answer:
            top_chunk = results[0][0]
            answer = f"（DeepSeek 调用失败，显示最相关原文）\n\n{top_chunk.text}\n\n---\n来源: {top_chunk.textbook} / {top_chunk.chapter} / 第{top_chunk.page}页"
        return answer, refs
