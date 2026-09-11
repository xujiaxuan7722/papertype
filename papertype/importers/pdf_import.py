"""PDF（文字层）导入器：过滤水印与页眉页脚，输出带坐标的 Line 列表，并提供按题裁图。

实测依据见 docs/最终方案 §4.3：
- 旋转水印：文字行方向不是 (1, 0) 的一律丢弃。
- 横排水印 / 页眉页脚：同一字符串在超过一半页面出现的丢弃（短于 4 字的纯标点串不参与统计）。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from ..models import Line

PAGE_NO_RE = re.compile(r"^(第\s*\d+\s*页(\s*共\s*\d+\s*页)?|[—\-–]\s*\d+\s*[—\-–]?|\d{1,3})$")
PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$")
BLANK_RUN_RE = re.compile(r"[_＿]{2,}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _raw_lines(doc: pymupdf.Document):
    """逐页取水平文字行（丢旋转行），附带字号与坐标；同时给出图片 / 大块矢量图占位。"""
    pages = []
    for pno, page in enumerate(doc, start=1):
        rows = []
        d = page.get_text("dict")
        for b in d["blocks"]:
            if b["type"] == 1:  # 位图
                x0, y0, x1, y1 = b["bbox"]
                if (x1 - x0) * (y1 - y0) > 400:
                    rows.append(Line(text="", page=pno, y=y0, x=x0, height=y1 - y0, source="pdf", image=True))
                continue
            for l in b["lines"]:
                if tuple(round(v, 2) for v in l["dir"]) != (1.0, 0.0):
                    continue
                text = "".join(s["text"] for s in l["spans"]).strip()
                if not text:
                    continue
                size = max(s["size"] for s in l["spans"])
                x0, y0, x1, y1 = l["bbox"]
                rows.append(Line(text=text, page=pno, y=y0, x=x0, height=y1 - y0, source="pdf",
                                 is_heading=size >= 13))
        # 大块矢量图（图形推理常见）
        try:
            for dr in page.get_drawings():
                r = dr.get("rect")
                if r and r.width > 40 and r.height > 40:
                    rows.append(Line(text="", page=pno, y=r.y0, x=r.x0, height=r.height, source="pdf", image=True))
        except Exception:
            pass
        pages.append((page.rect.height, rows))
    return pages


def _repeated_strings(pages, threshold=0.5, min_pages=3) -> set[str]:
    n = len(pages)
    if n < min_pages:
        return set()
    counter: Counter = Counter()
    for _, rows in pages:
        seen = set()
        for r in rows:
            if r.image:
                seen.add(_img_key(r))
            elif r.text:
                t = _norm(r.text)
                if len(t) >= 4 and not PUNCT_ONLY_RE.match(t):
                    seen.add(t)
        for t in seen:
            counter[t] += 1
    return {t for t, c in counter.items() if c >= max(min_pages, n * threshold)}


def _img_key(r: Line) -> str:
    return f"IMG@{round(r.x / 5)}:{round(r.y / 5)}:{round(r.height / 5)}"


def _merge_same_row(rows: list[Line]) -> list[Line]:
    """同一纵坐标上的多个片段按横坐标合并成一行（处理 A/B 同行选项与被水印切开的行）。"""
    rows = sorted(rows, key=lambda r: (round(r.y), r.x))
    merged: list[Line] = []
    for r in rows:
        if merged and not r.image and not merged[-1].image:
            last = merged[-1]
            tol = max(2.0, min(last.height, r.height) * 0.5)
            if abs(r.y - last.y) <= tol:
                gap = r.x - (last.x + _approx_width(last))
                sep = "  " if gap > last.height * 1.5 else ""
                last.text = (last.text + sep + r.text).strip()
                last.height = max(last.height, r.height)
                continue
        merged.append(r)
    return merged


def _approx_width(line: Line) -> float:
    # 粗略估计：中文字符按行高计宽，ASCII 按半宽
    w = 0.0
    for ch in line.text:
        w += line.height if ord(ch) > 0x2E80 else line.height * 0.55
    return w


def extract_lines(pdf_path: str | Path) -> list[Line]:
    doc = pymupdf.open(str(pdf_path))
    pages = _raw_lines(doc)
    repeated = _repeated_strings(pages)
    out: list[Line] = []
    for height, rows in pages:
        kept = []
        for r in rows:
            if r.image:
                if _img_key(r) not in repeated:
                    kept.append(r)
                continue
            t = _norm(r.text)
            if t in repeated:
                continue
            # 水印碎片：与某个重复串互为子串且位于页面边缘外，或极短且是重复串的片段
            if len(t) <= 3 and any(t in rep for rep in repeated):
                continue
            edge = r.y < height * 0.07 or r.y > height * 0.92
            if edge and PAGE_NO_RE.match(r.text.strip()):
                continue
            r.blanks = len(BLANK_RUN_RE.findall(r.text))
            kept.append(r)
        out.extend(_merge_same_row(kept))
    doc.close()
    return out


def has_text_layer(pdf_path: str | Path, sample_pages: int = 3) -> bool:
    doc = pymupdf.open(str(pdf_path))
    chars = 0
    for i, page in enumerate(doc):
        if i >= sample_pages:
            break
        chars += len(page.get_text().strip())
    doc.close()
    return chars > 50


def render_clip(pdf_path: str | Path, page: int, y0: float, y1: float, out_path: str | Path,
                dpi: int = 120, next_page_y1: float | None = None) -> str:
    """把某页 y0..y1 区域渲染成图；若 next_page_y1 给出，则把下一页顶部到该处的区域拼在下面。"""
    from PIL import Image
    doc = pymupdf.open(str(pdf_path))
    pg = doc[page - 1]
    rect = pymupdf.Rect(0, max(0, y0 - 4), pg.rect.width, min(pg.rect.height, y1))
    pix = pg.get_pixmap(clip=rect, dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if next_page_y1 is not None and page < len(doc):
        pg2 = doc[page]
        rect2 = pymupdf.Rect(0, pg2.rect.height * 0.07, pg2.rect.width, min(pg2.rect.height, next_page_y1))
        pix2 = pg2.get_pixmap(clip=rect2, dpi=dpi)
        img2 = Image.frombytes("RGB", (pix2.width, pix2.height), pix2.samples)
        canvas = Image.new("RGB", (max(img.width, img2.width), img.height + img2.height), "white")
        canvas.paste(img, (0, 0)); canvas.paste(img2, (0, img.height))
        img = canvas
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    doc.close()
    return str(out_path)


def page_height(pdf_path: str | Path, page: int) -> float:
    doc = pymupdf.open(str(pdf_path))
    h = doc[page - 1].rect.height
    doc.close()
    return h
