@echo off
chcp 65001 >nul
REM PaperType Windows 打包脚本：在 Windows 上装好 Python 3.11+ 后双击运行，产物在 dist\PaperType\
cd /d %~dp0
if not exist .venv (python -m venv .venv)
call .venv\Scripts\activate
pip install -q -e . pyinstaller
set OCR_MODELS=
for /f "delims=" %%i in ('python -c "import rapidocr,os;print(os.path.dirname(rapidocr.__file__))"') do set RAPID=%%i
pyinstaller --noconfirm --clean --name PaperType --icon NONE ^
  --add-data "papertype\web\static;papertype\web\static" ^
  --add-data "%RAPID%\models;rapidocr\models" ^
  --add-data "%RAPID%\config.yaml;rapidocr" ^
  --collect-all rapidocr --collect-all onnxruntime --collect-all pymupdf ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on ^
  run_papertype.py
echo.
echo 打包完成：dist\PaperType\PaperType.exe  （整个 dist\PaperType 文件夹一起拷走，data 目录会在 exe 旁自动生成）
pause
