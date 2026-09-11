"""校验：不过的题标 reviewed=False 并写明原因（docs/最终方案 §8.3）。"""
from __future__ import annotations

import re

from ..models import Question

GARBLE_RE = re.compile(r"[^一-鿿A-Za-z0-9\s，。、：；！？（）()【】《》“”‘’\"'．.,:;!?%‰℃°+\-—–_/×÷=<>≤≥≠~～·…《》\[\]{}&@#$*^|\\]{3,}")


def validate(questions: list[Question]) -> None:
    prev: dict[str, int] = {}
    for q in questions:
        issues: list[str] = list(q.issues)
        last = prev.get(q.unit)
        if last is not None and q.no != last + 1:
            issues.append(f"题号不连续：上一题 {last}，本题 {q.no}")
        prev[q.unit] = q.no
        if q.type in ("single", "multi") and len(q.options) < 2:
            issues.append(f"选项只有 {len(q.options)} 个")
        if q.type in ("single", "multi") and len(q.options) > 7:
            issues.append(f"选项多达 {len(q.options)} 个，可能粘连了下一题")
        if q.type == "blank" and q.blanks < 1:
            issues.append("填空题没有空位")
        if not q.stem.strip() and not q.image:
            issues.append("题干为空")
        if len(q.stem) > 600:
            issues.append("题干过长，可能混入了解析或材料")
        if q.source == "ocr":
            if q.options and len(q.options) < 4 and q.type == "single":
                issues.append("OCR 卷选项不足 4 个")
            if q.stem and len(q.stem) < 6 and not q.image:
                issues.append("OCR 卷题干过短")
            if GARBLE_RE.search(q.stem):
                issues.append("题干含疑似乱码")
        q.issues = issues
        q.reviewed = not issues
