import re
import fitz
from pathlib import Path
from src.schemas import Textbook, Chapter, ParseStatus
from src.config import FAST_MODE_MAX_PAGES, FAST_MODE_MAX_CHAPTERS

CH_RE = re.compile(
    r"(第[一二三四五六七八九十百零\d]+[章节篇])"
    r"|(Chapter\s+\d+)"
    r"|(^\d+[\.、]\s*.+)",
    re.MULTILINE,
)


def _detect_chapters(text: str, page_map: list[tuple[int, str]]) -> list[Chapter]:
    """Split text into chapters using regex. Falls back to pseudo-chapters."""
    matches = list(CH_RE.finditer(text))
    chapters: list[Chapter] = []

    if len(matches) >= 1:
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            title = m.group(0).strip()
            page = _find_page(start, page_map)
            chapters.append(Chapter(title=title, page_start=page, page_end=page, char_count=len(body), text=body))
    else:
        # fallback: single default chapter
        chapters.append(Chapter(title="默认章节", page_start=1, page_end=len(page_map), char_count=len(text), text=text))

    if len(chapters) > FAST_MODE_MAX_CHAPTERS:
        chapters = chapters[:FAST_MODE_MAX_CHAPTERS]

    return chapters


def _find_page(char_pos: int, page_map: list[tuple[int, str]]) -> int:
    for pg, ptext in page_map:
        if char_pos < len(ptext):
            return pg
        char_pos -= len(ptext)
    return page_map[-1][0] if page_map else 1


def parse_pdf(filepath: str) -> Textbook:
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        doc = fitz.open(filepath)
        tb.total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
        page_map: list[tuple[int, str]] = []
        full_text = ""
        for i in range(tb.total_pages):
            page_text = doc[i].get_text()
            page_map.append((i + 1, page_text))
            full_text += page_text
        doc.close()
        tb.chapters = _detect_chapters(full_text, page_map)
        tb.total_chars = sum(c.char_count for c in tb.chapters)
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def parse_markdown(filepath: str) -> Textbook:
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        text = Path(filepath).read_text(encoding="utf-8")
        # split by ## headings
        parts = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
        chapters = []
        page = 1
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            title = lines[0].lstrip("#").strip()
            body = lines[1] if len(lines) > 1 else ""
            chapters.append(Chapter(title=title, page_start=page, page_end=page, char_count=len(part), text=part))
            page += 1
        if not chapters:
            chapters.append(Chapter(title="默认章节", page_start=1, page_end=1, char_count=len(text), text=text))
        tb.chapters = chapters[:FAST_MODE_MAX_CHAPTERS]
        tb.total_chars = sum(c.char_count for c in tb.chapters)
        tb.total_pages = len(tb.chapters)
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def parse_txt(filepath: str) -> Textbook:
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        text = Path(filepath).read_text(encoding="utf-8")
        page_map = [(1, text)]
        tb.chapters = _detect_chapters(text, page_map)
        tb.total_chars = sum(c.char_count for c in tb.chapters)
        tb.total_pages = 1
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def parse_file(filepath: str) -> Textbook:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(filepath)
    elif ext == ".md":
        return parse_markdown(filepath)
    elif ext == ".txt":
        return parse_txt(filepath)
    else:
        tb = Textbook(filename=Path(filepath).name, status=ParseStatus.FAILED)
        tb.error = f"不支持的文件格式: {ext}"
        return tb
