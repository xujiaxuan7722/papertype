"""大模型任务的本地部分：分块、模型产出回流解析（不联网）。"""
from papertype.llm import tasks
from papertype.models import Paper, Question


def test_chunks_by_question_count():
    text = "\n".join(f"{i}. 题{i}\nA. a\nB. b" for i in range(1, 46))
    chunks = tasks._chunks(text, max_q=20)
    assert len(chunks) == 3
    assert chunks[0].startswith("1. 题1") and chunks[1].startswith("21. 题21") and chunks[2].startswith("41. 题41")


def test_model_output_reparsed_and_flagged():
    out = """第一单元 行测
一、单选题

1. 曲艺：相声：娱乐性
A. 社交：微信：即时性
B. 新闻：评论：客观性
C. 医院：医生：权威性
D. 司机：驾驶：可靠性

2. 从所给的四个选项中，选择最合适的一个填入问号处：
A. 
B. 
C. 
D. 

三、填空题

3. 法治和礼治发生在两种不同的社会____中，容易引起____。
"""
    qs = tasks.parse_model_output(out, "ocr")
    assert [q.no for q in qs] == [1, 2, 3]
    assert all(not q.reviewed and "大模型产出" in " ".join(q.issues) for q in qs)
    assert qs[0].options[1] == "新闻：评论：客观性" and qs[0].unit == "行测"
    assert qs[1].image and qs[1].options == ["", "", "", ""]
    assert qs[2].type == "blank" and qs[2].blanks == 2


def test_questions_to_text_roundtrip():
    p = Paper(id="x", title="t", source="s", import_path="text", created_at="", units=["A"],
              questions=[Question(unit="A", no=1, stem="题干", options=["甲", "乙"]),
                         Question(unit="A", no=2, stem="第二题", options=[], type="blank", blanks=1)])
    text = tasks.questions_to_text(p, only=["A|2"])
    assert "2. 第二题" in text and "1. 题干" not in text


def test_raw_span_text_from_pdf(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("PAPERTYPE_DATA", str(tmp_path))
    from papertype import pipeline
    p = pipeline.import_file("tests/fixtures/icbc.pdf")
    q37 = next(q for q in p.questions if q.no == 37)
    text = tasks.raw_span_text(p, [q37.key()])
    assert text.startswith("37.300 6/11") and "A.54" in text and "【答案】" in text   # 原始文字含答案，交给模型时由格式说明剔除
    q51 = next(q for q in p.questions if q.no == 51)
    t51 = tasks.raw_span_text(p, [q51.key()])
    assert "2019 年全年全国居民人均可支配收入" in t51 and "51.基于资料" in t51
