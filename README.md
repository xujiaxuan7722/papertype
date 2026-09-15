# PaperType（纸卷上机）

把一份 Word、PDF 或图片试卷变成能在电脑上作答的电子卷，练机考手感。只汇总答案，不判分、不倒计时，一人在 Windows 笔记本上单机使用。

方案全文见 `docs/最终方案-2026-09-11.md`。

## 运行

**从源码运行（本机或 Windows 装了 Python 3.11+）：**

```
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
python run_papertype.py             # 自动打开系统默认浏览器
```

Windows 上直接双击 `run_papertype.bat`：首次会自动建虚拟环境并从清华镜像装依赖（需联网，几分钟），之后每次秒开。

**搬到另一台 Windows 电脑：** 装好 Python 3.11+（安装时勾选 Add to PATH），把整个仓库文件夹拷过去（或 `git clone`），双击 `run_papertype.bat`。已导入的试卷和作答记录都在 `data/` 目录，一起拷走即可延续。

**打成 exe（在 Windows 上执行一次）：** 双击 `build_windows.bat`，产物在 `dist\PaperType\`，把整个文件夹拷到笔记本，双击 `PaperType.exe`。数据（试卷、作答记录、裁图、设置）都在 exe 旁边的 `data\` 目录里。

浏览器没有自动弹出时，黑窗口里会打印地址，复制到浏览器打开即可。

## 用法

1. **导入**：三个入口二选一——「导入文件」收 Word（.doc / .docx）/ PDF，一次可选多份，每份各成一份试卷并列出结果；「OCR 识图」收图片和扫描件（本机离线识别）；「粘贴文本」收豆包等转出的文本。
2. **校正**：识别结果逐题可改题型、题干、选项、空数；待核对的题标红置顶；每题有原文裁图对照。确认后生成试卷。
3. **作答**：整卷预览和分题作答两种模式共用一份作答记录，切换不丢。数字键选选项、Enter 下一题、M 标记。
4. **提交**：先提示未作答题号，可返回补做；提交后得到「单元 / 题号 / 题型 / 我的答案」表，可一键复制、导出 Excel。

**大模型**（可选）：设置页打开开关并填商汤网关密钥后，校正页多出三个手动按钮：标红题重切、整卷重切、OCR 整理。默认关闭，关闭时程序不发任何外部请求。

## 项目结构

```
papertype/
  importers/   doc（Word 97-2003 二进制，纯 Python 读正文与自动编号）/ docx / pdf（文字层）/ ocr / text 五个导入器，统一输出带坐标的文本行
  parser/      规则切题（题号、选项、题型、材料分组、答案剥离）与校验
  llm/         OpenAI 兼容客户端与三种整理任务
  store/       试卷 / 草稿 / 作答记录 JSON 文件
  pipeline.py  导入管线：导入 → 切题 → 裁图 → 草稿
  server.py    FastAPI 本地接口
  web/static/  前端（无框架）
tests/         两份银行真题 + 两张截图作为回归用例
```

## 测试

```
.venv/bin/python -m pytest -q
```
