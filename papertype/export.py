"""汇总表导出 Excel（列：单元、题号、题型、我的答案、标记）。"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from .pipeline import TYPE_LABEL


def summary_rows(paper, answers: dict, marks: list) -> tuple[list[dict], list[str]]:
    rows, unanswered = [], []
    markset = set(marks or [])
    for q in paper.questions:
        key = q.key()
        a = answers.get(key)
        text = format_answer(q, a)
        if not text:
            unanswered.append(f"{q.unit + '-' if q.unit else ''}{q.no}")
        rows.append({"unit": q.unit, "no": q.no, "type": TYPE_LABEL.get(q.type, q.type),
                     "answer": text, "marked": key in markset, "key": key})
    return rows, unanswered


def format_answer(q, a) -> str:
    if a is None:
        return ""
    if q.type in ("single", "multi", "judge"):
        if isinstance(a, list):
            return " ".join(sorted(x for x in a if x))
        return str(a).strip()
    if q.type == "blank":
        vals = a if isinstance(a, list) else [a]
        vals = [str(v).strip() for v in vals]
        return "；".join(vals) if any(vals) else ""
    return str(a).strip()


def to_xlsx(paper, rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "答案汇总"
    ws.append(["单元", "题号", "题型", "我的答案", "标记"])
    for r in rows:
        ws.append([r["unit"], r["no"], r["type"], r["answer"] or "未作答", "★" if r["marked"] else ""])
    ws.column_dimensions["A"].width = 16; ws.column_dimensions["D"].width = 30
    bio = BytesIO(); wb.save(bio)
    return bio.getvalue()


def paper_to_xlsx(paper) -> bytes:
    """试卷导出（可在 Excel 里改后回导）：单元、题号、题型、题干、A-G。"""
    wb = Workbook(); ws = wb.active; ws.title = "试卷"
    ws.append(["单元", "题号", "题型", "题干", "A", "B", "C", "D", "E", "F", "G", "空数"])
    for q in paper.questions:
        ws.append([q.unit, q.no, TYPE_LABEL.get(q.type, q.type), q.stem] + (q.options + [""] * 7)[:7] + [q.blanks])
    bio = BytesIO(); wb.save(bio)
    return bio.getvalue()
