"""OpenAI 兼容接口客户端（商汤网关）。直连，不走系统代理。"""
from __future__ import annotations

import httpx

from ..config import load_settings, llm_available


class LLMDisabled(Exception):
    pass


def chat(messages: list[dict], temperature: float = 0.0, timeout: float = 120.0) -> str:
    if not llm_available():
        raise LLMDisabled("大模型未启用或未填写密钥")
    s = load_settings()
    url = s["llm_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {s['llm_api_key'].strip()}", "Content-Type": "application/json"}
    body = {"model": s["llm_model"], "messages": messages, "temperature": temperature, "stream": False}
    with httpx.Client(timeout=timeout, trust_env=False) as c:
        r = c.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


def ping() -> dict:
    try:
        out = chat([{"role": "user", "content": "只回复：OK"}], timeout=30)
        return {"ok": True, "reply": out[:50]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
