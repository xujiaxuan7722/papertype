"""运行配置：数据目录、设置文件（大模型开关与密钥）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def base_dir() -> Path:
    """exe 所在目录（打包后）或仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = Path(os.environ.get("PAPERTYPE_DATA", base_dir() / "data"))
    for sub in ("papers", "drafts", "attempts", "assets", "tmp"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_SETTINGS = {
    "llm_enabled": False,
    "llm_base_url": "https://token.sensenova.cn/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-v4-flash",
    "app_window": False,
}


def load_settings() -> dict:
    p = data_dir() / "settings.json"
    if p.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(p.read_text("utf-8"))}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> dict:
    cur = load_settings()
    cur.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
    (data_dir() / "settings.json").write_text(json.dumps(cur, ensure_ascii=False, indent=2), "utf-8")
    return cur


def llm_available() -> bool:
    s = load_settings()
    return bool(s["llm_enabled"] and s["llm_api_key"].strip())
