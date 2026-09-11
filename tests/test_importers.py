"""Word / 文本 / OCR 导入器的用例。"""
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt

from papertype.importers import docx_import, ocr_import, text_import
from papertype.parser import parse_lines

FIX = Path(__file__).parent / "fixtures"


def _make_docx(path: Path):
    """自动编号题号 + 下划线格式空位 + 表格 + 分区标题。"""
    doc = Document()
    doc.add_heading("某银行校园招聘笔试模拟卷", level=1)
    doc.add_paragraph("一、单选题")
    # 用 List Number 样式产生自动编号（题号不在正文里）
    p = doc.add_paragraph("下列关于 TCP 的说法正确的是（ ）。", style="List Number")
    for o in ["A. 面向无连接", "B. 提供可靠传输", "C. 不保证顺序", "D. 无流量控制"]:
        doc.add_paragraph(o)
    p = doc.add_paragraph("属于关系型数据库的是（ ）。", style="List Number")
    doc.add_paragraph("A. MySQL  B. Redis")
    doc.add_paragraph("C. MongoDB  D. Neo4j")
    doc.add_paragraph("二、填空题")
    p = doc.add_paragraph(style="List Number")
    p.add_run("OSI 模型共分为")
    r = p.add_run("      "); r.font.underline = True
    p.add_run("层，其中第四层是")
    r = p.add_run("      "); r.font.underline = True
    p.add_run("层。")
    doc.add_paragraph("三、判断题")
    p = doc.add_paragraph("HTTP 是无状态协议。（ ）", style="List Number")
    t = doc.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "备注"; t.rows[0].cells[1].text = "本表仅用于测试"
    doc.save(str(path))


def test_docx_numbering_blanks_and_types(tmp_path):
    f = tmp_path / "t.docx"
    _make_docx(f)
    lines = docx_import.extract_lines(f, assets_dir=tmp_path / "a")
    nums = [l.number for l in lines if l.number]
    assert nums == [1, 2, 3, 4]                      # 自动编号还原
    assert any(l.text.startswith("1. 下列关于 TCP") for l in lines)
    blank_line = next(l for l in lines if "OSI" in l.text)
    assert blank_line.text.count("____") == 2 and blank_line.blanks == 2
    r = parse_lines(lines, source="docx")
    assert [q.no for q in r.questions] == [1, 2, 3, 4]
    assert r.questions[0].type == "single" and r.questions[0].options == ["面向无连接", "提供可靠传输", "不保证顺序", "无流量控制"]
    assert r.questions[1].options == ["MySQL", "Redis", "MongoDB", "Neo4j"]
    assert r.questions[2].type == "blank" and r.questions[2].blanks == 2
    assert r.questions[3].type == "judge"
    assert r.title.startswith("某银行")


def test_text_import_answers_stripped_and_inline_letter():
    text = """第一单元 综合
一、单选题
1. 甲（ B ）乙。
A. 一 B. 二
C. 三 D. 四
【答案】B。解析：因为……
2. 下列正确的有（ ）。
A. x
B. y
C. z
参考答案：AC
"""
    r = parse_lines(text_import.extract_lines(text), source="text")
    assert len(r.questions) == 2 and r.units == ["综合"]
    q1, q2 = r.questions
    assert "B" not in q1.stem.replace("（　）", "") or q1.stem == "甲（　）乙。"
    assert q1.options == ["一", "二", "三", "四"]
    assert q2.type == "multi" and q2.options == ["x", "y", "z"]
    assert "参考答案" not in (q2.stem + "".join(q2.options))


@pytest.mark.slow
def test_ocr_samples():
    r1 = parse_lines(ocr_import.extract_lines_from_images([FIX / "ocr1.jpeg"]), source="ocr")
    assert [q.no for q in r1.questions] == [1, 2, 3, 4]
    assert r1.questions[1].image and len(r1.questions[1].options) == 4
    assert r1.questions[2].blanks == 2 and r1.questions[2].options == ["形态歧义", "模式偏差", "情态误解", "形势干扰"]
    assert r1.questions[3].options[3].startswith("信息的增长")
    r2 = parse_lines(ocr_import.extract_lines_from_images([FIX / "ocr2.jpeg"]), source="ocr")
    assert len(r2.questions) == 6 and all(len(q.options) == 4 for q in r2.questions)
    assert r2.questions[4].options == ["3%", "3.3%", "4.5%", "3.8%"]
    assert r2.title == "中国建设银行笔试模拟卷" and r2.units == ["职业基础知识测试"]
