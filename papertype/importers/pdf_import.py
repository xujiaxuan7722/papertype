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


SUP_MAP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
NUMERIC_RE = re.compile(r"^\s*\d+\s*$")


def _span_atom(sp: dict) -> dict:
    x0, y0, x1, y1 = sp["bbox"]
    return {"text": sp["text"], "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": sp["size"],
            "sup": bool(sp["flags"] & 1), "used": False}


def _fold_fractions(atoms: list[dict], body: float) -> None:
    """分子在上、分母在下、横向重叠的两个纯数字块 → 一个基线块 "分子/分母"。只在公式行内调用。"""
    nums = [a for a in atoms if NUMERIC_RE.match(a["text"]) and not a["sup"]]
    for up in nums:
        if up["used"]:
            continue
        for dn in nums:
            if dn is up or dn["used"]:
                continue
            ox = min(up["x1"], dn["x1"]) - max(up["x0"], dn["x0"])
            if ox <= 0 or ox < 0.5 * min(up["x1"] - up["x0"], dn["x1"] - dn["x0"]):
                continue
            up_cy = (up["y0"] + up["y1"]) / 2; dn_cy = (dn["y0"] + dn["y1"]) / 2
            if not (body * 0.9 <= dn_cy - up_cy <= body * 1.9):
                continue
            cy = (up["y0"] + dn["y1"]) / 2
            up.update(text=f"{up['text'].strip()}/{dn['text'].strip()}", x0=min(up["x0"], dn["x0"]), x1=max(up["x1"], dn["x1"]),
                      y0=cy - body * 0.6, y1=cy + body * 0.6, size=body, frac=True)
            dn["used"] = True
            break


def _row_text(row: list[dict], body: float) -> str:
    row = [a for a in row if not a["used"] and a["text"]]
    row.sort(key=lambda a: a["x0"])
    out = ""
    last_x1 = None
    for a in row:
        t = a["text"]
        if a["sup"]:
            out += t.strip().translate(SUP_MAP)
            last_x1 = a["x1"]
            continue
        if last_x1 is not None:
            gap = a["x0"] - last_x1
            if a.get("frac") or (out and out[-1].isdigit() and t[:1].isdigit() and gap > 0.5):
                out += " "
            elif gap > body * 1.5:
                out += "  "
            elif gap > body * 0.35 and not out.endswith(" ") and not t.startswith(" "):
                out += " "
        out += t
        last_x1 = a["x1"]
    return re.sub(r"[ \t]{3,}", "  ", out).strip()


def _line_text(spans: list[dict]) -> str:
    """普通行：按原顺序拼接，上标转成上标字符（带上标标记的，或字号小且明显抬高的数字块）。"""
    body = max(sp["size"] for sp in spans)
    base = max(sp["bbox"][3] for sp in spans if sp["text"].strip()) if any(sp["text"].strip() for sp in spans) else 0
    out = ""
    for sp in spans:
        t = sp["text"]
        raised = sp["size"] < body * 0.8 and (base - sp["bbox"][3]) > sp["size"] * 0.25 and NUMERIC_RE.match(t or "x")
        out += t.strip().translate(SUP_MAP) if (sp["flags"] & 1 or raised) else t
    return out


def _raw_lines(doc: pymupdf.Document):
    """逐页取水平文字行（丢旋转行）。行内字块高低不齐的是公式行，收集后折叠分数再重组。"""
    pages = []
    for pno, page in enumerate(doc, start=1):
        rows: list[Line] = []
        formula_pool: list[dict] = []
        sizes = []
        d = page.get_text("dict")
        for b in d["blocks"]:
            if b["type"] == 1:
                x0, y0, x1, y1 = b["bbox"]
                if (x1 - x0) * (y1 - y0) > 400:
                    rows.append(Line(text="", page=pno, y=y0, x=x0, height=y1 - y0, source="pdf", image=True))
                continue
            for l in b["lines"]:
                if tuple(round(v, 2) for v in l["dir"]) != (1.0, 0.0):
                    continue
                spans = [sp for sp in l["spans"] if sp["text"]]
                if not spans:
                    continue
                body_spans = [sp for sp in spans if not (sp["flags"] & 1) and sp["text"].strip()]
                sizes.extend(sp["size"] for sp in body_spans)
                bottoms = [sp["bbox"][3] for sp in body_spans]; tops = [sp["bbox"][1] for sp in body_spans]
                msize = max(sp["size"] for sp in body_spans) if body_spans else 10
                mixed = body_spans and max(max(bottoms) - min(bottoms), max(tops) - min(tops)) > msize * 0.5
                if mixed:
                    formula_pool.extend(_span_atom(sp) for sp in spans)
                    continue
                text = _line_text(spans).strip()
                if not text:
                    continue
                size = max(sp["size"] for sp in spans)
                x0, y0, x1, y1 = l["bbox"]
                rows.append(Line(text=text, page=pno, y=y0, x=x0, height=y1 - y0, source="pdf", is_heading=size >= 13))
        if formula_pool:
            body = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
            for band in _bands(formula_pool):
                _fold_fractions(band, body)
                text = _row_text(band, body)
                if not text:
                    continue
                live = [a for a in band if not a["used"]]
                x0 = min(a["x0"] for a in live); y0 = min(a["y0"] for a in live); y1 = max(a["y1"] for a in live)
                rows.append(Line(text=text, page=pno, y=y0, x=x0, height=y1 - y0, source="pdf"))
        try:
            for dr in page.get_drawings():
                r = dr.get("rect")
                if r and r.width > 40 and r.height > 40:
                    rows.append(Line(text="", page=pno, y=r.y0, x=r.x0, height=r.height, source="pdf", image=True))
        except Exception:
            pass
        pages.append((page.rect.height, rows))
    return pages


