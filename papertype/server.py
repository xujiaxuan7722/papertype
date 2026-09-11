"""FastAPI 本地服务：导入、校正、作答、汇总、设置、大模型任务。只监听 127.0.0.1。"""
from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, export, pipeline
from .llm import client as llm_client
from .llm import tasks as llm_tasks
from .models import Paper, Question
from .parser.validate import validate
from .store import files as store

app = FastAPI(title="PaperType")
STATIC = Path(__file__).parent / "web" / "static"
JOBS: dict[str, dict] = {}


def _get(kind: str, pid: str) -> Paper:
    p = store.load_paper(pid, kind)
    if not p:
        raise HTTPException(404, "试卷不存在")
    return p


# ---------- 列表 ----------

@app.get("/api/papers")
def papers():
    return {"papers": store.list_papers("papers"), "drafts": store.list_papers("drafts")}


# ---------- 导入 ----------

@app.post("/api/import")
async def do_import(mode: str = Form(...), title: str = Form(""), text: str = Form(""),
                    files: list[UploadFile] = File(default=[])):
    tmp = config.data_dir() / "tmp" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        if not f.filename:
            continue
        dst = tmp / Path(f.filename).name
        dst.write_bytes(await f.read())
        saved.append(dst)
    try:
        if mode == "file":
            if len(saved) != 1:
                raise pipeline.ImportError_("「导入文件」一次只收一份 Word 或 PDF。")
            paper = pipeline.import_file(saved[0], title or None)
        elif mode == "ocr":
            paper = pipeline.import_ocr(saved, title or None)
        elif mode == "text":
            paper = pipeline.import_text(text, title or None)
        else:
            raise pipeline.ImportError_("未知的导入方式")
    except pipeline.ImportError_ as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    store.save_paper(paper, "drafts")
    return {"paper": paper.to_dict(), "stats": pipeline.stats(paper)}


# ---------- 草稿 / 试卷 ----------

class PaperIn(BaseModel):
    title: str | None = None
    units: list[str] | None = None
    questions: list[dict]


def _apply(paper: Paper, body: PaperIn) -> Paper:
    if body.title is not None:
        paper.title = body.title.strip()[:80]
    qs = []
    for d in body.questions:
        d = {k: v for k, v in d.items() if k in Question.__dataclass_fields__}
        d["issues"] = []
        q = Question(**d)
        q.options = [str(o) for o in q.options]
        q.blanks = int(q.blanks or 0)
        if q.type == "blank":
            q.blanks = max(1, q.blanks)
        qs.append(q)
    paper.questions = qs
    units = []
    for q in qs:
        if q.unit and q.unit not in units:
            units.append(q.unit)
    paper.units = body.units or units
    validate(paper.questions)
    return paper


@app.get("/api/{kind}/{pid}")
def get_paper(kind: str, pid: str):
    _kind(kind)
    p = _get(kind, pid)
    return {"paper": p.to_dict(), "stats": pipeline.stats(p), "llm": config.llm_available()}


@app.put("/api/{kind}/{pid}")
def put_paper(kind: str, pid: str, body: PaperIn):
    _kind(kind)
    p = _apply(_get(kind, pid), body)
    store.save_paper(p, kind)
    return {"paper": p.to_dict(), "stats": pipeline.stats(p)}


@app.delete("/api/{kind}/{pid}")
def del_paper(kind: str, pid: str):
    _kind(kind)
    store.delete_paper(pid, kind)
    if kind == "papers" or not store.load_paper(pid, "papers"):
        shutil.rmtree(store.assets_dir(pid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/drafts/{pid}/confirm")
def confirm(pid: str, body: PaperIn | None = None):
    p = _get("drafts", pid)
    if body is not None:
        p = _apply(p, body)
    for q in p.questions:            # 校正页确认 = 全部视为已核对
        q.reviewed, q.issues = True, []
    store.save_paper(p, "papers")
    store.delete_paper(pid, "drafts")
    return {"id": p.id}


@app.post("/api/papers/{pid}/reopen")
def reopen(pid: str):
    p = _get("papers", pid)
    store.save_paper(p, "drafts")
    return {"id": p.id}


def _kind(kind: str):
    if kind not in ("papers", "drafts"):
        raise HTTPException(404)


@app.get("/assets/{pid}/{name}")
def asset(pid: str, name: str):
    f = store.assets_dir(pid) / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f))


