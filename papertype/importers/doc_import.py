"""Word 97-2003 二进制 .doc 导入：纯 Python 读正文与段落自动编号（MS-DOC 规范），不依赖 Word/WPS/LibreOffice。

能拿到：正文文本、软回车分行、表格按行展开、Word 自动编号还原成「N. 」题号、内置标题样式。
拿不到：内嵌图片、下划线格式的空位（.doc 里藏在字符属性表中，暂不解析）。
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import olefile

from ..models import Line
from .docx_import import BLANK_RUN_RE

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

SPRM_PISTD = 0x4600
SPRM_PILVL = 0x260A
SPRM_PILFO = 0x460B
SPRM_PFINTABLE = 0x2416
SPRM_PFTTP = 0x2417
SPRM_PHUGEPAPX = 0x6646     # 段落属性太大（表格行结束标记常见）时放在 Data 流里
_SPRA_SIZE = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}
_DECIMAL_NFC = {0x00, 0x16}       # 阿拉伯数字 / 前导零
_NONE_NFC = 0xFF


def is_doc(path: str | Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == OLE_MAGIC
    except OSError:
        return False


class _Doc:
    def __init__(self, path: str | Path):
        ole = olefile.OleFileIO(str(path))
        try:
            if not ole.exists("WordDocument"):
                raise ValueError("不是 Word 文档（OLE 包里没有 WordDocument 流）")
            self.wd = ole.openstream("WordDocument").read()
            flags = struct.unpack_from("<H", self.wd, 0x0A)[0]
            name = "1Table" if flags & 0x0200 else "0Table"
            self.table = ole.openstream(name).read() if ole.exists(name) else b""
            self.data = ole.openstream("Data").read() if ole.exists("Data") else b""
        finally:
            ole.close()
        self.ccp_text = struct.unpack_from("<i", self.wd, 0x4C)[0]
        self.pieces = self._pieces()

    def _fclcb(self, index: int) -> tuple[int, int]:
        """FibRgFcLcb97 第 index 对 (fc, lcb)。"""
        return struct.unpack_from("<Ii", self.wd, 0x9A + 8 * index)

    # ---- 片表：CP → 文本 / FC ----
    def _pieces(self) -> list[tuple[int, int, int, bool]]:
        """[(cp_start, cp_end, fc, compressed)]"""
        fc, lcb = self._fclcb(33)
        clx = self.table[fc:fc + lcb]
        pos = 0
        while pos < len(clx) and clx[pos] == 0x01:
            pos += 3 + struct.unpack_from("<H", clx, pos + 1)[0]
        if pos >= len(clx) or clx[pos] != 0x02:
            raise ValueError("片表损坏")
        plcb = struct.unpack_from("<I", clx, pos + 1)[0]
        pos += 5
        n = (plcb - 4) // 12
        cps = struct.unpack_from("<%dI" % (n + 1), clx, pos)
        pos += 4 * (n + 1)
        out = []
        for i in range(n):
            _, fcv, _ = struct.unpack_from("<HIH", clx, pos + 8 * i)
            out.append((cps[i], cps[i + 1], fcv & 0x3FFFFFFF, bool(fcv & 0x40000000)))
        return out

    def text(self) -> str:
        parts = []
        for cp0, cp1, fc, comp in self.pieces:
            n = cp1 - cp0
            if comp:
                parts.append(self.wd[fc // 2: fc // 2 + n].decode("cp1252", "replace"))
            else:
                parts.append(self.wd[fc: fc + 2 * n].decode("utf-16-le", "replace"))
        return "".join(parts)[: self.ccp_text]

    def cp_to_fc(self, cp: int) -> int:
        for cp0, cp1, fc, comp in self.pieces:
            if cp0 <= cp < cp1:
                return fc + (cp - cp0) if comp else fc + 2 * (cp - cp0)
        return -1

    # ---- 段落属性：FC → (istd, ilfo, ilvl) ----
    def paragraph_props(self) -> list[tuple[int, int, dict]]:
        """[(fc_start, fc_end, {"istd","ilfo","ilvl"})]，来自 PlcfBtePapx → PAPX FKP。"""
        fc, lcb = self._fclcb(13)
        plc = self.table[fc:fc + lcb]
        if lcb < 8:
            return []
        n = (lcb - 4) // 8
        pns = struct.unpack_from("<%dI" % n, plc, 4 * (n + 1))
        out = []
        for pn in pns:
            page = self.wd[(pn & 0x3FFFFF) * 512:(pn & 0x3FFFFF) * 512 + 512]
            if len(page) < 512:
                continue
            crun = page[511]
            rgfc = struct.unpack_from("<%dI" % (crun + 1), page, 0)
            for i in range(crun):
                boff = page[4 * (crun + 1) + 13 * i]
                props = {"istd": 0, "ilfo": 0, "ilvl": 0, "intable": False, "ttp": False}
                if boff:
                    p = boff * 2
                    cb = page[p]
                    if cb == 0:
                        grp = page[p + 2: p + 2 + page[p + 1] * 2]
                    else:
                        grp = page[p + 1: p + 1 + cb * 2 - 1]
                    if len(grp) >= 2:
                        props["istd"] = struct.unpack_from("<H", grp, 0)[0]
                        self._read_sprms(grp[2:], props, self.data)
                out.append((rgfc[i], rgfc[i + 1], props))
        out.sort(key=lambda t: t[0])
        return out

    @staticmethod
    def _read_sprms(grp: bytes, props: dict, data: bytes = b"") -> None:
        pos = 0
        while pos + 2 <= len(grp):
            sprm = struct.unpack_from("<H", grp, pos)[0]
            pos += 2
            spra = sprm >> 13
            if spra == 6:
                if sprm == 0xD608:
                    size = struct.unpack_from("<H", grp, pos)[0]; pos += 2
                else:
                    size = grp[pos] if pos < len(grp) else 0; pos += 1
            else:
                size = _SPRA_SIZE[spra]
            if sprm == SPRM_PILFO and size == 2:
                props["ilfo"] = struct.unpack_from("<H", grp, pos)[0]
            elif sprm == SPRM_PILVL and size == 1:
                props["ilvl"] = grp[pos]
            elif sprm == SPRM_PISTD and size == 2:
                props["istd"] = struct.unpack_from("<H", grp, pos)[0]
            elif sprm == SPRM_PFINTABLE and size == 1:
                props["intable"] = bool(grp[pos])
            elif sprm == SPRM_PFTTP and size == 1:
                props["ttp"] = bool(grp[pos])
            elif sprm == SPRM_PHUGEPAPX and size == 4 and data:
                off = struct.unpack_from("<I", grp, pos)[0]
                if off + 2 <= len(data):
                    cb = struct.unpack_from("<H", data, off)[0]
                    _Doc._read_sprms(data[off + 2: off + 2 + cb], props, b"")
            pos += size

    # ---- 列表定义：ilfo → 各级 (nfc, start) ----
    def list_formats(self) -> dict[int, dict[int, tuple[int, int]]]:
        """{ilfo(1 起): {ilvl: (nfc, iStartAt)}}，LFO 级别覆盖优先。"""
        lst: dict[int, list[tuple[int, int]]] = {}
        fc, lcb = self._fclcb(73)
        buf = self.table[fc:fc + lcb]
        if len(buf) >= 2:
            c = struct.unpack_from("<H", buf, 0)[0]
            pos = 2
            heads = []
            for _ in range(c):
                lsid = struct.unpack_from("<i", buf, pos)[0]
                simple = bool(buf[pos + 26] & 0x01)
                heads.append((lsid, 1 if simple else 9))
                pos += 28
            for lsid, nlvl in heads:
                levels = []
                for _ in range(nlvl):
                    if pos + 28 > len(buf):
                        break
                    start = struct.unpack_from("<i", buf, pos)[0]
                    nfc = buf[pos + 4]
                    cb_chpx, cb_papx = buf[pos + 24], buf[pos + 25]
                    pos += 28 + cb_papx + cb_chpx
                    cch = struct.unpack_from("<H", buf, pos)[0] if pos + 2 <= len(buf) else 0
                    pos += 2 + 2 * cch
                    levels.append((nfc, start))
                lst[lsid] = levels
        result: dict[int, dict[int, tuple[int, int]]] = {}
        fc, lcb = self._fclcb(74)
        buf = self.table[fc:fc + lcb]
        if len(buf) < 4:
            return result
        n = struct.unpack_from("<i", buf, 0)[0]
        pos = 4
        lfos = []
        for _ in range(n):
            lsid = struct.unpack_from("<i", buf, pos)[0]
            lfos.append((lsid, buf[pos + 12]))
            pos += 16
        for i, (lsid, clfolvl) in enumerate(lfos):
            levels = {j: v for j, v in enumerate(lst.get(lsid, []))}
            for _ in range(clfolvl):
                if pos + 8 > len(buf):
                    break
                start = struct.unpack_from("<i", buf, pos)[0]
                fl = buf[pos + 4]
                ilvl, f_start, f_fmt = fl & 0x0F, bool(fl & 0x10), bool(fl & 0x20)
                pos += 8
                nfc = levels.get(ilvl, (0, 1))[0]
                if f_fmt and pos + 28 <= len(buf):
                    nfc = buf[pos + 4]
                    cb_chpx, cb_papx = buf[pos + 24], buf[pos + 25]
                    pos += 28 + cb_papx + cb_chpx
                    cch = struct.unpack_from("<H", buf, pos)[0] if pos + 2 <= len(buf) else 0
                    pos += 2 + 2 * cch
                if f_start:
                    levels[ilvl] = (nfc, start)
                elif f_fmt:
                    levels[ilvl] = (nfc, levels.get(ilvl, (0, 1))[1])
            result[i + 1] = levels
        return result


def _clean(s: str) -> str:
    s = re.sub("\x13[^\x14\x15]*\x14", "", s).replace("\x15", "")   # 域：只留结果
    s = re.sub("\x13[^\x15]*\x15", "", s)
    s = s.replace("\x1e", "-").replace("\x1f", "")
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", s).strip()


def extract_lines(doc_path: str | Path) -> list[Line]:
    d = _Doc(doc_path)
    text = d.text()
    props = d.paragraph_props()
    fmts = d.list_formats()
    counters: dict[tuple[int, int], int] = {}

    def props_at(cp: int) -> dict:
        fc = d.cp_to_fc(cp)
        lo, hi = 0, len(props) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            a, b, p = props[mid]
            if fc < a:
                hi = mid - 1
            elif fc >= b:
                lo = mid + 1
            else:
                return p
        return {"istd": 0, "ilfo": 0, "ilvl": 0, "intable": False, "ttp": False}

    out: list[Line] = []
    cell_buf: list[str] = []      # 当前单元格里已结束的段落
    row_cells: list[str] = []     # 当前表格行里已结束的单元格
    y = 0.0
    start = 0
    n = len(text)
    i = 0
    while i <= n:
        ch = text[i] if i < n else "\r"
        if ch in ("\r", "\x07") or i == n:
            para = text[start:i]
            p = props_at(i if i < n else max(n - 1, 0))
            pieces = [t for t in (_clean(t) for t in para.split("\x0b")) if t]
            if ch == "\x07" or p["intable"]:
                # 表格：单元格内的段落攒进 cell_buf，0x07 结束一个单元格；带 fTtp 的 0x07 是行结束
                if ch == "\x07" and p["ttp"]:
                    if any(row_cells):
                        flat = "  ".join(c.replace("\n", " ") for c in row_cells if c)
                        out.append(Line(text=flat, page=1, y=y, x=10.0, height=1.0, source="docx", cells=list(row_cells)))
                        y += 1
                    row_cells, cell_buf = [], []
                elif ch == "\x07":
                    cell_buf.extend(pieces)
                    row_cells.append("\n".join(cell_buf))
                    cell_buf = []
                else:
                    cell_buf.extend(pieces)
                start = i + 1
                i += 1
                continue
            number = None
            ilfo, ilvl = p["ilfo"], p["ilvl"]
            if ilfo and ilfo != 0xF801:
                nfc, st = fmts.get(ilfo, {}).get(ilvl, (0, 1))
                if nfc in _DECIMAL_NFC or nfc == _NONE_NFC:
                    counters[(ilfo, ilvl)] = counters.get((ilfo, ilvl), st - 1) + 1
                    number = counters[(ilfo, ilvl)]
                    if nfc == _NONE_NFC:
                        number = None
            heading = 1 <= p["istd"] <= 9
            for k, t in enumerate(pieces):
                if k == 0 and number is not None and not re.match(r"^\d+\s*[\.．、]", t):
                    t = f"{number}. {t}"
                out.append(Line(text=t, page=1, y=y, x=10.0, height=1.0, source="docx",
                                number=number if k == 0 else None,
                                blanks=len(BLANK_RUN_RE.findall(t)), is_heading=heading and k == 0))
                y += 1
            start = i + 1
        i += 1
    return out
