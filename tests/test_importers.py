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


def test_numbering_restart_and_table_rows():
    text = """数量关系（3）
1. 甲题
A. a
B. b
2. 乙题
A. a
B. b
3. 丙题
A. a
B. b
资料分析（2）
请回答1～2题。
一、按经济类型分组
1.国有单位  43.32  -6.43  41.28  -6.29
2.城镇集体单位  30.71  -1.30  29.02  -0.99
1.2016 年第3 季末国有单位有在岗人员（）人。
A. 1
B. 2
2.下列说法正确的是（）。
A. x
B. y
"""
    from papertype.importers import text_import
    r = parse_lines(text_import.extract_lines(text), source="text")
    assert [(q.unit, q.no) for q in r.questions] == [("数量关系（3）", 1), ("数量关系（3）", 2), ("数量关系（3）", 3), ("资料分析（2）", 1), ("资料分析（2）", 2)]
    assert r.questions[3].group and "国有单位  43.32" in r.questions[3].material


def test_docx_images_assigned_by_position(tmp_path, monkeypatch):
    """图片按出现位置归题：题 1 一张、题 2 没有、单元标题下的图不分给任何题、题 3 两张拼成一张。"""
    from PIL import Image
    from papertype import pipeline

    monkeypatch.setenv("PAPERTYPE_DATA", str(tmp_path / "data"))

    def pic(name, h):
        p = tmp_path / name
        Image.new("RGB", (80, h), "black").save(p)
        return str(p)

    doc = Document()
    doc.add_paragraph("一、单选题")
    doc.add_paragraph("1. 如图，下列说法正确的是（ ）。")
    doc.add_picture(pic("a.png", 60))
    for o in ["A. 甲", "B. 乙", "C. 丙", "D. 丁"]:
        doc.add_paragraph(o)
    doc.add_paragraph("2. 下列属于关系型数据库的是（ ）。")
    doc.add_paragraph("A. MySQL  B. Redis")
    doc.add_paragraph("C. MongoDB  D. Neo4j")
    doc.add_paragraph("二、判断题")
    doc.add_picture(pic("banner.png", 30))      # 单元标题下的装饰图，不属于任何题
    doc.add_paragraph("3. 图中两个图形面积相等。（ ）")
    doc.add_picture(pic("b.png", 40))
    doc.add_picture(pic("c.png", 50))
    f = tmp_path / "pic.docx"
    doc.save(str(f))

    paper = pipeline.import_file(f)
    q1, q2, q3 = paper.questions
    adir = tmp_path / "data" / "assets" / paper.id
    assert q1.image and Image.open(adir / q1.image).size == (80, 60)
    assert q2.image is None and q2.crop is None
    assert q3.image and Image.open(adir / q3.image).size == (80, 90)   # 两张纵向拼接
    assert q1.image != q3.image


def test_docx_chart_picture_becomes_group_material_image(tmp_path, monkeypatch):
    """资料分析：材料提示语之后的图表图片 → 组内第一题的 material_crop（只生成一份），题内小图 → 题图。"""
    from PIL import Image
    from papertype import pipeline
    monkeypatch.setenv("PAPERTYPE_DATA", str(tmp_path / "data"))
    chart = tmp_path / "chart.png"; Image.new("RGB", (300, 120), "gray").save(chart)
    small = tmp_path / "small.png"; Image.new("RGB", (100, 40), "black").save(small)
    doc = Document()
    doc.add_paragraph("(三)")
    doc.add_paragraph("根据下图回答1～2题。")
    doc.add_picture(str(chart))
    doc.add_paragraph("1.图中数值最大的一项是：")
    doc.add_paragraph("A. 第一项   B. 第二项   C. 第三项   D. 第四项")
    doc.add_paragraph("2.同比增速最高的是：")
    doc.add_paragraph("A. 甲   B. 乙   C. 丙   D. 丁")
    doc.add_paragraph("3.如图，问号处应填入的图形是：")
    doc.add_picture(str(small))
    doc.add_paragraph("A   B   C   D")
    f = tmp_path / "chart.docx"; doc.save(str(f))
    paper = pipeline.import_file(f)
    q1, q2, q3 = paper.questions
    adir = tmp_path / "data" / "assets" / paper.id
    assert q1.group and q2.group == q1.group
    assert q1.material_crop and Image.open(adir / q1.material_crop).size == (300, 120)
    assert q2.material_crop is None and q1.image is None and q2.image is None
    assert q3.group is None and q3.image and Image.open(adir / q3.image).size == (100, 40)


