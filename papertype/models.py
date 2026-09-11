"""核心数据结构。所有导入路径都先变成 Line 列表，再由解析器变成 Question 列表。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Line:
    """带结构的文本行：所有导入器（docx / pdf / ocr / text）的统一输出。"""
    text: str
    page: int = 0            # 从 1 起；粘贴文本为 0
    y: float = 0.0           # 行顶纵坐标（页内），粘贴文本按行号递增
    x: float = 0.0           # 行左横坐标
    height: float = 0.0      # 行高
    number: Optional[int] = None   # docx 自动编号还原出的序号
    blanks: int = 0          # 该行内还原出的空位数
    source: str = "text"     # text / docx / pdf / ocr
    is_heading: bool = False # docx 标题样式、pdf 大字号
    image: bool = False      # 该行是占位的图片对象
    ref: Optional[str] = None  # docx 内嵌图片的文件名


@dataclass
class Question:
    unit: str = ""               # 单元名，无单元为空
    no: int = 0                  # 卷面题号
    type: str = "single"         # single / multi / judge / blank / essay
    stem: str = ""
    options: list[str] = field(default_factory=list)
    blanks: int = 0
    image: Optional[str] = None  # 图片题的裁剪图（作答页主体）
    crop: Optional[str] = None   # 每题的原文裁剪图（校正页参考）
    group: Optional[str] = None  # 材料题分组 id
    material: Optional[str] = None  # 分组材料文本（组内第一题带，其余引用 group）
    material_crop: Optional[str] = None  # 材料的裁图（含图表时有用）
    m_page: int = 0                 # 材料起点（供裁图）
    m_y0: float = 0.0
    reviewed: bool = True        # False = 待核对
    issues: list[str] = field(default_factory=list)  # 校验说明
    page: int = 0
    y0: float = 0.0
    end_page: int = 0
    y1: float = 0.0
    source: str = "text"

    def key(self) -> str:
        return f"{self.unit}|{self.no}"


@dataclass
class Paper:
    id: str
    title: str
    source: str
    import_path: str             # docx / pdf-text / ocr / text
    created_at: str
    units: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    raw_text: str = ""           # 导入时抽取出的原文（供大模型重切 / OCR 整理）

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Paper":
        qs = [Question(**q) for q in d.get("questions", [])]
        return Paper(
            id=d["id"], title=d["title"], source=d["source"], import_path=d["import_path"],
            created_at=d["created_at"], units=d.get("units", []), questions=qs, raw_text=d.get("raw_text", ""),
        )
