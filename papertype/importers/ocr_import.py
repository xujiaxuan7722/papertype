"""OCR 识图导入：RapidOCR 文字框 → 坐标归并（§4.5 四条规则）→ Line 列表。

输入可以是一张或多张图片（按给定顺序作为第 1..N 页），或扫描版 PDF（逐页渲染 150 dpi）。
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from ..models import Line

_engine = None
NUM_HEAD_RE = re.compile(r"^\s*\d{1,3}\s*[\.．、:：]?\s*$")
OPT_HEAD_RE = re.compile(r"^\s*[A-G]\s*[\.．、:：]?\s*$")
OPT_ROW_RE = re.compile(r"^\s*[A-G]\s*[\.．、]")
END_PUNCT = "。．.！!？?：:；;，,、）)”\""


def _get_engine():
    global _engine
    if _engine is None:
        import logging
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        from rapidocr import RapidOCR
        _engine = RapidOCR()
    return _engine


def render_pdf_pages(pdf_path: str | Path, out_dir: str | Path, dpi: int = 150) -> list[Path]:
    import pymupdf
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    paths = []
    for i, page in enumerate(doc, start=1):
        p = out_dir / f"page_{i:03d}.png"
        page.get_pixmap(dpi=dpi).save(str(p))
        paths.append(p)
    doc.close()
    return paths


def ocr_image(path: str | Path) -> list[dict]:
    """返回 [{text, score, x0, y0, x1, y1}]。"""
    res = _get_engine()(str(path))
    boxes = []
    if not res or not res.txts:
        return boxes
    for box, txt, score in zip(res.boxes, res.txts, res.scores):
        xs = [float(pt[0]) for pt in box]; ys = [float(pt[1]) for pt in box]
        boxes.append({"text": str(txt).strip(), "score": float(score),
                      "x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)})
    return boxes


def _rows(boxes: list[dict]) -> list[list[dict]]:
    """按纵坐标聚成行（框中心 y 差小于半个行高）。"""
    boxes = sorted(boxes, key=lambda b: ((b["y0"] + b["y1"]) / 2, b["x0"]))
    rows: list[list[dict]] = []
    for b in boxes:
        cy = (b["y0"] + b["y1"]) / 2; h = b["y1"] - b["y0"]
        if rows:
            last = rows[-1]
            lcy = sum((x["y0"] + x["y1"]) / 2 for x in last) / len(last)
            lh = max(x["y1"] - x["y0"] for x in last)
            if abs(cy - lcy) <= max(h, lh) * 0.5:
                last.append(b); continue
        rows.append([b])
    for r in rows:
        r.sort(key=lambda b: b["x0"])
    return rows


def _char_w(b: dict) -> float:
    n = max(1, len(b["text"]))
    return (b["x1"] - b["x0"]) / n


def _join_row(row: list[dict]) -> tuple[str, int]:
    """同行框归并：题号框并入；大间距且句中 → 补空位；选项行大间距 → 两个空格。"""
    text = row[0]["text"]
    blanks = 0
    is_option_row = bool(OPT_ROW_RE.match(text)) or OPT_HEAD_RE.match(text) is not None
    for prev, b in zip(row, row[1:]):
        gap = b["x0"] - prev["x1"]
        cw = max(_char_w(prev), _char_w(b), 1.0)
        if OPT_HEAD_RE.match(prev["text"]) or NUM_HEAD_RE.match(prev["text"]):
            sep = " "
        elif OPT_ROW_RE.match(b["text"]) or OPT_HEAD_RE.match(b["text"]):
            sep = "  "
            is_option_row = True
        elif gap > cw * 2 and not is_option_row and prev["text"] and prev["text"][-1] not in END_PUNCT:
            sep = "____"; blanks += 1
        elif gap > cw * 1.2:
            sep = "  "
        else:
            sep = ""
        text = text + sep + b["text"]
    return text, blanks


def extract_lines_from_images(image_paths: list[str | Path]) -> list[Line]:
    out: list[Line] = []
    for pno, path in enumerate(image_paths, start=1):
        boxes = ocr_image(path)
        for row in _rows(boxes):
            text, blanks = _join_row(row)
            if not text.strip():
                continue
            y0 = min(b["y0"] for b in row); y1 = max(b["y1"] for b in row)
            out.append(Line(text=text, page=pno, y=y0, x=row[0]["x0"], height=y1 - y0,
                            source="ocr", blanks=blanks))
        # 图片题：文字行之间的大块空白（超过 4 行高）视为图像区域
        out.extend(_gap_images(out, pno, path))
    return out


def _gap_images(lines: list[Line], pno: int, path) -> list[Line]:
    rows = [l for l in lines if l.page == pno and not l.image]
    if len(rows) < 2:
        return []
    hs = sorted(l.height for l in rows); med = hs[len(hs) // 2] or 10
    imgs = []
    for a, b in zip(rows, rows[1:]):
        gap = b.y - (a.y + a.height)
        if gap > med * 4:
            imgs.append(Line(text="", page=pno, y=a.y + a.height + med, x=a.x, height=gap - med, source="ocr", image=True))
    return imgs


def crop_image(path: str | Path, y0: float, y1: float, out_path: str | Path) -> str:
    im = Image.open(path)
    box = (0, max(0, int(y0 - 6)), im.width, min(im.height, int(y1)))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.crop(box).save(str(out_path))
    return str(out_path)