def test_docx_soft_breaks_split_into_lines(tmp_path):
    """WPS/老 .doc 常把整题放在一个段落里用软回车分行：要按行拆开，题干和选项才能分开。"""
    doc = Document()
    doc.add_paragraph("一、单选题")
    p = doc.add_paragraph()
    p.add_run("1.上层建筑的核心是：").add_break()
    p.add_run("A.思想意识形态   B.军队   C.监狱   D.国家政权").add_break()
    p.add_run("2.邓小平理论的精髓是：").add_break()
    p.add_run("A.解放思想，实事求是      B.独立自主").add_break()
    p.add_run("C.自力更生    D.改革开放")
    f = tmp_path / "soft.docx"
    doc.save(str(f))
    lines = docx_import.extract_lines(f)
    assert [l.text[:6] for l in lines] == ["一、单选题", "1.上层建筑", "A.思想意识", "2.邓小平理", "A.解放思想", "C.自力更生"]
    r = parse_lines(lines, source="docx")
    assert [q.no for q in r.questions] == [1, 2]
    assert r.questions[0].options == ["思想意识形态", "军队", "监狱", "国家政权"]
    assert r.questions[1].options == ["解放思想，实事求是", "独立自主", "自力更生", "改革开放"]


def test_doc_binary_text_numbering_softbreaks_table():
    """Word 97-2003 二进制 .doc：纯 Python 读正文、还原自动编号、软回车分行、表格按行、内置标题样式。"""
    from papertype.importers import doc_import
    assert doc_import.is_doc(FIX / "sample.doc")
    lines = doc_import.extract_lines(FIX / "sample.doc")
    assert [l.text for l in lines] == [
        "某银行校园招聘笔试模拟卷", "一、单选题",
        "1. 下列关于 TCP 的说法正确的是（ ）。", "A. 面向无连接   B. 提供可靠传输", "C. 不保证顺序   D. 无流量控制",
        "2. 属于关系型数据库的是（ ）。", "A. MySQL  B. Redis", "C. MongoDB  D. Neo4j",
        "二、判断题", "3. HTTP 是无状态协议。（ ）", "备注  本表仅用于测试",
    ]
    assert lines[-1].cells == ["备注", "本表仅用于测试"]          # 表格行保留单元格
    assert [l.number for l in lines if l.number] == [1, 2, 3]       # 自动编号跨分区连续
    assert lines[0].is_heading and not lines[1].is_heading
    r = parse_lines(lines, source="docx")
    assert [q.no for q in r.questions] == [1, 2, 3]
    assert r.questions[0].options == ["面向无连接", "提供可靠传输", "不保证顺序", "无流量控制"]
    assert r.questions[2].type == "judge"


def test_doc_renamed_as_docx_imports_without_converter(tmp_path, monkeypatch):
    """老 .doc 改后缀成 .docx 也能直接导入（不依赖 LibreOffice/Word）；非 Word 文件给明确提示。"""
    import shutil
    from papertype import pipeline
    monkeypatch.setenv("PAPERTYPE_DATA", str(tmp_path / "data"))
    f = tmp_path / "renamed.docx"
    shutil.copy(FIX / "sample.doc", f)
    paper = pipeline.import_file(f)
    assert paper.import_path == "doc" and [q.no for q in paper.questions] == [1, 2, 3]
    junk = tmp_path / "junk.docx"
    junk.write_bytes(b"not a word file" * 40)
    with pytest.raises(pipeline.ImportError_) as e:
        pipeline.import_file(junk)
    assert "另存为" in str(e.value)


def test_material_table_at_paper_start_with_decimal_cells():
    """资料分析卷首材料：提示语带"第"（回答第1—5题）、表格行含 1.19 之类小数、卷首无单元标题，
    材料仍应成组，表格行不被当成第 1 题。"""
    text = """(一)
根据下面的统计表回答第1—5题。
我国人口形势及预测
1980  1985  1990  1992  2000  2010
人口总数（亿）人  9.87  10.58  11.43  11.72  12.48  13.82
城镇人口（亿人）  1.19  2.50  3.02  3.24  5.23  7.66
乡村人口（亿人）  7.96  8.08  8.41  8.48  8.71  8.86
1.预测我国人口总数到哪一年，将接近14亿人
A. 2000            B. 2010            C. 2020            D.无法确定
2.预测我国2000年城镇与乡村人口的比例为：
A. 1∶1            B. 1∶1.5           C. 1∶1.67         D. 1∶2
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [1, 2]
    q1, q2 = r.questions
    assert q1.stem.startswith("预测我国人口总数") and q1.options == ["2000", "2010", "2020", "无法确定"]
    assert q1.group and q2.group == q1.group
    assert "城镇人口" in (q1.material or "") and "1.19" in q1.material
    assert "1980  1985" in q1.material                      # 纯数字的年份表头行保留


def test_material_short_header_line_is_not_section():
    """材料提示语之后的短行（"年度"）是表头：材料不被截断，纯数字数据行保留。"""
    text = """(五)
根据下面的统计表回答21～25题。
某大专院校教师情况
年度
类别  老年  中年  青年
1996  120  60  240
1997  210  40  320
合计  330
21.1997年老年教师比1996年多多少人?
A. 90            B. 70            C. 60            D. 50
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [21]
    m = r.questions[0].material or ""
    assert m.startswith("(五)") or m.startswith("根据下面")
    assert "某大专院校教师情况" in m and "年度" in m and "1997  210  40  320" in m and "合计  330" in m


