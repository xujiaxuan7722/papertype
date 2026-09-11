"""两份真题的回归用例（docs/最终方案 §11 阶段 2 验收）。"""
from collections import Counter
from pathlib import Path

import pytest

from papertype.importers.pdf_import import extract_lines, has_text_layer
from papertype.parser import parse_lines

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def boc():
    return parse_lines(extract_lines(FIX / "boc.pdf"), source="pdf")


@pytest.fixture(scope="module")
def icbc():
    return parse_lines(extract_lines(FIX / "icbc.pdf"), source="pdf")


def test_text_layer():
    assert has_text_layer(FIX / "boc.pdf") and has_text_layer(FIX / "icbc.pdf")


def test_boc_counts(boc):
    per = Counter(q.unit for q in boc.questions)
    assert per == {"英语": 55, "行政能力测试": 58, "综合知识": 55}
    assert len(boc.questions) == 168
    assert boc.units == ["英语", "行政能力测试", "综合知识"]


def test_boc_no_watermark(boc):
    for q in boc.questions:
        assert "海哥" not in q.stem and all("海哥" not in o for o in q.options)


def test_boc_review_rate(boc):
    bad = [q for q in boc.questions if not q.reviewed]
    assert len(bad) <= len(boc.questions) * 0.1
    assert [(q.unit, q.no) for q in bad] == [("行政能力测试", 45)]     # 公式对象题：私有编码字符，改为看图作答并提示核对
    q45 = bad[0]
    assert q45.image and q45.options == ["1111", "111", "2222", "222"]


def test_boc_options_and_types(boc):
    by = {(q.unit, q.no): q for q in boc.questions}
    q = by[("英语", 2)]
    assert q.options == ["scrutiny", "exams", "management", "exploration"]
    assert by[("英语", 31)].options == ["productivity", "diversity", "activeness", "possibility"]
    assert by[("行政能力测试", 14)].image and len(by[("行政能力测试", 14)].options) == 4
    assert by[("综合知识", 4)].options[0].startswith("李师傅的机会成本是1/3") and by[("综合知识", 4)].options[0].endswith("本比张师傅小")
    assert by[("综合知识", 40)].type == "multi" and len(by[("综合知识", 40)].options) == 4
    assert by[("综合知识", 1)].type == "single"


def test_boc_material_groups(boc):
    groups = Counter(q.group for q in boc.questions if q.group)
    assert len(groups) >= 6 and all(v == 5 for v in groups.values())
    first = next(q for q in boc.questions if q.group)
    assert first.material and len(first.material) > 100


def test_icbc_counts_and_answers_stripped(icbc):
    assert len(icbc.questions) == 80
    assert [q.no for q in icbc.questions] == list(range(1, 81))
    for q in icbc.questions:
        assert "【答案】" not in q.stem and "故本题" not in q.stem
        for o in q.options:
            assert "【答案】" not in o and "故本题" not in o and "正确答案" not in o
    bad = [q for q in icbc.questions if not q.reviewed]
    assert len(bad) <= 8


def test_icbc_types_and_images(icbc):
    by = {q.no: q for q in icbc.questions}
    assert by[61].type == "multi" and not by[61].stem.startswith("【")
    assert by[24].image and by[35].image and len(by[35].options) == 4
    assert by[53].options[0].startswith("不足1%")
    assert by[51].group and by[51].material and by[52].group == by[51].group
    assert Counter(len(q.options) for q in icbc.questions)[4] >= 78


def test_icbc_superscript_and_fractions(icbc):
    by = {q.no: q for q in icbc.questions}
    assert "2000²-1999²+1" in by[40].stem and "1000²-999²+1" in by[40].stem
    assert by[37].stem.startswith("300 6/11") and "57 57/99" in by[37].stem and "15 15/99" in by[37].stem
    assert by[36].options == ["1/2", "1/28", "1/9", "1/7"]


def test_icbc_span_ends_before_answer(icbc):
    by = {q.no: q for q in icbc.questions}
    q = by[35]                       # 图形题：裁图终点应是【答案】段起点，而不是下一题
    assert q.end_page == q.page and q.y0 < q.y1 < 520
    assert by[51].material and by[51].m_page == 22 and by[51].m_y0 > 500


def test_icbc_material_groups(icbc):
    groups = {}
    for q in icbc.questions:
        if q.group:
            groups.setdefault(q.group, []).append(q.no)
    assert list(groups.values()) == [[51, 52, 53, 54, 55], [56, 57, 58, 59, 60]]
    by = {q.no: q for q in icbc.questions}
    assert by[56].m_page == 26 and not by[56].material      # 纯图片材料：无文字，但有裁图位置


def test_boc_chart_material_text(boc):
    q = next(q for q in boc.questions if q.unit == "行政能力测试" and q.no == 54)
    assert q.material.startswith("根据资料，回答54—58 题。")
    assert "2018 年全年研究与试验发展" in q.material and "专利申请数  432.3  16.9" in q.material
    assert "24000  25" not in q.material and "\n0\n" not in q.material     # 图表坐标不进材料文字
    assert q.m_page == 23
