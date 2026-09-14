@echo off
chcp 65001 >nul
REM PaperType 纸卷上机：不打包、直接从源码运行。首次双击会自动建虚拟环境并装依赖（需联网，几分钟），之后秒开。
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 python。请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/windows/
  echo        安装时务必勾选 "Add python.exe to PATH"，装完后重新双击本文件。
  pause
  exit /b 1
)

if not exist .venv (
  echo 首次运行：正在创建虚拟环境并安装依赖，请稍候……
  python -m venv .venv || goto :fail
  .venv\Scripts\python -m pip install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
  .venv\Scripts\python -m pip install -q -e . -i https://pypi.tuna.tsinghua.edu.cn/simple || goto :fail
  echo 依赖安装完成。
)

.venv\Scripts\python run_papertype.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo [错误] 启动失败，请把上面的报错内容截图。常见原因：网络不通导致依赖没装完（删掉 .venv 文件夹后重试）。
pause
exit /b 1
