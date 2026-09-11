"""入口：起本地服务，打开系统默认浏览器（docs/最终方案 §8.8）。"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import webbrowser

import uvicorn

from . import config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open(url: str):
    time.sleep(1.2)
    s = config.load_settings()
    if s.get("app_window"):
        for exe in ("msedge", "chrome", "chromium", "google-chrome"):
            try:
                subprocess.Popen([exe, f"--app={url}"])
                return
            except Exception:
                continue
    webbrowser.open(url)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else _free_port()
    url = f"http://127.0.0.1:{port}/"
    print("=" * 56)
    print("  PaperType 纸卷上机 已启动")
    print(f"  浏览器没有自动打开时，请手动访问：{url}")
    print(f"  数据目录：{config.data_dir()}")
    print("  关闭本窗口即退出。")
    print("=" * 56)
    if "--no-browser" not in sys.argv:
        threading.Thread(target=_open, args=(url,), daemon=True).start()
    from .server import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