def test_answer_key_rows_at_end_are_not_questions():
    text = """1.甲是（ ）。
A. 一 B. 二 C. 三 D. 四
2.乙是（ ）。
A. 一 B. 二 C. 三 D. 四
答案：
1. B      2. C
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [1, 2]
    assert r.questions[1].options == ["一", "二", "三", "四"]


def test_docx_table_kept_as_rows_in_material(tmp_path):
    """Word 表格：导入器保留单元格（含空表头格），材料里以竖线行保存，作答页渲染成表格。"""
    doc = Document()
    doc.add_paragraph("根据下表回答1～2题。")
    t = doc.add_table(rows=2, cols=3)
    for r, vals in enumerate([["", "2020", "2021"], ["产量（吨）", "120", "150"]]):
        for c, v in enumerate(vals):
            t.rows[r].cells[c].text = v
    doc.add_paragraph("1.2021年产量比2020年多多少?")
    doc.add_paragraph("A. 10   B. 20   C. 30   D. 40")
    doc.add_paragraph("2.2020年产量是多少?")
    doc.add_paragraph("A. 100   B. 120   C. 150   D. 200")
    f = tmp_path / "tbl.docx"
    doc.save(str(f))
    lines = docx_import.extract_lines(f)
    rows = [l.cells for l in lines if l.cells is not None]
    assert rows == [["", "2020", "2021"], ["产量（吨）", "120", "150"]]
    r = parse_lines(lines, source="docx")
    assert [q.no for q in r.questions] == [1, 2]
    m = r.questions[0].material or ""
    assert "||2020|2021|" in m and "|产量（吨）|120|150|" in m


@pytest.mark.parametrize("name", ["merged.docx", "merged.doc"])
def test_word_merged_cells_marked(name):
    """合并单元格：横向续格记 ">"，纵向续格记 "^"，docx 与 .doc 两种格式结果一致；材料里保留这些标记供作答页跨列/跨行渲染。"""
    from papertype.importers import doc_import
    f = FIX / name
    lines = doc_import.extract_lines(f) if name.endswith(".doc") else docx_import.extract_lines(f)
    rows = [l.cells for l in lines if l.cells is not None]
    assert rows == [["年度", "产量", ">"], ["^", "计划", "实际"], ["2020", "120", "150"]]
    r = parse_lines(lines, source="docx")
    assert [q.no for q in r.questions] == [1, 2]
    assert "|年度|产量|>|" in (r.questions[0].material or "") and "|^|计划|实际|" in r.questions[0].material


def test_number_missing_punctuation_is_rescued():
    """题号后漏了标点（"43市场调节是指"）：按期望题号救回，不再把下一题的选项粘进上一题。"""
    text = """42.企业要提高经济效益，必须使（ ）。
A.利益总额增加   B.消耗减少
C.利润增长快   D.利润率高
43市场调节是指：（ ）。
A.有计划地调节   B.由价值规律自发调节
C.资源配置方式   D.辅之以宏观调控
44.我国的社会主义市场经济体制的显著特点表现在（ ）。
A.甲   B.乙   C.丙   D.丁
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [42, 43, 44]
    assert [len(q.options) for q in r.questions] == [4, 4, 4]
    assert r.questions[1].stem.startswith("市场调节是指")


def test_numbered_subitems_in_stem_and_multi_dash_hint():
    """题干里的 "1．2．3．4．" 小项不是新题；"回答106——110题" 的双破折号提示语要认出材料。"""
    text = """105．下列说法与资料相符的有几个？（  ）
1．甲国幸福指数高于乙国。
2．人口过亿的国家失业率越低。
3．丙国失业率低于丁国。
4．戊国幸福指数最低。
A．0   B．1   C．2   D．3
四、根据以下资料，回答106——110题
2009年5月全国邮电业务基本情况
邮电业务总量  亿元  10722.8  4274.2  11.4  11.6
邮政业务总量  亿元  630.1  133.0  12.7  16.4
106．2009年1—5月，平均每月约多少亿份？（  ）
A．13.7   B．14.2   C．14.6   D．17.8
107．同比增长率从高到低排列正确的是：（  ）
A．函件—包裹   B．汇票—包裹   C．快递—汇票   D．函件—汇票
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [105, 106, 107]
    q105, q106, q107 = r.questions
    assert q105.options == ["0", "1", "2", "3"] and "4．戊国幸福指数最低" in q105.stem
    assert q106.group and q107.group == q106.group and "邮电业务总量" in (q106.material or "")
    assert len(q107.options) == 4


def test_answer_section_at_end_stops_parsing():
    """卷末"参考答案与解析"之后的 "1．【解析】A。…" 不是新题。"""
    text = """139.甲（ ）。
A. 一 B. 二 C. 三 D. 四
140.乙（ ）。
A. 一 B. 二 C. 三 D. 四
参考答案与解析
1．【解析】A。一个"更"字传达出自豪的语气。
2．【解析】C。传达：向别人转述。
"""
    r = parse_lines(text_import.extract_lines(text), source="docx")
    assert [q.no for q in r.questions] == [139, 140]
    assert r.questions[1].options == ["一", "二", "三", "四"]
