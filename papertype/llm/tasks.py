"""大模型的三种手动用法：标红题重切、整卷重切、OCR 整理（docs/最终方案 §8.5）。

统一做法：把原文文本按大题分块（≤20 题）交给模型，要求逐字抄写成「标准题库格式」，
产出回流同一个解析器。模型产出的题一律标"待核对"。
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..models import Paper, Question
from ..parser import parse_lines
from ..importers import text_import
from .client import chat

FORMAT_SPEC = """标准题库格式（严格遵守）：
- 单元用一行「第一单元 XXX」；分区用一行「一、单选题」「二、多选题」「三、填空题」「四、判断题」；
- 每题以「题号. 题干」开头，题号用原卷题号；选项每个独占一行，写成「A. 内容」「B. 内容」……；
- 填空题的空位用 ____ 表示；一段材料带多道小题时，先写「材料：」加材料原文，再写各小题；
- 图形题或选项是图片时，写「A. 」「B. 」「C. 」「D. 」四行，内容留空；
- 原卷若带答案或解析，一律不要输出；
- 逐字抄写原文，不改写、不概括、不补充；题目之间空一行；除题目外不要输出任何说明。"""

SYS = "你是试卷排版整理助手。你只做格式整理，不做任何内容创作。"


def _chunks(text: str, max_q: int = 20) -> list[str]:
    """按题号行切块，每块不超过 max_q 道题。"""
    lines = text.splitlines()
    idxs = [i for i, l in enumerate(lines) if re.match(r"^\s*\d{1,3}\s*[\.．、]", l)]
    if len(idxs) <= max_q:
        return [text]
    chunks, start = [], 0
    for k in range(max_q, len(idxs), max_q):
        cut = idxs[k]
        chunks.append("\n".join(lines[start:cut])); start = cut
    chunks.append("\n".join(lines[start:]))
    return [c for c in chunks if c.strip()]


def _ask(chunk: str, mode: str) -> str:
    task = {
        "rechunk": "把下面的试卷原文整理成标准题库格式。",
        "ocr_tidy": "下面是 OCR 识别出的试卷文本，可能有错字、断行、选项字母粘连。请只修正明显的识别错误并整理成标准题库格式，不要改写句子。",
    }[mode]
    msg = f"{task}\n\n{FORMAT_SPEC}\n\n===== 原文开始 =====\n{chunk}\n===== 原文结束 ====="
    return chat([{"role": "system", "content": SYS}, {"role": "user", "content": msg}])


def rewrite(text: str, mode: str, progress=None) -> str:
    chunks = _chunks(text)
    outs = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        futs = {ex.submit(_ask, c, mode): i for i, c in enumerate(chunks)}
        for f in futs:
            i = futs[f]
            outs[i] = f.result()
            if progress:
                progress(i + 1, len(chunks))
    return "\n\n".join(o.strip() for o in outs if o)


def raw_span_text(paper: Paper, keys: list[str]) -> str:
    """指定题目在原卷里的原始文字（pdf 文字层按坐标截取；其他来源退回解析后的题目文字）。"""
    from ..store.files import assets_dir
    src = assets_dir(paper.id) / "source.pdf"
    if paper.import_path != "pdf-text" or not src.exists():
        return questions_to_text(paper, only=keys)
    from ..importers.pdf_import import extract_lines
    lines = extract_lines(src)
    qs = paper.questions
    out = []
    for i, q in enumerate(qs):
        if q.key() not in keys or not q.page:
            continue
        nxt = qs[i + 1] if i + 1 < len(qs) else None
        end = (nxt.page, nxt.y0) if nxt and nxt.page else (10 ** 6, 0)
        start = (q.m_page, q.m_y0) if q.group and q.material is not None and q.m_page else (q.page, q.y0)
        chunk = [l.text for l in lines if not l.image and start <= (l.page, l.y) < end]
        if not chunk:
            chunk = [f"{q.no}. {q.stem}"] + [f"{chr(65 + k)}. {o}" for k, o in enumerate(q.options)]
        out.append("\n".join(chunk))
        out.append("")
    return "\n".join(out)


def questions_to_text(paper: Paper, only: list[str] | None = None) -> str:
    """把（部分）题目还原成文本，供模型重切；only 为 key 列表。"""
    out, unit = [], None
    for q in paper.questions:
        if only is not None and q.key() not in only:
            continue
        if q.unit != unit:
            unit = q.unit
            if unit:
                out.append(f"第{unit}单元 {unit}" if False else f"单元：{unit}")
        if q.material:
            out.append("材料：" + q.material)
        out.append(f"{q.no}. {q.stem}")
        for i, o in enumerate(q.options):
            out.append(f"{chr(65 + i)}. {o}")
        out.append("")
    return "\n".join(out)


def parse_model_output(text: str, source: str) -> list[Question]:
    text = re.sub(r"(?m)^\s*单元：(.+)$", r"第一单元 \1", text)
    text = re.sub(r"(?m)^\s*材料：", "", text)
    r = parse_lines(text_import.extract_lines(text), source=source)
    for q in r.questions:
        q.reviewed = False
        if "大模型产出，需人工核对" not in q.issues:
            q.issues.append("大模型产出，需人工核对")
    return r.questions
