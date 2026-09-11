"""端到端：导入 → 校正 → 生成试卷 → 作答 → 提交 → 汇总导出（阶段 4 验收）。"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["PAPERTYPE_DATA"] = str(tmp_path_factory.mktemp("data"))
    from papertype.server import app
    with TestClient(app) as c:
        yield c


def test_import_pdf_review_confirm_take_submit(client):
    with open(FIX / "icbc.pdf", "rb") as f:
        r = client.post("/api/import", data={"mode": "file", "title": ""}, files=[("files", ("icbc.pdf", f, "application/pdf"))])
    assert r.status_code == 200, r.text
    d = r.json(); pid = d["paper"]["id"]
    assert d["stats"]["count"] == 80 and d["stats"]["with_image"] >= 6
    assert d["paper"]["questions"][23]["crop"]      # 图形题有裁图
    assert client.get(f"/assets/{pid}/{d['paper']['questions'][23]['crop']}").status_code == 200
    assert client.get("/api/papers").json()["drafts"][0]["id"] == pid

    # 校正：改一题题型，确认生成
    qs = d["paper"]["questions"]
    qs[0]["type"] = "multi"
    r = client.put(f"/api/drafts/{pid}", json={"title": "工行真题", "questions": qs})
    assert r.status_code == 200 and r.json()["paper"]["questions"][0]["type"] == "multi"
    r = client.post(f"/api/drafts/{pid}/confirm", json={"title": "工行真题", "questions": qs})
    assert r.status_code == 200
    assert client.get(f"/api/papers/{pid}").status_code == 200
    assert client.get(f"/api/drafts/{pid}").status_code == 404
    paper = client.get(f"/api/papers/{pid}").json()["paper"]
    assert all(q["reviewed"] for q in paper["questions"])
    assert "answer" not in paper["questions"][0] and "raw_text" in paper

    # 作答草稿自动保存
    k1 = f"{paper['questions'][0]['unit']}|{paper['questions'][0]['no']}"
    k2 = f"{paper['questions'][1]['unit']}|{paper['questions'][1]['no']}"
    r = client.put(f"/api/papers/{pid}/answers", json={"answers": {k1: ["A", "C"], k2: "B"}, "marks": [k2], "mode": "take"})
    assert r.status_code == 200
    assert client.get(f"/api/papers/{pid}/answers").json()["answers"][k2] == "B"

    # 提交前检查未作答
    r = client.post(f"/api/papers/{pid}/check", json={"answers": {k1: ["A", "C"], k2: "B"}, "marks": []})
    assert r.json()["total"] == 80 and len(r.json()["unanswered"]) == 78 and r.json()["unanswered"][0] == "3"

    # 提交
    r = client.post(f"/api/papers/{pid}/submit", json={"answers": {k1: ["A", "C"], k2: "B"}, "marks": [k2]})
    ts = r.json()["id"]; rows = r.json()["rows"]
    assert rows[0]["answer"] == "A C" and rows[1]["answer"] == "B" and rows[1]["marked"] and rows[2]["answer"] == ""
    assert client.get(f"/api/papers/{pid}/attempts").json()["attempts"][0]["answered"] == 2
    x = client.get(f"/api/papers/{pid}/attempts/{ts}/export.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.get(f"/api/papers/{pid}/export.xlsx").content[:2] == b"PK"
    assert client.get(f"/api/papers/{pid}/answers").json()["answers"] == {}   # 提交后草稿清空


def test_import_ocr_images(client):
    files = [("files", ("ocr2.jpeg", open(FIX / "ocr2.jpeg", "rb"), "image/jpeg")),
             ("files", ("ocr1.jpeg", open(FIX / "ocr1.jpeg", "rb"), "image/jpeg"))]
    r = client.post("/api/import", data={"mode": "ocr", "title": "样图"}, files=files)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["stats"]["count"] == 10          # 6 + 4
    qs = d["paper"]["questions"]
    assert qs[7]["image"] and qs[7]["crop"]   # 第二张图的图形推理题
    assert qs[8]["blanks"] == 2


def test_import_text_and_errors(client):
    text = "一、单选题\n\n1. 下列哪项正确？\nA. 甲\nB. 乙\nC. 丙\nD. 丁\n答案：B\n\n二、填空题\n\n2. 中国的首都是____，最大城市是____。\n"
    r = client.post("/api/import", data={"mode": "text", "text": text, "title": ""})
    assert r.status_code == 200, r.text
    qs = r.json()["paper"]["questions"]
    assert len(qs) == 2 and qs[0]["type"] == "single" and qs[0]["options"] == ["甲", "乙", "丙", "丁"]
    assert qs[1]["type"] == "blank" and qs[1]["blanks"] == 2
    assert "答案" not in qs[0]["stem"] and "B" not in "".join(qs[0]["issues"])
    r = client.post("/api/import", data={"mode": "file", "text": ""}, files=[("files", ("x.txt", b"abc", "text/plain"))])
    assert r.status_code == 400


def test_settings_and_llm_gate(client):
    s = client.get("/api/settings").json()
    assert s["llm_enabled"] is False and s["llm_available"] is False
    r = client.put("/api/settings", json={"llm_enabled": True, "llm_api_key": "sk-test-1234"})
    assert r.json()["llm_available"] is True and r.json()["llm_api_key"].endswith("1234") and r.json()["llm_api_key"].startswith("*")
    r = client.put("/api/settings", json={"llm_api_key": "******1234"})   # 掩码回传不改
    assert r.json()["llm_api_key"].endswith("1234")
    client.put("/api/settings", json={"llm_enabled": False})
    text = "1. 题\nA. a\nB. b\n"
    pid = client.post("/api/import", data={"mode": "text", "text": text}).json()["paper"]["id"]
    r = client.post(f"/api/drafts/{pid}/llm", json={"scope": "all"})
    assert r.status_code == 400 and "未启用" in r.json()["detail"]
