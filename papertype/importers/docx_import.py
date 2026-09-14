"""Word 导入：还原自动编号题号、下划线空位，抽出内嵌图片，表格按行展开。"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from ..models import Line

BLANK_RUN_RE = re.compile(r"[_＿]{2,}")


def _num_format(doc, num_id: str, ilvl: str) -> str:
    """查编号格式（decimal / chineseCounting ...）；查不到按 decimal。"""
    try:
        numbering = doc.part.numbering_part.element
    except Exception:
        return "decimal"
    for num in numbering.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            abs_id = num.find(qn("w:abstractNumId")).get(qn("w:val"))
            for a in numbering.findall(qn("w:abstractNum")):
                if a.get(qn("w:abstractNumId")) == abs_id:
                    for lvl in a.findall(qn("w:lvl")):
                        if lvl.get(qn("w:ilvl")) == ilvl:
                            fmt = lvl.find(qn("w:numFmt"))
                            return fmt.get(qn("w:val")) if fmt is not None else "decimal"
    return "decimal"


def _style_numpr(style):
    seen = set()
    while style is not None and id(style) not in seen:
        seen.add(id(style))
        try:
            ppr = style.element.pPr
            if ppr is not None and ppr.numPr is not None:
                return ppr.numPr
        except Exception:
            pass
        style = style.base_style
    return None


def _para_text(p) -> tuple[str, int]:
    """拼接 run 文本；带下划线且内容为空白 / 很短的 run 还原成 ____。"""
    parts = []
    blanks = 0
    for r in p.runs:
        t = r.text
        u = r.font.underline
        if u and (not t.strip() or len(t.strip()) <= 1):
            parts.append("____"); blanks += 1
        elif u and re.fullmatch(r"[\s_＿]+", t):
            parts.append("____"); blanks += 1
        else:
            parts.append(t)
    text = "".join(parts)
    text = re.sub(r"(____)(\s*____)+", "____", text) if blanks else text
    blanks = max(blanks, len(BLANK_RUN_RE.findall(text)))
    # 全角 / 半角括号里的一串空格：作答空位（仅计数，不改写）
    return text.strip(), blanks


def extract_lines(docx_path: str | Path, assets_dir: str | Path | None = None) -> list[Line]:
    doc = Document(str(docx_path))
    counters: dict[tuple[str, str], int] = defaultdict(int)
    out: list[Line] = []
    y = 0.0
    rels = doc.part.rels
    img_seq = 0

    def emit_images(p_elm):
        nonlocal img_seq, y
        blips = p_elm.findall(".//" + qn("a:blip"))
        for b in blips:
            rid = b.get(qn("r:embed"))
            if not rid or rid not in rels:
                continue
            part = rels[rid].target_part
            ext = Path(part.partname).suffix or ".png"
            img_seq += 1
            ref = None
            if assets_dir:
                Path(assets_dir).mkdir(parents=True, exist_ok=True)
                ref = f"docx_img_{img_seq}{ext}"
                (Path(assets_dir) / ref).write_bytes(part.blob)
            out.append(Line(text="", page=1, y=y, x=10.0, height=1.0, source="docx", image=True, ref=ref))
            y += 1

    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            p = Paragraph(child, doc)
            text, blanks = _para_text(p)
            number = None
            numpr = child.find(".//" + qn("w:numPr"))
            if numpr is None:
                numpr = _style_numpr(p.style)      # 编号定义在样式（如 List Number）里
            if numpr is not None:
                num_id_el = numpr.find(qn("w:numId")); ilvl_el = numpr.find(qn("w:ilvl"))
                if num_id_el is not None and num_id_el.get(qn("w:val")) not in (None, "0"):
                    num_id = num_id_el.get(qn("w:val"))
                    ilvl = ilvl_el.get(qn("w:val")) if ilvl_el is not None else "0"
                    fmt = _num_format(doc, num_id, ilvl)
                    if fmt in ("decimal", "decimalZero", "none") or fmt.startswith("decimal"):
                        counters[(num_id, ilvl)] += 1
                        number = counters[(num_id, ilvl)]
                        if fmt != "none" and text and not re.match(r"^\d+\s*[\.．、]", text):
                            text = f"{number}. {text}"
            emit_images(child)
            if not text:
                continue
            style = (p.style.name or "") if p.style is not None else ""
            heading = style.lower().startswith("heading") or style.startswith("标题") or style == "Title"
            # 段内软回车（Shift+Enter，<w:br/>）：WPS/老 .doc 常把整题甚至多题放在一个段落里，按行拆开
            pieces = [t.strip() for t in text.split("\n") if t.strip()]
            for k, t in enumerate(pieces):
                out.append(Line(text=t, page=1, y=y, x=10.0, height=1.0, source="docx",
                                number=number if k == 0 else None,
                                blanks=blanks if len(pieces) == 1 else len(BLANK_RUN_RE.findall(t)),
                                is_heading=heading and k == 0))
                y += 1
        elif tag == "tbl":
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            t = Table(child, doc)
            for tr in t._tbl.tr_lst:
                cells = []
                for tc in tr.tc_lst:
                    txt = "\n".join(Paragraph(pe, None).text.strip() for pe in tc.p_lst if Paragraph(pe, None).text.strip())
                    cells.append("^" if tc.vMerge == "continue" else txt)      # 纵向合并的续格
                    cells.extend([">"] * (max(tc.grid_span or 1, 1) - 1))       # 横向合并占的格
                if any(c not in ("", ">", "^") for c in cells):
                    text = "  ".join(c.replace("\n", " ") for c in cells if c not in ("", ">", "^"))
                    out.append(Line(text=text, page=1, y=y, x=10.0, height=1.0, source="docx", cells=cells))
                    y += 1
    return out