def _bands(atoms: list[dict]) -> list[list[dict]]:
    """公式字块按纵向重叠合并成带（同一视觉行）。"""
    atoms = sorted(atoms, key=lambda a: a["y0"])
    bands: list[list[dict]] = []
    for a in atoms:
        if bands:
            cur = bands[-1]
            top = min(x["y0"] for x in cur); bot = max(x["y1"] for x in cur)
            if a["y0"] < bot - 2 and a["y1"] > top + 2:
                cur.append(a); continue
        bands.append([a])
    return bands


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


def _fold_line_fractions(rows: list[Line]) -> list[Line]:
    """独立成行的单个数字上下叠放（大分数）：上行/下行 → 一行 "分子/分母"，放在两者中线上。"""
    nums = [r for r in rows if not r.image and NUMERIC_RE.match(r.text)]
    used: set[int] = set()
    for up in nums:
        if id(up) in used:
            continue
        for dn in nums:
            if dn is up or id(dn) in used:
                continue
            ox = min(up.x + _approx_width(up), dn.x + _approx_width(dn)) - max(up.x, dn.x)
            if ox <= 0:
                continue
            dist = (dn.y + dn.height / 2) - (up.y + up.height / 2)
            if not (up.height * 0.9 <= dist <= up.height * 2.0):
                continue
            cy = (up.y + dn.y + dn.height) / 2
            up.text = f"{up.text.strip()}/{dn.text.strip()}"
            up.y, up.height = cy - up.height / 2, up.height
            up.x = min(up.x, dn.x)
            used.add(id(dn))
            break
    return [r for r in rows if id(r) not in used]


def _merge_same_row(rows: list[Line]) -> list[Line]:
    """同一视觉行（垂直中心接近）的多个片段按横坐标合并成一行（处理 A/B 同行选项与被水印切开的行）。"""
    rows = _fold_line_fractions(rows)
    rows = sorted(rows, key=lambda r: (r.y + r.height / 2, r.x))
    clusters: list[list[Line]] = []
    for r in rows:
        if r.image:
            clusters.append([r]); continue
        if clusters and not clusters[-1][0].image:
            last = clusters[-1]
            cy = sum(x.y + x.height / 2 for x in last) / len(last)
            tol = max(2.0, min(min(x.height for x in last), r.height) * 0.5)
            if abs((r.y + r.height / 2) - cy) <= tol:
                last.append(r); continue
        clusters.append([r])
    merged: list[Line] = []
    for c in clusters:
        if len(c) == 1:
            merged.append(c[0]); continue
        c.sort(key=lambda x: x.x)
        first = c[0]
        text = first.text
        x_end = first.x + _approx_width(first)
        for r in c[1:]:
            gap = r.x - x_end
            sep = "  " if gap > first.height * 1.5 else (" " if gap > first.height * 0.3 else "")
            text = (text + sep + r.text).strip()
            x_end = r.x + _approx_width(r)
        merged.append(Line(text=text, page=first.page, y=min(x.y for x in c), x=first.x,
                           height=max(x.y + x.height for x in c) - min(x.y for x in c), source="pdf",
                           is_heading=any(x.is_heading for x in c), blanks=sum(x.blanks for x in c)))
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
                near_edge = r.y + r.height < height * 0.1 or r.y > height * 0.9
                if _img_key(r) not in repeated and not near_edge:
                    kept.append(r)
                continue
            t = _norm(r.text)
            if t in repeated:
                continue
            if len(t) <= 3 and any(t in rep for rep in repeated if not rep.startswith("IMG@")):
                continue
            if PUNCT_ONLY_RE.match(t) and len(t) >= 6:
                continue                       # 分隔线之类的纯符号行
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


def render_span(pdf_path: str | Path, page0: int, y0: float, page1: int, y1: float, out_path: str | Path,
                dpi: int = 110, max_pages: int = 4) -> str:
    """从 page0 的 y0 到 page1 的 y1 之间的全部内容纵向拼成一张图（材料跨页）。"""
    from PIL import Image
    doc = pymupdf.open(str(pdf_path))
    parts = []
    for pno in range(page0, min(page1, page0 + max_pages - 1) + 1):
        pg = doc[pno - 1]
        top = y0 - 4 if pno == page0 else pg.rect.height * 0.07
        bot = y1 if pno == page1 else pg.rect.height * 0.93
        if bot - top < 8:
            continue
        pix = pg.get_pixmap(clip=pymupdf.Rect(0, max(0, top), pg.rect.width, min(pg.rect.height, bot)), dpi=dpi)
        parts.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    doc.close()
    if not parts:
        raise ValueError("empty span")
    w = max(p.width for p in parts); h = sum(p.height for p in parts)
    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for p in parts:
        canvas.paste(p, (0, y)); y += p.height
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out_path))
    return str(out_path)


def page_height(pdf_path: str | Path, page: int) -> float:
    doc = pymupdf.open(str(pdf_path))
    h = doc[page - 1].rect.height
    doc.close()
    return h
