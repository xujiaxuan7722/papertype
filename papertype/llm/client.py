"""OpenAI 兼容接口客户端（商汤网关）。直连，不走系统代理。"""
from __future__ import annotations

import time

import httpx

from ..config import load_settings, llm_available


class LLMDisabled(Exception):
    pass


def chat(messages: list[dict], temperature: float = 0.0, timeout: float = 240.0) -> str:
    if not llm_available():
        raise LLMDisabled("大模型未启用或未填写密钥")
    s = load_settings()
    url = s["llm_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {s['llm_api_key'].strip()}", "Content-Type": "application/json"}
    body = {"model": s["llm_model"], "messages": messages, "temperature": temperature, "stream": False}
    delays = [3, 6, 12, 20, 30]           # 429 / 5xx 退避重试（商汤 Token Plan 有并发与频率限制）
    with httpx.Client(timeout=timeout, trust_env=False) as c:
        for attempt in range(len(delays) + 1):
            r = c.post(url, headers=headers, json=body)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            if r.status_code == 429:
                raise RuntimeError("网关限流（429）：请求太频繁或并发过多，请稍等一两分钟再试")
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
    raise RuntimeError("网关无响应")


def ping() -> dict:
    try:
        out = chat([{"role": "user", "content": "只回复：OK"}], timeout=30)
        return {"ok": True, "reply": out[:50]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