@app.get("/api/papers/{pid}/export.xlsx")
def export_paper(pid: str):
    p = _get("papers", pid)
    return Response(export.paper_to_xlsx(p), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="paper-{pid}.xlsx"'})


# ---------- 作答 ----------

class AnswersIn(BaseModel):
    answers: dict
    marks: list[str] = []
    mode: str = ""


@app.get("/api/papers/{pid}/answers")
def get_answers(pid: str):
    _get("papers", pid)
    return store.load_draft_answers(pid) or {"answers": {}, "marks": [], "mode": ""}


@app.put("/api/papers/{pid}/answers")
def put_answers(pid: str, body: AnswersIn):
    _get("papers", pid)
    store.save_draft_answers(pid, body.answers, body.marks, body.mode)
    return {"ok": True}


@app.post("/api/papers/{pid}/check")
def check(pid: str, body: AnswersIn):
    p = _get("papers", pid)
    rows, unanswered = export.summary_rows(p, body.answers, body.marks)
    return {"unanswered": unanswered, "total": len(rows)}


@app.post("/api/papers/{pid}/submit")
def submit(pid: str, body: AnswersIn):
    p = _get("papers", pid)
    rows, unanswered = export.summary_rows(p, body.answers, body.marks)
    ts = store.submit_attempt(pid, body.answers, body.marks, unanswered, rows)
    return {"id": ts, "rows": rows, "unanswered": unanswered}


@app.get("/api/papers/{pid}/attempts")
def attempts(pid: str):
    _get("papers", pid)
    return {"attempts": store.list_attempts(pid)}


@app.get("/api/papers/{pid}/attempts/{ts}")
def attempt(pid: str, ts: str):
    a = store.load_attempt(pid, ts)
    if not a:
        raise HTTPException(404)
    return a


@app.get("/api/papers/{pid}/attempts/{ts}/export.xlsx")
def attempt_xlsx(pid: str, ts: str):
    p = _get("papers", pid)
    a = store.load_attempt(pid, ts)
    if not a:
        raise HTTPException(404)
    return Response(export.to_xlsx(p, a["rows"]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="answers-{pid}-{ts}.xlsx"'})


# ---------- 设置 / 大模型 ----------

@app.get("/api/settings")
def get_settings():
    s = config.load_settings()
    s["llm_api_key"] = ("*" * 6 + s["llm_api_key"][-4:]) if s["llm_api_key"] else ""
    s["llm_available"] = config.llm_available()
    return s


class SettingsIn(BaseModel):
    llm_enabled: bool | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    app_window: bool | None = None


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    d = {k: v for k, v in body.model_dump().items() if v is not None}
    if "llm_api_key" in d and d["llm_api_key"].startswith("******"):
        d.pop("llm_api_key")           # 掩码原样传回 = 不改
    config.save_settings(d)
    return get_settings()


@app.post("/api/settings/ping")
def ping():
    return llm_client.ping()


class LLMJobIn(BaseModel):
    scope: str          # flagged / keys / all / ocr_tidy
    keys: list[str] = []


@app.post("/api/{kind}/{pid}/llm")
def llm_job(kind: str, pid: str, body: LLMJobIn):
    _kind(kind)
    if not config.llm_available():
        raise HTTPException(400, "大模型未启用：请先在设置里打开开关并填写密钥。")
    p = _get(kind, pid)
    flagged = [q.key() for q in p.questions if not q.reviewed]
    if body.scope == "keys":
        flagged = [k for k in body.keys if any(q.key() == k for q in p.questions)]
        if not flagged:
            raise HTTPException(400, "没有指定要重切的题。")
    if body.scope == "flagged" and not flagged:
        raise HTTPException(400, "没有待核对的题。")
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"done": False, "progress": "0/1", "error": None, "result": None, "cancelled": False}

    def run():
        try:
            if body.scope in ("flagged", "keys"):
                text = llm_tasks.raw_span_text(p, flagged)
                mode = "ocr_tidy" if p.import_path == "ocr" else "rechunk"
            else:
                text = p.raw_text or llm_tasks.questions_to_text(p)
                mode = "ocr_tidy" if body.scope == "ocr_tidy" else "rechunk"
            out = llm_tasks.rewrite(text, mode, progress=lambda i, n: JOBS[job_id].update(progress=f"{i}/{n}"))
            if JOBS[job_id]["cancelled"]:
                JOBS[job_id].update(done=True, error="已取消，试卷未改动")
                return
            newqs = llm_tasks.parse_model_output(out, p.import_path)
            if body.scope in ("flagged", "keys"):
                by = {(q.unit, q.no): q for q in newqs}
                by_no = {q.no: q for q in newqs}
                replaced = 0
                for i, q in enumerate(p.questions):
                    if q.key() in flagged:
                        n = by.get((q.unit, q.no)) or by_no.get(q.no)
                        if n:
                            n.unit, n.crop, n.image = q.unit, q.crop, (q.image if n.image else q.image)
                            n.page, n.y0, n.end_page, n.y1 = q.page, q.y0, q.end_page, q.y1
                            n.group, n.material, n.material_crop, n.m_page, n.m_y0 = q.group, q.material, q.material_crop, q.m_page, q.m_y0
                            p.questions[i] = n; replaced += 1
                validate(p.questions)
                for q in p.questions:
                    if not q.reviewed and "大模型产出" in " ".join(q.issues):
                        pass
                msg = f"重切了 {replaced} 道待核对题"
            else:
                new = pipeline.reparse_text(p, out)
                p.questions, p.units = new.questions, new.units
                for q in p.questions:
                    q.reviewed = False
                    q.issues = list(dict.fromkeys(q.issues + ["大模型产出，需人工核对"]))
                msg = f"整卷重切，共 {len(p.questions)} 题"
            store.save_paper(p, kind)
            JOBS[job_id].update(done=True, result={"message": msg, "stats": pipeline.stats(p)})
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:300] or repr(e)[:300]
            JOBS[job_id].update(done=True, error=msg)
            try:
                import time as _t
                with open(config.data_dir() / "llm.log", "a", encoding="utf-8") as f:
                    f.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')} job={job_id} scope={body.scope} paper={pid} ERROR {msg}\n")
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()
    return {"job": job_id}


@app.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404)
    j["cancelled"] = True
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404)
    return j


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
