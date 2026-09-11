"""导入管线：文件 / 图片 / 文本 → Line → 切题 → 裁图 → 草稿试卷（docs/最终方案 §7）。"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .importers import docx_import, ocr_import, pdf_import, text_import
from .models import Paper, Question
from .parser import parse_lines
from .store.files import assets_dir, new_id, save_paper

TYPE_LABEL = {"single": "单选", "multi": "多选", "judge": "判断", "blank": "填空", "essay": "简答"}


class ImportError_(Exception):
    pass


def import_file(path: str | Path, title: str | None = None) -> Paper:
    """「导入文件」入口：docx 或有文字层的 pdf。"""
    path = Path(path)
    ext = path.suffix.lower()
    pid = new_id(_slug(path.stem))
    adir = assets_dir(pid)
    if ext == ".docx":
        lines = docx_import.extract_lines(path, assets_dir=adir)
        result = parse_lines(lines, source="docx")
        paper = _build(pid, title or result.title or path.stem, path.name, "docx", result, lines)
        _crops_docx(paper, adir)
    elif ext == ".pdf":
        if not pdf_import.has_text_layer(path):
            raise ImportError_("这份 PDF 没有文字层，请改用「OCR 识图」入口导入。")
        lines = pdf_import.extract_lines(path)
        result = parse_lines(lines, source="pdf")
        paper = _build(pid, title or result.title or path.stem, path.name, "pdf-text", result, lines)
        shutil.copy(path, adir / "source.pdf")
        _crops_pdf(paper, adir / "source.pdf", adir)
    else:
        raise ImportError_(f"不支持的文件类型：{ext}。「导入文件」只收 .docx 和 .pdf，图片请走「OCR 识图」。")
    return paper


def import_ocr(paths: list[str | Path], title: str | None = None) -> Paper:
    """「OCR 识图」入口：jpg / png（多张按顺序）或扫描版 pdf。"""
    paths = [Path(p) for p in paths]
    if not paths:
        raise ImportError_("没有收到图片。")
    pid = new_id(_slug(paths[0].stem))
    adir = assets_dir(pid)
    pages: list[Path] = []
    for p in paths:
        if p.suffix.lower() == ".pdf":
            pages.extend(ocr_import.render_pdf_pages(p, adir / "pages"))
        else:
            (adir / "pages").mkdir(parents=True, exist_ok=True)
            dst = adir / "pages" / f"page_{len(pages) + 1:03d}{p.suffix.lower()}"
            shutil.copy(p, dst)
            pages.append(dst)
    lines = ocr_import.extract_lines_from_images(pages)
    result = parse_lines(lines, source="ocr")
    paper = _build(pid, title or result.title or paths[0].stem, ", ".join(p.name for p in paths), "ocr", result, lines)
    _crops_images(paper, pages, adir)
    return paper


def import_text(text: str, title: str | None = None) -> Paper:
    """「粘贴文本」入口。"""
    if not text.strip():
        raise ImportError_("文本为空。")
    lines = text_import.extract_lines(text)
    result = parse_lines(lines, source="text")
    pid = new_id("text")
    return _build(pid, title or result.title or "粘贴的试卷", "粘贴文本", "text", result, lines)


def reparse_text(paper: Paper, text: str) -> Paper:
    """大模型整理 / 重切后的标准格式文本回流：同一解析器，保留试卷 id 与来源。"""
    result = parse_lines(text_import.extract_lines(text), source=paper.import_path if paper.import_path != "text" else "text")
    new = _build(paper.id, paper.title, paper.source, paper.import_path, result)
    new.raw_text, new.created_at = paper.raw_text, paper.created_at
    # 沿用旧题的裁图（按 单元+题号 对上的）
    old = {q.key(): q for q in paper.questions}
    for q in new.questions:
        o = old.get(q.key())
        if o:
            q.crop, q.image = o.crop, (o.image if q.image else None)
            q.page, q.y0, q.end_page, q.y1 = o.page, o.y0, o.end_page, o.y1
    return new


def stats(paper: Paper) -> dict:
    qs = paper.questions
    return {"count": len(qs), "to_review": sum(1 for q in qs if not q.reviewed),
            "with_image": sum(1 for q in qs if q.image), "units": paper.units,
            "types": {TYPE_LABEL[t]: sum(1 for q in qs if q.type == t) for t in TYPE_LABEL if any(q.type == t for q in qs)}}


# ---- 内部 ----

def _slug(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "", s)[:12] or "paper"


def _build(pid: str, title: str, source: str, import_path: str, result, lines=None) -> Paper:
    raw = "\n".join(l.text for l in lines if not l.image) if lines else ""
    return Paper(id=pid, title=title.strip()[:80], source=source, import_path=import_path,
                 created_at=time.strftime("%Y-%m-%d %H:%M:%S"), units=result.units, questions=result.questions,
                 raw_text=raw)


def _span_end(paper: Paper, i: int, q: Question) -> tuple[int, float, float | None]:
    """本题裁图的结束位置：下一题起点（同页）或本页页尾 + 下一页顶部到下一题起点。"""
    nxt = paper.questions[i + 1] if i + 1 < len(paper.questions) else None
    if nxt and nxt.page == q.page:
        return q.page, nxt.y0, None
    if nxt and nxt.page == q.page + 1:
        return q.page, 10 ** 6, nxt.y0
    return q.page, 10 ** 6, None


def _crops_pdf(paper: Paper, pdf_path: Path, adir: Path) -> None:
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    heights = {i + 1: p.rect.height for i, p in enumerate(doc)}
    doc.close()
    for i, q in enumerate(paper.questions):
        if not q.page:
            continue
        page, y1, next_y1 = _span_end(paper, i, q)
        y1 = min(y1, heights.get(page, 800) * 0.93)
        # 材料题：组内第一题的裁图从材料起点开始
        y0 = q.y0
        name = f"q_{_safe(q.unit)}_{q.no}.png"
        try:
            pdf_import.render_clip(pdf_path, page, y0, y1, adir / name, next_page_y1=next_y1)
            q.crop = name
            if q.image:
                q.image = name
        except Exception:
            q.crop = None


def _crops_images(paper: Paper, pages: list[Path], adir: Path) -> None:
    from PIL import Image
    sizes = {i + 1: Image.open(p).size for i, p in enumerate(pages)}
    for i, q in enumerate(paper.questions):
        if not q.page or q.page > len(pages):
            continue
        page, y1, next_y1 = _span_end(paper, i, q)
        y1 = min(y1, sizes[page][1])
        name = f"q_{_safe(q.unit)}_{q.no}.png"
        try:
            ocr_import.crop_image(pages[page - 1], q.y0, y1, adir / name)
            if next_y1 is not None and page < len(pages):
                _stack(adir / name, pages[page], next_y1)
            q.crop = name
            if q.image:
                q.image = name
        except Exception:
            q.crop = None


def _stack(base: Path, next_page: Path, next_y1: float) -> None:
    from PIL import Image
    a = Image.open(base); b = Image.open(next_page)
    b = b.crop((0, 0, b.width, min(b.height, int(next_y1))))
    canvas = Image.new("RGB", (max(a.width, b.width), a.height + b.height), "white")
    canvas.paste(a, (0, 0)); canvas.paste(b, (0, a.height))
    canvas.save(base)


def _crops_docx(paper: Paper, adir: Path) -> None:
    """docx：把落在本题范围内的内嵌图片纵向拼成一张。"""
    from PIL import Image
    imgs = sorted(adir.glob("docx_img_*"))
    if not imgs:
        return
    # 图片按出现顺序对应段落序号：docx 导入器里图片 Line 的 y 与段落序号同一坐标轴
    # 这里简化：按题目顺序把图片分配到"上一道题"
    from .importers.docx_import import extract_lines  # noqa
    # 无法从 Question 反查图片序号时，退回：有 image 标记的题依次领取图片
    pool = list(imgs)
    for q in paper.questions:
        if q.image and pool:
            pics = [pool.pop(0)]
            name = f"q_{_safe(q.unit)}_{q.no}.png"
            ims = [Image.open(p).convert("RGB") for p in pics]
            w = max(i.width for i in ims); h = sum(i.height for i in ims)
            canvas = Image.new("RGB", (w, h), "white")
            y = 0
            for im in ims:
                canvas.paste(im, (0, y)); y += im.height
            canvas.save(adir / name)
            q.image = name; q.crop = name


def _safe(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9一-鿿]+", "", s)[:10] or "u"
