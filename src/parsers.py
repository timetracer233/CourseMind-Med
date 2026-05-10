import re
import fitz
from pathlib import Path
from src.schemas import Textbook, Chapter, ParseStatus
from src.config import FAST_MODE_MAX_PAGES, FAST_MODE_MAX_CHAPTERS

# Chapter-like patterns in TOC and body
CH_HEADING_RE = re.compile(
    r"(第[一二三四五六七八九十百零\d]+[章节篇])"
    r"|(Chapter\s+\d+)"
    r"|(^[一二三四五六七八九十]+[、．.])"
    r"|(^\d+[\.、]\s*[^\d])",
    re.MULTILINE,
)


def _find_toc(doc: fitz.Document, max_toc_pages: int = 10) -> tuple[int, int]:
    """Search for TOC pages. Returns (start_page, end_page) or (0, 0) if not found."""
    toc_keywords = ["目录", "目次", "CONTENTS"]
    for pn in range(min(max_toc_pages, len(doc))):
        text = doc[pn].get_text()
        for kw in toc_keywords:
            if kw in text:
                # Collect TOC pages (usually spans 2-4 pages after the keyword)
                toc_start = pn
                toc_end = pn
                for next_pn in range(pn + 1, min(pn + 5, len(doc))):
                    next_text = doc[next_pn].get_text()
                    # TOC pages have many chapter-like patterns or dots for page numbers
                    if len(next_text) > 50 and (CH_HEADING_RE.search(next_text) or "…" in next_text or ".." in next_text):
                        toc_end = next_pn
                    else:
                        break
                return toc_start, toc_end
    return 0, 0


def _extract_toc_titles(doc: fitz.Document, toc_start: int, toc_end: int) -> list[str]:
    """Extract chapter titles from TOC pages."""
    titles = []
    for pn in range(toc_start, toc_end + 1):
        text = doc[pn].get_text()
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = CH_HEADING_RE.match(line)
            if m:
                # Clean up: remove trailing dots, page numbers, extra spaces
                title = re.sub(r"[\s…\.]{2,}\d+$", "", line).strip()
                title = re.sub(r"\s+", " ", title)
                if len(title) >= 3 and len(title) <= 80:
                    titles.append(title)
    return titles


def _parse_pdf_by_toc(filepath: str) -> Textbook:
    """Primary: detect TOC → extract chapter titles → locate boundaries in body."""
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        doc = fitz.open(filepath)
        total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
        tb.total_pages = total_pages

        # Step 1: Find TOC and extract chapter titles
        toc_start, toc_end = _find_toc(doc)
        toc_titles = _extract_toc_titles(doc, toc_start, toc_end) if toc_start > 0 else []

        if len(toc_titles) < 2:
            doc.close()
            return _parse_pdf_by_font_fallback(filepath)

        # Step 2: Search body text for TOC title occurrences to find chapter pages
        chapter_pages: list[tuple[str, int]] = []
        for title in toc_titles:
            # Search for the title in the document (after TOC)
            search_key = title[:12]  # First 12 chars is enough to identify
            for pn in range(toc_end + 1, total_pages):
                page_text = doc[pn].get_text()
                if search_key in page_text:
                    chapter_pages.append((title, pn + 1))
                    break
            else:
                # Title not found by substring — try regex
                chapter_pages.append((title, 0))

        # Filter out titles that couldn't be located
        located = [(t, p) for t, p in chapter_pages if p > 0]
        if len(located) < 2:
            doc.close()
            return _parse_pdf_by_font_fallback(filepath)

        # Step 3: Build chapters with boundaries
        chapters = []
        for i, (title, page) in enumerate(located):
            next_page = located[i + 1][1] if i + 1 < len(located) else total_pages + 1
            # Collect text for this chapter
            body_parts = []
            for pn in range(page - 1, min(next_page - 1, total_pages)):
                body_parts.append(doc[pn].get_text())
            body = "\n".join(body_parts)
            chapters.append(Chapter(
                title=title,
                page_start=page,
                page_end=min(next_page - 1, total_pages),
                char_count=len(body),
                text=body,
            ))

        doc.close()

        if len(chapters) > FAST_MODE_MAX_CHAPTERS:
            chapters = chapters[:FAST_MODE_MAX_CHAPTERS]

        tb.chapters = chapters
        tb.total_chars = sum(c.char_count for c in chapters)
        tb.status = ParseStatus.DONE
    except Exception as e:
        tb.status = ParseStatus.FAILED
        tb.error = str(e)
    return tb


