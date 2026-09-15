@echo off
chcp 65001 >nul
REM PaperType 纸卷上机：不打包、直接从源码运行。首次双击会自动建虚拟环境并装依赖（需联网，几分钟），之后秒开。
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 没找到 python。请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/windows/
    echo        安装时务必勾选 "Add python.exe to PATH"，装完后重新双击本文件。
    pause
    exit /b 1
  )
  echo 正在创建虚拟环境……
  python -m venv .venv || goto :fail
)

REM 每次都检查依赖是否真的装齐（上次中断过也能自动补装）
.venv\Scripts\python -c "import uvicorn, fastapi, pymupdf, docx, rapidocr, olefile, openpyxl, httpx, PIL" >nul 2>nul
if errorlevel 1 call :install
if errorlevel 1 goto :fail

.venv\Scripts\python run_papertype.py
if errorlevel 1 goto :fail
exit /b 0

:install
echo 正在安装依赖（几分钟，请勿关闭窗口）。依次尝试阿里云 / 清华 / 腾讯云 / 官方源……
for %%m in (https://mirrors.aliyun.com/pypi/simple/ https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.cloud.tencent.com/pypi/simple https://pypi.org/simple) do (
  echo.
  echo ===== 尝试镜像 %%m =====
  .venv\Scripts\python -m pip install -e . -i %%m
  if not errorlevel 1 (
    .venv\Scripts\python -c "import uvicorn, fastapi, pymupdf, docx, rapidocr, olefile, openpyxl, httpx, PIL" && echo 依赖安装完成。 && exit /b 0
  )
)
echo [错误] 所有镜像都没装成。若开着 VPN、WARP 或代理软件，请先关掉再重试。
exit /b 1

:fail
echo.
echo [错误] 启动失败，请把上面的报错内容截图。
pause
exit /b 1
