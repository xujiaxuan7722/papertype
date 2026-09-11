"""试卷 / 草稿 / 作答记录：一份一个 JSON 文件。"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import data_dir
from ..models import Paper

SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")


def new_id(prefix: str = "") -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{prefix}" if prefix else ts


def _p(kind: str, pid: str) -> Path:
    return data_dir() / kind / f"{SAFE_RE.sub('', pid)}.json"


def save_paper(paper: Paper, kind: str = "papers") -> str:
    _p(kind, paper.id).write_text(json.dumps(paper.to_dict(), ensure_ascii=False, indent=1), "utf-8")
    return paper.id


def load_paper(pid: str, kind: str = "papers") -> Paper | None:
    p = _p(kind, pid)
    if not p.exists():
        return None
    return Paper.from_dict(json.loads(p.read_text("utf-8")))


def delete_paper(pid: str, kind: str = "papers") -> None:
    p = _p(kind, pid)
    if p.exists():
        p.unlink()


def list_papers(kind: str = "papers") -> list[dict]:
    out = []
    for p in sorted((data_dir() / kind).glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text("utf-8"))
            qs = d.get("questions", [])
            out.append({"id": d["id"], "title": d["title"], "source": d["source"], "import_path": d["import_path"],
                        "created_at": d["created_at"], "count": len(qs),
                        "to_review": sum(1 for q in qs if not q.get("reviewed", True)),
                        "attempts": len(list_attempts(d["id"])) if kind == "papers" else 0})
        except Exception:
            continue
    return out


def assets_dir(pid: str) -> Path:
    d = data_dir() / "assets" / SAFE_RE.sub("", pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- 作答记录 ----

def attempts_dir(pid: str) -> Path:
    d = data_dir() / "attempts" / SAFE_RE.sub("", pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_draft_answers(pid: str, answers: dict, marks: list, mode: str = "") -> None:
    (attempts_dir(pid) / "draft.json").write_text(
        json.dumps({"answers": answers, "marks": marks, "mode": mode, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                   ensure_ascii=False), "utf-8")


def load_draft_answers(pid: str) -> dict | None:
    p = attempts_dir(pid) / "draft.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def submit_attempt(pid: str, answers: dict, marks: list, unanswered: list, rows: list) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    (attempts_dir(pid) / f"{ts}.json").write_text(
        json.dumps({"id": ts, "paper_id": pid, "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "answers": answers, "marks": marks, "unanswered": unanswered, "rows": rows}, ensure_ascii=False, indent=1), "utf-8")
    d = attempts_dir(pid) / "draft.json"
    if d.exists():
        d.unlink()
    return ts


def load_attempt(pid: str, ts: str) -> dict | None:
    p = attempts_dir(pid) / f"{SAFE_RE.sub('', ts)}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def list_attempts(pid: str) -> list[dict]:
    out = []
    for p in sorted(attempts_dir(pid).glob("*.json"), reverse=True):
        if p.name == "draft.json":
            continue
        try:
            d = json.loads(p.read_text("utf-8"))
            out.append({"id": d["id"], "submitted_at": d["submitted_at"], "answered": len([r for r in d["rows"] if r["answer"]]),
                        "total": len(d["rows"])})
        except Exception:
            continue
    return out