def _parse_pdf_by_font_fallback(filepath: str) -> Textbook:
    """Fallback: font-size heuristics for chapter detection."""
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        doc = fitz.open(filepath)
        total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
        tb.total_pages = total_pages

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
                    sizes = [span["size"] for span in line["spans"] if span["text"].strip()]
                    avg_size = sum(sizes) / len(sizes) if sizes else 0
                    max_size = max(sizes) if sizes else 0
                    blocks_info.append({
                        "page": page_num + 1, "text": text,
                        "size": max_size, "avg_size": avg_size,
                    })

        doc.close()

        if not blocks_info:
            tb.status = ParseStatus.DONE
            return tb

        all_sizes = sorted([b["avg_size"] for b in blocks_info])
        if not all_sizes:
            tb.status = ParseStatus.DONE
            return tb

        body_size = all_sizes[len(all_sizes) // 2]
        heading_threshold = body_size * 1.15

        chapter_blocks = []
        for b in blocks_info:
            text = b["text"].strip()
            if not text:
                continue
            is_larger = b["avg_size"] >= heading_threshold
            is_ch = bool(re.match(r"(第[一二三四五六七八九十百零\d]+[章节篇])", text))
            is_chapter = bool(re.match(r"(Chapter\s+\d+)", text, re.IGNORECASE))
            if is_larger or is_ch or is_chapter:
                chapter_blocks.append(b)

        if len(chapter_blocks) < 2:
            return _parse_pdf_by_page_chunks(filepath, blocks_info)

        chapters = []
        for i, cb in enumerate(chapter_blocks):
            npg = chapter_blocks[i + 1]["page"] if i + 1 < len(chapter_blocks) else total_pages + 1
            body = []
            for b in blocks_info:
                if b["page"] >= cb["page"] and b["page"] < npg:
                    body.append(b["text"])
            body_text = "\n".join(body)
            chapters.append(Chapter(
                title=cb["text"].strip()[:80],
                page_start=cb["page"],
                page_end=min(npg, total_pages),
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


def _parse_pdf_by_page_chunks(filepath: str, blocks_info: list[dict] | None = None) -> Textbook:
    """Last resort: chunk by page ranges."""
    filename = Path(filepath).name
    tb = Textbook(filename=filename, status=ParseStatus.PARSING)
    try:
        if blocks_info is None:
            doc = fitz.open(filepath)
            total_pages = min(len(doc), FAST_MODE_MAX_PAGES)
            blocks_info = []
            for page_num in range(total_pages):
                for blk in doc[page_num].get_text("dict")["blocks"]:
                    if blk["type"] != 0:
                        continue
                    for line in blk["lines"]:
                        text = "".join([span["text"] for span in line["spans"]])
                        if text.strip():
                            blocks_info.append({"page": page_num + 1, "text": text})
            doc.close()
            tb.total_pages = total_pages
        else:
            tb.total_pages = max((b["page"] for b in blocks_info), default=1)

        texts_by_page: dict[int, list[str]] = {}
        for b in blocks_info:
            p = b["page"]
            if p not in texts_by_page:
                texts_by_page[p] = []
            texts_by_page[p].append(b["text"])

        chapters = []
        pages_per = max(1, len(texts_by_page) // min(8, len(texts_by_page)))
        page_nums = sorted(texts_by_page.keys())
        for i in range(0, len(page_nums), pages_per):
            chunk_pages = page_nums[i:i + pages_per]
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
    return _parse_pdf_by_toc(filepath)


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
        matches = list(CH_HEADING_RE.finditer(text))
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
