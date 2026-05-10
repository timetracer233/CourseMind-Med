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


def _parse_pdf_by_font(filepath: str) -> Textbook:
    """Parse PDF using font-size heuristics to detect real chapter headings."""
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        doc = fitz.open(filepath)
        total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
        tb.total_pages = total_pages

        # Collect all text blocks with font info
        blocks_info: list[dict] = []
        for page_num in range(total_pages):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            for blk in blocks:
                if blk["type"] != 0:
                    continue
                for line in blk["lines"]:
                    text = "".join([span["text"] for span in line["spans"]])
                    if not text.strip():
                        continue
                    # Get the max font size in this line
                    sizes = [span["size"] for span in line["spans"] if span["text"].strip()]
                    avg_size = sum(sizes) / len(sizes) if sizes else 0
                    max_size = max(sizes) if sizes else 0
                    blocks_info.append({
                        "page": page_num + 1,
                        "text": text,
                        "size": max_size,
                        "avg_size": avg_size,
                    })

        doc.close()

        if not blocks_info:
            tb.status = ParseStatus.DONE
            return tb

        # Find body font size (median of all text)
        all_sizes = sorted([b["avg_size"] for b in blocks_info])
        if not all_sizes:
            tb.status = ParseStatus.DONE
            return tb

        body_size = all_sizes[len(all_sizes) // 2]

        # A heading is: font larger than body AND relatively short text
        heading_threshold = body_size * 1.15  # 15% larger than body
        chapter_blocks = []
        for b in blocks_info:
            text = b["text"].strip()
            if not text:
                continue
            # Heading signals: larger font or matches 第X章 pattern
            is_larger = b["avg_size"] >= heading_threshold
            is_ch_pattern = bool(re.match(r"(第[一二三四五六七八九十百零\d]+[章节篇])", text))
            is_chapter_pattern = bool(re.match(r"(Chapter\s+\d+)", text, re.IGNORECASE))
            if is_larger or is_ch_pattern or is_chapter_pattern:
                chapter_blocks.append(b)

        # If font analysis found nothing, fall back to regex
        if not chapter_blocks:
            return _parse_pdf_by_regex(filepath, blocks_info)

        # Build chapters from detected headings
        chapters = []
        for i, cb in enumerate(chapter_blocks):
            # Find where this chapter's text ends (next chapter heading or EOF)
            next_page = chapter_blocks[i + 1]["page"] if i + 1 < len(chapter_blocks) else total_pages + 1
            # Collect text for this chapter
            body = []
            for b in blocks_info:
                if b["page"] >= cb["page"] and b["page"] < next_page:
                    body.append(b["text"])
            body_text = "\n".join(body)
            chapters.append(Chapter(
                title=cb["text"].strip()[:80],
                page_start=cb["page"],
                page_end=min(next_page, total_pages),
                char_count=len(body_text),
                text=body_text,
            ))

        if len(chapters) > FAST_MODE_MAX_CHAPTERS:
            chapters = chapters[:FAST_MODE_MAX_CHAPTERS]

        tb.chapters = chapters
        tb.total_chars = sum(c.char_count for c in chapters)
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def _parse_pdf_by_regex(filepath: str, blocks_info: list[dict] | None = None) -> Textbook:
    """Legacy regex-based PDF chapter detection (fallback)."""
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        if blocks_info is None:
            doc = fitz.open(filepath)
            total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
            blocks_info = []
            for page_num in range(total_pages):
                page = doc[page_num]
                blocks = page.get_text("dict")["blocks"]
                for blk in blocks:
                    if blk["type"] != 0:
                        continue
                    for line in blk["lines"]:
                        text = "".join([span["text"] for span in line["spans"]])
                        if text.strip():
                            blocks_info.append({"page": page_num + 1, "text": text, "size": 0, "avg_size": 0})
            doc.close()
            tb.total_pages = total_pages
        else:
            tb.total_pages = max((b["page"] for b in blocks_info), default=1)

        full_text = "\n".join([b["text"] for b in blocks_info])
        matches = list(CH_RE.finditer(full_text))
        chapters = []

        if len(matches) >= 2:
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
                body = full_text[start:end].strip()
                title = m.group(0).strip()
                # Find page for this position
                char_pos = 0
                page = 1
                for b in blocks_info:
                    if char_pos + len(b["text"]) > start:
                        page = b["page"]
                        break
                    char_pos += len(b["text"])
                chapters.append(Chapter(title=title, page_start=page, page_end=page, char_count=len(body), text=body))
        else:
            # No chapter markers found: create pseudo-chapters by page ranges
            texts_by_page: dict[int, list[str]] = {}
            for b in blocks_info:
                p = b["page"]
                if p not in texts_by_page:
                    texts_by_page[p] = []
                texts_by_page[p].append(b["text"])
            pages_per_chapter = max(1, len(texts_by_page) // min(8, len(texts_by_page)))
            page_nums = sorted(texts_by_page.keys())
            for i in range(0, len(page_nums), pages_per_chapter):
                chunk_pages = page_nums[i:i + pages_per_chapter]
                body = "\n".join(["\n".join(texts_by_page[p]) for p in chunk_pages])
                chapters.append(Chapter(
                    title=f"第{chunk_pages[0]}-{chunk_pages[-1]}页",
                    page_start=chunk_pages[0],
                    page_end=chunk_pages[-1],
                    char_count=len(body),
                    text=body,
                ))

        if len(chapters) > FAST_MODE_MAX_CHAPTERS:
            chapters = chapters[:FAST_MODE_MAX_CHAPTERS]

        tb.chapters = chapters
        tb.total_chars = sum(c.char_count for c in chapters)
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def parse_pdf(filepath: str) -> Textbook:
    return _parse_pdf_by_font(filepath)


def parse_markdown(filepath: str) -> Textbook:
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        text = Path(filepath).read_text(encoding="utf-8")
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
        matches = list(CH_RE.finditer(text))
        chapters = []
        if len(matches) >= 1:
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                body = text[start:end].strip()
                chapters.append(Chapter(title=m.group(0).strip(), page_start=1, page_end=1, char_count=len(body), text=body))
        else:
            chapters.append(Chapter(title="默认章节", page_start=1, page_end=1, char_count=len(text), text=text))
        tb.chapters = chapters[:FAST_MODE_MAX_CHAPTERS]
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
