@echo off
chcp 65001 >nul
REM 不打包、直接从源码运行（需已装 Python 3.11+）：首次会自动建虚拟环境并装依赖
cd /d %~dp0
if not exist .venv (python -m venv .venv && .venv\Scripts\pip install -q -e .)
.venv\Scripts\python run_papertype.py
