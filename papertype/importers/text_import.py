"""粘贴文本导入：一行一条 Line，无坐标。"""
from __future__ import annotations

import re

from ..models import Line

BLANK_RUN_RE = re.compile(r"[_＿]{2,}")


def extract_lines(text: str) -> list[Line]:
    out = []
    for i, raw in enumerate(text.splitlines()):
        t = raw.strip()
        if not t:
            continue
        out.append(Line(text=t, page=0, y=float(i), x=0.0, height=1.0, source="text",
                        blanks=len(BLANK_RUN_RE.findall(t))))
    return out
