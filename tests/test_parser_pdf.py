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
    assert len(bad) == 0


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
