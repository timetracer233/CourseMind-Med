from src.config import CHUNK_SIZE, CHUNK_OVERLAP
from src.schemas import Textbook, Chunk


def chunk_textbook(tb: Textbook) -> list[Chunk]:
    chunks = []
    for ch in tb.chapters:
        text = ch.text
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunk_text = text[start:end]
            chunks.append(Chunk(
                chunk_id=f"{tb.filename}_{ch.title}_{idx}",
                textbook=tb.filename,
                chapter=ch.title,
                page=ch.page_start,
                text=chunk_text,
            ))
            idx += 1
            start += CHUNK_SIZE - CHUNK_OVERLAP
            if start >= len(text):
                break
    return chunks


def chunk_all(textbooks: dict[str, Textbook]) -> list[Chunk]:
    all_chunks = []
    for tb in textbooks.values():
        all_chunks.extend(chunk_textbook(tb))
    return all_chunks
