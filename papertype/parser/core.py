"""规则切题：Line 列表 → Question 列表。

流程：物理行按缩进合并成逻辑段落 → 段落分类（单元 / 分区标题 / 题号 / 选项 / 答案 / 其他）
→ 顺序扫描组装题目 → 题型判定 → 材料分组 → 校验。规则依据 docs/最终方案 §8.2。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Line, Question
from .validate import validate

NUM_RE = re.compile(r"^\s*(\d{1,3})\s*[\.．、:：](?!\d(?!\d{3}\s*[年～~\-—–]))\s*")   # 允许 "2.2017 年…" "16.2011～2017 年"：题号后紧跟年份
NUM_LOOSE_RE = re.compile(r"(?=(\d{1,3})\s*[\.．、])")
NUM_WORD_RE = re.compile(r"^\s*第\s*(\d{1,3})\s*题[\.．、:：]?\s*")
UNIT_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十\d]+)\s*(单元|部分|篇|卷)\s*[:：]?\s*(.*)$")
SECTION_RE = re.compile(r"^\s*([一二三四五六七八九十]+)\s*[、\.．]\s*(.+)$")
OPTION_HEAD_RE = re.compile(r"^\s*([A-G])(?:\s*[\.．、:：]|\s+(?![项选正错和或与])(?=[一-鿿\d]))\s*")
LETTER_ROW_RE = re.compile(r"^\s*A(\s+[B-G])+\s*$")
OPTION_ANY_RE = re.compile(r"([A-G])(?:\s*[\.．、]|\s+(?![项选正错和或与])(?=[一-鿿\d]))")
ANSWER_RE = re.compile(r"^\s*(【\s*(答案|参考答案|正确答案)\s*】|(答案|参考答案|正确答案|解析|答案解析|【解析】|【答案解析】)\s*[:：]?)")
ANALYSIS_RE = re.compile(r"^\s*(【\s*解析\s*】|解析\s*[:：])")
ANALYSIS_TAIL_RE = re.compile(r"故本题|正确答案|答案[为选是]|排除\s*[A-G]|[选为]\s*[A-G]\s*[。．]|^[A-G]\s*项[，,、：:]|错误[，。]排除|正确[，。]排除|由(表格|材料|题干|图表?|文段)可知|(正确|错误)[。；;]")
INLINE_ANSWER_RE = re.compile(r"[（(]\s*([A-G]{1,4})\s*[)）]")
BLANK_RUN_RE = re.compile(r"[_＿]{2,}")
PAREN_BLANK_RE = re.compile(r"[（(]\s{2,}[)）]")
MATERIAL_HINT_RE = re.compile(r"(阅读|根据)(以下|下列|下面)?(材料|短文|文章|资料)|回答\s*\d+\s*[～~\-—至]\s*\d+\s*题|Text\s*\d+|Passage\s*\d+")
TEXT_MARK_RE = re.compile(r"^\s*(Text|Passage)\s*\d+\s*$", re.I)
TYPE_MARK_RE = re.compile(r"^\s*[【\[（(]\s*(单选题|多选题|判断题|填空题|简答题|不定项选择题|单选|多选|判断|填空|简答|不定项)\s*[】\]）)]\s*")
TYPE_MARK_MAP = {"单选": "single", "多选": "multi", "判断": "judge", "填空": "blank", "简答": "essay", "不定项": "multi"}

SECTION_TYPES = [
    (re.compile(r"不定项|多项选择|多选"), "multi"),
    (re.compile(r"单项选择|单选|选择题"), "single"),
    (re.compile(r"判断"), "judge"),
    (re.compile(r"填空"), "blank"),
    (re.compile(r"简答|论述|问答|案例分析|计算题|材料分析"), "essay"),
    (re.compile(r"选词填空|完形填空|阅读理解|逻辑推理|判断推理|数字运算|数量关系|资料分析|言语理解|图形推理|思维策略|常识|定义判断|类比推理"), "single"),
]
MATH_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹×÷√∑∫≈≠≤≥∠π°∞]|\d\s*/\s*\d|[\uE000-\uF8FF]|□")
PUA_RE = re.compile(r"[\uE000-\uF8FF\uFFFD]")
FORMULA_LINE_RE = re.compile(r"^[\d\s+\-×÷*/=().,（）％%^²³√…]{8,}$")
TABLE_ROW_RE = re.compile(r"^[^\d]{1,24}?\s*(-?\d[\d.,%]*\s*){3,}$")   # 表格数据行："国有单位  43.32  -6.43  41.28"
ANALYSIS_BODY_RE = re.compile(r"解得|可得|可知|则[有：:]|设[一-鿿a-zA-Z]{0,4}[为是]|排除|选项|答案|∴|综上|即可|[=＝]|故选|本题|考[查察]")
SHORT_HEADING_RE = re.compile(r"[一-鿿A-Za-z]{2,8}(?:\s*[（(]\s*\d{1,3}\s*[)）])?")   # 如"数字推理（25）"
CHART_LINE_RE = re.compile(r"^[\d\s.,%．，、:：\-—–~～/()（）]+$")
MATERIAL_SECTIONS = re.compile(r"完形填空|阅读理解|资料分析|阅读材料")
MULTI_STEM_RE = re.compile(r"多项|多选|有哪些|包括哪些|正确的有|错误的有|不定项")


@dataclass
class Para:
    text: str
    kind: str = "other"     # unit / section / number / option / answer / mark / other / image
    number: int | None = None
    page: int = 0
    y: float = 0.0
    x: float = 0.0
    height: float = 0.0
    image: bool = False
    blanks: int = 0
    lines: list[Line] = field(default_factory=list)


@dataclass
class ParseResult:
    title: str
    units: list[str]
    questions: list[Question]
    notes: list[str] = field(default_factory=list)


# ---------- 1. 物理行 → 逻辑段落 ----------

def _merge_paragraphs(lines: list[Line]) -> list[Para]:
    paras: list[Para] = []
    page_full: dict[int, float] = {}                          # 每页满行宽度（第 90 百分位，中文计 1、ASCII 计 0.55）
    by_page: dict[int, list[float]] = {}
    for l in lines:
        if not l.image and l.text:
            by_page.setdefault(l.page, []).append(_wlen(l.text))
    for pg, ws in by_page.items():
        ws.sort(); page_full[pg] = ws[int(len(ws) * 0.9)]
    for idx, ln in enumerate(lines):
        nxt = next((l for l in lines[idx + 1:idx + 4] if not l.image and l.text.strip()), None)
        if ln.image:
            paras.append(Para(text="", kind="image", page=ln.page, y=ln.y, x=ln.x, height=ln.height, image=True))
            continue
        text = ln.text.strip()
        if not text:
            continue
        short_heading = bool(SHORT_HEADING_RE.fullmatch(text))
        hard_new = bool(NUM_RE.match(text) or NUM_WORD_RE.match(text) or OPTION_HEAD_RE.match(text)
                        or UNIT_RE.match(text) or SECTION_RE.match(text) or ANSWER_RE.match(text)
                        or ln.is_heading or TEXT_MARK_RE.match(text) or ln.number)
        prev = paras[-1] if paras else None
        if prev and prev.kind in ("unit", "section", "mark"):
            prev = None
        tol = max(3.0, ln.height * 0.6)
        if prev and not prev.image and not hard_new and ln.source in ("pdf", "ocr", "docx") \
                and ln.x < prev.x - tol and ln.page == prev.lines[-1].page:
            # 缩进悬挂：比段落首行更靠左 → 续行。例外：短小无标点的行且下一行是题号 / 单元 → 它是小节标题
            nxt_t = nxt.text.strip() if nxt else ""
            prev_full = _wlen(prev.lines[-1].text) >= page_full.get(ln.page, 40) * 0.8 and not _ends_sentence(prev.text)
            heading_like = short_heading and not prev_full and (NUM_RE.match(nxt_t) or UNIT_RE.match(nxt_t) or SECTION_RE.match(nxt_t) or not nxt)
            if not heading_like:
                _append(prev, ln); continue
        starts_new = hard_new or short_heading
        if prev and not prev.image and not starts_new and ln.source in ("pdf", "ocr", "docx"):
            prev_last = NUM_RE.sub("", prev.lines[-1].text, count=1) if prev.lines else prev.text
            blocked = TABLE_ROW_RE.match(prev_last.strip()) or MATERIAL_HINT_RE.search(text)   # 表格行之后 / 材料提示语之前不续行
            if ln.page != prev.page and prev.kind != "option" and not _ends_sentence(prev.text) and not blocked:
                _append(prev, ln); continue
            if abs(ln.x - prev.x) <= tol and prev.kind == "other" and not _ends_sentence(prev.text) and not blocked:
                _append(prev, ln); continue
        if prev and not prev.image and not starts_new and ln.source == "text":
            if prev.kind in ("number", "other") and not _ends_sentence(prev.text):
                _append(prev, ln); continue
            if prev.kind == "option" and len(text) < 25:
                _append(prev, ln); continue
        p = Para(text=text, page=ln.page, y=ln.y, x=ln.x, height=ln.height, blanks=ln.blanks, lines=[ln])
        _classify(p, ln)
        paras.append(p)
    return paras


def _wlen(t: str) -> float:
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in t)


def _ends_sentence(t: str) -> bool:
    return bool(t) and t.rstrip()[-1] in "。．.！!？?：:；;）)”\"」』"


def _append(p: Para, ln: Line):
    sep = " " if (p.text and ord(p.text[-1]) < 128 and ln.text and ord(ln.text[0]) < 128) else ""
    p.text = (p.text + sep + ln.text.strip()).strip()
    p.blanks += ln.blanks
    p.lines.append(ln)


def _classify(p: Para, ln: Line):
    t = p.text
    if UNIT_RE.match(t) and len(t) < 30:
        p.kind = "unit"; return
    if ANSWER_RE.match(t):
        p.kind = "answer"; return
    if TEXT_MARK_RE.match(t):
        p.kind = "mark"; return
    m = SECTION_RE.match(t)
    if m and len(t) < 20 and not OPTION_HEAD_RE.match(t):
        p.kind = "section"; return
    if ln.number:
        p.kind = "number"; p.number = ln.number; return
    m = NUM_RE.match(t) or NUM_WORD_RE.match(t)
    if m:
        rest = t[m.end():]
        if TABLE_ROW_RE.match(rest):
            p.kind = "other"; return          # 带编号的表格数据行，不是题目
        p.kind = "number"; p.number = int(m.group(1)); return
    if OPTION_HEAD_RE.match(t) or LETTER_ROW_RE.match(t):
        p.kind = "option"; return
    if ln.is_heading and len(t) < 30:
        p.kind = "section"; return
    if SHORT_HEADING_RE.fullmatch(t):
        # 短小无标点的独立行：视为小节标题（如"逻辑推理""资料分析"）
        p.kind = "section"; return
    p.kind = "other"


# ---------- 2. 题号容错：期望的下一题号藏在行首附近 ----------

def _rescue_number(p: Para, expected: int) -> bool:
    if p.kind != "other" or expected <= 0:
        return False
    head = p.text[:16]
    for m in NUM_LOOSE_RE.finditer(head):
        if int(m.group(1)) == expected:
            end = m.start() + len(m.group(1))
            rest = p.text[end:]
            rest = re.sub(r"^\s*[\.．、]\s*", "", rest, count=1)
            if TABLE_ROW_RE.match(rest.split("\n")[0]):
                return False               # 带编号的表格数据行
            p.kind = "number"; p.number = expected
            p.text = (p.text[:m.start()] + rest).strip()
            return True
    return False


# ---------- 3. 选项拆分 ----------

def _split_options(text: str) -> list[tuple[str, str]]:
    """把一段文字按 A. B. C. 顺序拆成 [(字母, 内容)]；只接受从行首字母开始且连续的字母序列。"""
    cands = list(OPTION_ANY_RE.finditer(text))
    if not cands:
        return []
    picked = []
    want = cands[0].group(1) if cands[0].start() <= 2 else "A"
    for m in cands:
        if m.group(1) == want:
            picked.append(m); want = chr(ord(want) + 1)
    if not picked or picked[0].start() > 2:
        return []
    out = []
    for i, m in enumerate(picked):
        end = picked[i + 1].start() if i + 1 < len(picked) else len(text)
        out.append((m.group(1), text[m.end():end].strip()))
    return out


# ---------- 4. 主流程 ----------

def parse_lines(lines: list[Line], source: str = "text") -> ParseResult:
    paras = _merge_paragraphs(lines)
    title = ""
    units: list[str] = []
    unit = ""
    section = ""
    section_type = "single"
    questions: list[Question] = []
    qmeta: dict[int, dict] = {}       # id(question) -> {section, section_type}
    materials: dict[str, str] = {}
    cur: Question | None = None
    cur_stage = "stem"                # stem / options
    pending_other: list[Para] = []    # 选项之后、下一题之前的其他段落（候选材料）
    pending_images: list[Para] = []   # 题目之间出现的图片（纯图片材料，如资料分析的图表）
    group_id: str | None = None
    group_seq = 0
    group_end: int | None = None      # 材料提示"回答 49～53 题"给出的结束题号
    group_count = 0
    last_no = 0
    num_x = None                      # 最近一个题号行的横坐标
    skipping_answer = False
    pending_after_answer = False      # 当前 pending 是解析块之后收的（可能其实是解析）
    seen_first_question = False

    part_seq = 0
    section_of_first = ""
    section_after_q = False

    def open_auto_unit():
        """没有单元标题但题号重新从 1 开始：自动开一个单元，名字取最近的分区标题，否则"第 N 部分"。"""
        nonlocal unit, part_seq, group_id
        part_seq += 1
        base = section if (section and section_after_q) else (unit.split("·")[0] if unit else f"第{part_seq}部分")
        name = base
        k = 2
        while name in units:
            name = f"{base}·{k}"; k += 1
        unit = name
        units.append(unit)
        group_id = None                    # 攒着的材料段落保留，归到新单元的第一题

    def close_current(end_page: int, end_y: float):
        nonlocal cur, cur_stage
        if cur is None:
            return
        cur.end_page, cur.y1 = end_page, end_y
        questions.append(cur)
        cur, cur_stage = None, "stem"

    material_pos: dict[str, tuple[int, float]] = {}

    def start_group(text: str, pos: tuple[int, float] | None = None):
        nonlocal group_id, group_seq, group_end, group_count
        group_seq += 1
        group_id = f"g{group_seq}"
        materials[group_id] = text.strip()
        if pos:
            material_pos[group_id] = pos
        group_count = 0
        m = re.search(r"回答\s*(\d+)\s*[～~\-—至到]\s*(\d+)\s*题", text)
        group_end = int(m.group(2)) if m else None

    def flush_pending_as_material():
        nonlocal pending_other, pending_images, pending_after_answer
        pending_after_answer = False
        big_images = [x for x in pending_images if x.height >= 60]
        if not pending_other and not big_images:
            pending_images = []
            return
        text = "\n".join(x.text for x in pending_other)
        clean = _material_text(pending_other)
        if not seen_first_question and not unit and not section and group_id is None and not big_images:
            pending_other, pending_images = [], []      # 卷首说明 / 题量表，不是材料
            return
        if not clean and not big_images:
            pending_other, pending_images = [], []      # 只有分隔线 / 坐标数字之类的碎片，不是材料
            return
        if len(pending_other) >= 2 or MATERIAL_HINT_RE.search(text) or len(text) > 120 or big_images:
            firsts = pending_other + big_images
            first = min(firsts, key=lambda x: (x.page, x.y))
            pos = (first.page, first.y)
            if group_id and materials.get(group_id) == "" and group_id not in material_pos:
                materials[group_id] = clean          # "Text 1" 标记之后的正文
                material_pos[group_id] = pos
            else:
                start_group(clean, pos)
        pending_other, pending_images = [], []

    for idx, p in enumerate(paras):
        if idx == 0 and p.kind == "other" and len(p.text) <= 30 and not title:
            title = p.text          # 卷首第一行短文本 = 试卷名（OCR 路径无字号信息）
            continue
        if p.kind == "unit":
            close_current(p.page, p.y)
            m = UNIT_RE.match(p.text)
            unit = (m.group(3) or f"第{m.group(1)}{m.group(2)}").strip()
            if unit not in units:
                units.append(unit)
            section, section_type = "", "single"
            group_id, pending_other, pending_images, last_no, skipping_answer = None, [], [], 0, False
            continue
        nxt_para = paras[idx + 1] if idx + 1 < len(paras) else None
        before_restart = nxt_para is not None and nxt_para.kind == "number" and nxt_para.number == 1
        if p.kind == "section" and cur is None and not p.lines[0].is_heading and seen_first_question \
                and not before_restart \
                and (pending_other or (skipping_answer and not SECTION_RE.match(p.text))):
            p.kind = "other"          # 材料累积中的小标题 / 解析之后的无编号短行（图表单位、表头）不是分区标题
        if p.kind == "section" and before_restart and pending_after_answer:
            pending_other, pending_after_answer = [], False     # 分区标题前攒的是解析残余
        if p.kind == "section":
            if not seen_first_question and not title and not unit and p.lines and p.lines[0].is_heading:
                title = p.text
                continue
            close_current(p.page, p.y)
            section = re.sub(r"^\s*[一二三四五六七八九十]+\s*[、\.．]\s*", "", p.text).strip()
            section_type = _section_type(section)
            if not seen_first_question and not unit:
                section_of_first = section
            section_after_q = True
            group_id, pending_other, pending_images, skipping_answer = None, [], [], False
            continue
        if p.kind == "mark":
            close_current(p.page, p.y)
            pending_other, skipping_answer = [], False
            start_group("")
            continue
        if p.kind == "answer":
            close_current(p.page, p.y)
            skipping_answer = True
            continue
        if p.kind == "other":
            if not (cur is not None and qmeta.get(id(cur), {}).get("inferred") and _rescue_number(p, last_no)):
                _rescue_number(p, last_no + 1)
        if p.kind == "number" and cur is not None and p.number == last_no and qmeta.get(id(cur), {}).get("inferred"):
            # 推断出的题号之后真正的题号行出现：推断题的内容其实是材料，本行才是题干
            if cur.stem.strip() and not cur.options and (len(cur.stem) > 40 or MATERIAL_HINT_RE.search(cur.stem) or cur.image):
                start_group(cur.stem, (cur.page, cur.y0))
                cur.group = group_id
                group_count = 1
            cur.stem = (NUM_RE.sub("", p.text, count=1) if NUM_RE.match(p.text) else NUM_WORD_RE.sub("", p.text, count=1)).strip()
            cur.page, cur.y0 = p.page, p.y
            cur.issues = [i for i in cur.issues if "推断" not in i]
            qmeta[id(cur)]["inferred"] = False
            num_x = p.x
            opts = _split_options(cur.stem)
            if len(opts) >= 2:
                cur.stem = cur.stem[:_first_option_pos(cur.stem)].strip()
                cur.options = [o for _, o in opts]
                cur_stage = "options"
            continue
        if p.kind == "number" and last_no and p.number not in (1, last_no + 1, last_no + 2, last_no + 3):
            p.kind = "other"        # 材料 / 图表里的数字，不是题号
        if p.kind == "number" and p.number == 1 and last_no >= 3:
            close_current(p.page, p.y)
            if not unit:
                part_seq_before = part_seq
                # 第一次重排时，把前面的题补进"第 1 部分"
                first_name = section_of_first or "第1部分"
                for q in questions:
                    if not q.unit:
                        q.unit = first_name
                if first_name not in units:
                    units.insert(0, first_name)
                part_seq = 1
            open_auto_unit()
            last_no = 0
        if skipping_answer and source != "text" and p.kind in ("other", "option") and ANALYSIS_TAIL_RE.search(p.text) and len(p.text) < 120:
            continue    # 解析的零散尾巴
        if skipping_answer and source != "text" and p.kind == "other" and ANALYSIS_TAIL_RE.search(p.text):
            continue    # 解析的跨页段落
        if skipping_answer and source != "text" and p.kind == "other" and last_no \
                and (num_x is None or p.x >= num_x - max(3.0, p.height * 0.6)) \
                and (MATERIAL_HINT_RE.search(p.text[:40]) or not (_looks_like_stem(p.text) or re.search(r"[（(]\s*[)）]", p.text))):
            if ANALYSIS_BODY_RE.search(p.text):
                continue                     # 与题目同缩进的解析段落
            skipping_answer = False          # 解析结束后的正文段落：下一组题的材料候选
            pending_after_answer = True
            pending_other.append(p)
            continue
        if skipping_answer and source != "text" and p.kind in ("other", "option") and last_no \
                and (num_x is None or p.x >= num_x - max(3.0, p.height * 0.6)):
            # 解析段落的续行已按缩进并入答案段；此处仍出现题目缩进的正文，说明下一题开始了但题号没识别出（多为公式图）
            close_current(p.page, p.y)
            cur = Question(unit=unit, no=last_no + 1, stem="" if p.kind == "option" else p.text,
                           page=p.page, y0=p.y, source=source)
            cur.issues.append("题号未识别，按顺序推断")
            qmeta[id(cur)] = {"section": section, "section_type": section_type, "inferred": True}
            last_no += 1
            skipping_answer = False
            if p.kind == "option":
                opts = _split_options(p.text) or [(p.text[0], OPTION_HEAD_RE.sub("", p.text, count=1))]
                cur.options.extend(o for _, o in opts)
                cur_stage = "options"
            continue
        def infer_from_pending(upto: Para):
            """题号丢失但前面堆着像题干的段落：推断出缺失的那道题（校正页标红）。"""
            nonlocal cur, cur_stage, last_no, pending_other
            first = pending_other[0]
            close_current(first.page, first.y)
            cur = Question(unit=unit, no=last_no + 1, stem="\n".join(x.text for x in pending_other),
                           page=first.page, y0=first.y, source=source)
            cur.issues.append("题号未识别，按顺序推断")
            qmeta[id(cur)] = {"section": section, "section_type": section_type, "inferred": True}
            if any(x.image for x in paras if x.page == first.page and first.y <= x.y < upto.y):
                cur.image = "pending"
            last_no += 1
            pending_other = []
            cur_stage = "stem"

        if p.kind == "number" and last_no and p.number == last_no + 2 and pending_other and cur is not None \
                and _looks_like_stem(pending_other[0].text):
            infer_from_pending(p)
        elif p.kind == "option" and cur is not None and len(cur.options) >= 2 and pending_other \
                and _looks_like_stem(pending_other[0].text):
            infer_from_pending(p)
        if p.kind == "number":
            skipping_answer = False
            seen_first_question = True
            flush_pending_as_material()
            close_current(p.page, p.y)
            body = NUM_RE.sub("", p.text, count=1) if NUM_RE.match(p.text) else NUM_WORD_RE.sub("", p.text, count=1)
            cur = Question(unit=unit, no=p.number or 0, stem=body.strip(), page=p.page, y0=p.y, source=source)
            cur.blanks = p.blanks
            section_after_q = False
            if TYPE_MARK_RE.match(cur.stem):
                group_id = None          # 题干自带【多选题】等标记 = 新的分区，材料组到此为止
            if group_id:
                cap = 20 if MATERIAL_SECTIONS.search(section) else 6
                if (group_end is not None and cur.no > group_end) or (group_end is None and group_count >= cap):
                    group_id = None
                else:
                    cur.group = group_id
                    group_count += 1
            qmeta[id(cur)] = {"section": section, "section_type": section_type}
            last_no = p.number or last_no
            num_x = p.x
            opts = _split_options(cur.stem)
            if len(opts) >= 2:
                cur.stem = cur.stem[:_first_option_pos(cur.stem)].strip()
                cur.options = [o for _, o in opts]
                cur_stage = "options"
            continue
        if p.kind == "image" and (cur is None or skipping_answer):
            if not skipping_answer or p.height >= 150:      # 解析里的小插图不算材料；整页大图（资料）才算
                pending_images.append(p)
            continue
        if skipping_answer:
            continue
        if cur is None:
            if p.kind == "other":
                if pending_after_answer and (ANALYSIS_BODY_RE.search(p.text) or ANALYSIS_TAIL_RE.search(p.text)):
                    pending_other, pending_after_answer, skipping_answer = [], False, True   # 原来是解析，不是材料
                    continue
                if seen_first_question or unit or section or group_id is not None:
                    pending_other.append(p)
            continue
        if p.kind == "image":
            cur.image = cur.image or "pending"
            continue
        if p.kind == "option":
            if LETTER_ROW_RE.match(p.text):
                opts = [(c, "") for c in p.text.split()]
            else:
                opts = _split_options(p.text) or [(p.text[0], OPTION_HEAD_RE.sub("", p.text, count=1))]
            cur.options.extend(o for _, o in opts)
            cur_stage = "options"
            continue
        if p.kind == "other":
            if cur_stage == "stem":
                cur.stem = (cur.stem + "\n" + p.text).strip()
                cur.blanks += p.blanks
            else:
                pending_other.append(p)
            continue
    if paras:
        close_current(paras[-1].page, paras[-1].y + paras[-1].height)

    seen: set[str] = set()
    for q in questions:
        if q.group and q.group not in seen:
            seen.add(q.group)
            q.material = materials.get(q.group) or None
            if q.group in material_pos:
                q.m_page, q.m_y0 = material_pos[q.group]
        if q.group and not materials.get(q.group) and q.group not in material_pos:
            q.group = None
    _finalize(questions, qmeta)
    validate(questions)
    return ParseResult(title=title, units=units, questions=questions)


def _material_text(paras: list[Para]) -> str:
    """材料文字：按物理行剔除图表坐标 / 纯数字行，保留正文与表格行。"""
    out = []
    for p in paras:
        for l in (p.lines or []):
            t = l.text.strip()
            if not t or CHART_LINE_RE.match(t):
                continue
            cjk = len(re.findall(r"[一-鿿A-Za-z]", t))
            if cjk < 2 and len(t) > 3:
                continue
            out.append(t)
    return "\n".join(out).strip()


def _looks_like_stem(text: str) -> bool:
    t = text.strip()
    return bool(re.search(r"[：:？?]$", t) or re.search(r"选项|填入|问号|下列|以下|正确|错误|规律", t))


def _first_option_pos(text: str) -> int:
    m = re.search(r"(?<![\d.])A\s*[\.．、]", text)
    return m.start() if m else len(text)


def _section_type(section: str) -> str:
    for rx, t in SECTION_TYPES:
        if rx.search(section):
            return t
    return "single"


def _finalize(questions: list[Question], qmeta: dict[int, dict]):
    for q in questions:
        meta = qmeta.get(id(q), {})
        st = meta.get("section_type", "single")
        m = TYPE_MARK_RE.match(q.stem)
        if m:
            st = TYPE_MARK_MAP.get(m.group(1)[:2], st) if m.group(1)[:3] != "不定项" else "multi"
            q.stem = q.stem[m.end():].strip()
        # 题干里已填的答案字母清空
        if q.options:
            q.stem = INLINE_ANSWER_RE.sub("（　）", q.stem)
        # 空位统计：下划线串 + 填空区的宽括号
        q.blanks = max(q.blanks, len(BLANK_RUN_RE.findall(q.stem)))
        if not q.options and st in ("blank", "single") and PAREN_BLANK_RE.search(q.stem):
            q.blanks = max(q.blanks, len(PAREN_BLANK_RE.findall(q.stem)))
        if q.image == "pending" and not q.options and re.search(r"问号|图形|图片|填入", q.stem):
            q.options = ["", "", "", ""]
        # 题型
        if q.options:
            if st == "multi" or MULTI_STEM_RE.search(q.stem):
                q.type = "multi"
            elif st == "judge" and len(q.options) == 2:
                q.type = "judge"
            else:
                q.type = "single"
        else:
            if st == "judge":
                q.type = "judge"
            elif st == "essay":
                q.type = "essay"
            else:
                q.type = "blank"
                q.blanks = max(q.blanks, 1)
        # 数学符号题（分数、上标、运算符、公式对象）一律看图作答：题干或选项含这些符号
        alltext = q.stem + "\n" + "\n".join(q.options)
        if q.stem and MATH_RE.search(alltext):
            q.image = q.image or "pending"
        # 公式对象：私有编码字符（Word 公式的运算符）或整行数字运算式 → 看图作答
        if q.stem and (PUA_RE.search(q.stem) or any(FORMULA_LINE_RE.match(l.strip()) for l in q.stem.splitlines()[1:])):
            q.image = q.image or "pending"
            if PUA_RE.search(q.stem):
                q.stem = PUA_RE.sub("□", q.stem)
                q.issues.append("题干含无法还原的公式符号，已改为看图作答，请核对")
        # 图片题：有图像对象且（题干很短或选项内容为空）
        if q.image == "pending":
            empty_opts = q.options and all(len(o.strip()) == 0 for o in q.options)
            formula = PUA_RE.search(q.stem) or any(FORMULA_LINE_RE.match(l.strip()) for l in q.stem.splitlines()) or MATH_RE.search(alltext)
            q.image = "yes" if (empty_opts or len(q.stem) < 40 or formula) else None
        if q.options and all(len(o.strip()) == 0 for o in q.options) and not q.image:
            q.image = "yes"
        if q.options and not q.stem.strip():
            q.stem = f"（第 {q.no} 空）" if q.group else f"（第 {q.no} 题）"
