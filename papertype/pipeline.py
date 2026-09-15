"""导入管线：文件 / 图片 / 文本 → Line → 切题 → 裁图 → 草稿试卷（docs/最终方案 §7）。"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .importers import doc_import, docx_import, ocr_import, pdf_import, text_import
from .models import Paper, Question
from .parser import parse_lines
from .store.files import assets_dir, new_id

TYPE_LABEL = {"single": "单选", "multi": "多选", "judge": "判断", "blank": "填空", "essay": "简答"}


class ImportError_(Exception):
    pass


def import_file(path: str | Path, title: str | None = None) -> Paper:
    """「导入文件」入口：docx 或有文字层的 pdf。"""
    path = Path(path)
    ext = path.suffix.lower()
    pid = new_id(_slug(path.stem))
    adir = assets_dir(pid)
    if ext in (".docx", ".doc"):
        import zipfile
        if zipfile.is_zipfile(path):
            lines = docx_import.extract_lines(path, assets_dir=adir)
            result = parse_lines(lines, source="docx")
            paper = _build(pid, title or result.title or path.stem, path.name, "docx", result, lines)
            _crops_docx(paper, adir, lines)
            _picture_option_questions(paper, has_pictures=True)
        elif doc_import.is_doc(path):
            # Word 97-2003 二进制 .doc（哪怕后缀写成 .docx）：纯 Python 读正文和自动编号，没有图片
            try:
                lines = doc_import.extract_lines(path)
            except Exception as e:
                raise ImportError_(f"这份老格式 .doc 读取失败（{e}），请在 WPS 或 Word 里「另存为」.docx 再导入。")
            result = parse_lines(lines, source="docx")
            paper = _build(pid, title or result.title or path.stem, path.name, "doc", result, lines)
            _doc_postprocess(paper)
        else:
            raise ImportError_("这份文件不是有效的 Word 文档（既不是 .docx 包也不是老版 .doc），请在 WPS 或 Word 里「另存为」.docx 再导入。")
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



def _picture_option_questions(paper: Paper, has_pictures: bool) -> None:
    """选项全是图的题（图形推理）：题干末尾只剩"（ ）"、没有选项 → 单选 + A～D 空选项按字母作答。"""
    for q in paper.questions:
        if not q.options and (q.type in ("single", "multi") or
                              (q.type == "blank" and q.blanks <= 1 and re.search(r"[（(]\s*[)）]\s*[：:。]?$", q.stem))):
            q.type = "single"
            q.options = ["", "", "", ""]
            if not (has_pictures and q.image):
                q.reviewed = False
                q.issues.append("本题的图在 Word 里是图片，老格式 .doc 拿不到；可对照原卷按字母作答，或另存为 .docx 重新导入"
                                if not has_pictures else "本题没有选项文字，按字母作答；请核对原卷")


def _doc_postprocess(paper: Paper) -> None:
    """老格式 .doc 拿不到图片：清掉看图标记；选项全是图的题给 A～D 空选项按字母作答。"""
    for q in paper.questions:
        q.image = None          # .doc 没有页面图，规则按「2/3」「°F」等字样猜的看图作答不成立
    _picture_option_questions(paper, has_pictures=False)


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
    """本题裁图的结束位置：答案段起点（若有）或下一题起点；跨页时给出下一页的截止纵坐标。"""
    end_page, end_y = q.page, 10 ** 6
    nxt = paper.questions[i + 1] if i + 1 < len(paper.questions) else None
    if nxt and nxt.page in (q.page, q.page + 1):
        end_page, end_y = nxt.page, nxt.y0
    # 解析器在遇到【答案】/ 分区标题时把 y1 记为该段起点，比下一题起点更早
    if q.end_page and q.y1 and (q.end_page, q.y1) < (end_page, end_y) and (q.end_page, q.y1) > (q.page, q.y0):
        end_page, end_y = q.end_page, q.y1
    if end_page == q.page:
        return q.page, end_y, None
    return q.page, 10 ** 6, end_y


def _crops_pdf(paper: Paper, pdf_path: Path, adir: Path) -> None:
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    heights = {i + 1: p.rect.height for i, p in enumerate(doc)}
    doc.close()
    for q in paper.questions:
        if q.group and q.m_page and (q.m_page, q.m_y0) < (q.page, q.y0):
            name = f"m_{paper.questions.index(q) + 1:03d}_{_safe(q.unit)}_{q.no}.png"
            try:
                pdf_import.render_span(pdf_path, q.m_page, q.m_y0, q.page, q.y0, adir / name)
                q.material_crop = name
            except Exception:
                q.material_crop = None
    for i, q in enumerate(paper.questions):
        if not q.page:
            continue
        page, y1, next_y1 = _span_end(paper, i, q)
        y1 = min(y1, heights.get(page, 800) * 0.93)
        # 材料题：组内第一题的裁图从材料起点开始
        y0 = q.y0
        name = f"q_{i + 1:03d}_{_safe(q.unit)}_{q.no}.png"      # 带卷内序号：题号重复也不会互相覆盖
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
        name = f"q_{i + 1:03d}_{_safe(q.unit)}_{q.no}.png"
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


def _crops_docx(paper: Paper, adir: Path, lines) -> None:
    """docx：按位置分配内嵌图片。落在本题范围内的图纵向拼成一张作 crop/image，
    材料段（组内第一题的 m_y0 到 y0 之间）的图拼成 material_crop；无主的图不分给任何题。"""
    from PIL import Image
    imgs = [(l.y, adir / l.ref) for l in lines if l.image and l.ref and (adir / l.ref).exists()]

    def stack(pics: list[Path], name: str) -> str | None:
        try:
            ims = [Image.open(p).convert("RGB") for p in pics]
            w = max(i.width for i in ims); h = sum(i.height for i in ims)
            canvas = Image.new("RGB", (w, h), "white")
            y = 0
            for im in ims:
                canvas.paste(im, (0, y)); y += im.height
            canvas.save(adir / name)
            return name
        except Exception:
            return None

    for i, q in enumerate(paper.questions):
        _, end_y, _ = _span_end(paper, i, q)
        if q.group and q.m_page and q.m_y0 < q.y0:          # 材料位置只记在组内第一题上，与 PDF 路径一致
            mats = [p for y, p in imgs if q.m_y0 <= y < q.y0]
            if mats:
                q.material_crop = stack(mats, f"m_{i + 1:03d}_{_safe(q.unit)}_{q.no}.png")
        mine = [p for y, p in imgs if q.y0 <= y < end_y]
        if mine:
            name = stack(mine, f"q_{i + 1:03d}_{_safe(q.unit)}_{q.no}.png")
            q.crop = name
            q.image = name          # Word 没有页面渲染，题内的图就是作答页要看的图
        elif q.image:
            q.image = None          # 解析器按字眼猜是图片题，但本题范围内没有图
            q.reviewed = False
            q.issues.append("Word 中本题范围内没有图片，请核对题干")


def _safe(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9一-鿿]+", "", s)[:10] or "u"
