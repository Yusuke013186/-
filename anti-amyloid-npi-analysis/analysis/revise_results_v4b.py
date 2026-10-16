# -*- coding: utf-8 -*-
"""【結果】を「…低下例が」までは上野先生版（空欄補充済み）のまま残し、
その先を症例ごとに区切って低下例2例→非低下例2例の順に示す。

【演題名】【目的】【方法】【結論】と【結果】の末尾の一文は原本のまま。
数値は元データから組み立て、手入力しない。
"""
from __future__ import annotations

import html
import re
import sys
import zipfile
from xml.sax.saxutils import escape

from npi_increase_analysis import build_cases, read_background

PIVOT = "時間見当識／MMSE／CDR-SB（初回→追跡時）は，低下例が"
TAIL = "時間見当識は低下2例で上昇し，非低下2例では上昇しなかったが，MMSEとCDR-SBの変化は一様でなかった．"


def text(p):
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))


def case_block() -> str:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    four = [c for c in inc if c.npi_bl.score >= 1]
    dec = sorted([c for c in four if c.npi_fu.score < c.npi_bl.score], key=lambda c: int(c.pid[1:]))
    # 非低下例は、前の文「非低下2例は2→3点，1→3点」と同じ順に並べる
    non = sorted([c for c in four if c.npi_fu.score >= c.npi_bl.score], key=lambda c: -c.npi_bl.score)

    def trip(c):
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        return f"{tb:g}→{tf:g}／{mb:g}→{mf:g}／{cb:.1f}→{cf:.1f}"

    def seg(group):
        return "，".join(f"{i}例目（{BG[c.pid]['年齢']:g}歳）で{trip(c)}"
                         for i, c in enumerate(group, 1))

    return seg(dec) + "，非低下例が" + seg(non) + "であった．"


def main(filled: str, tpl: str, out: str) -> None:
    # 前半は「空欄補充版」の【結果】から PIVOT までをそのまま切り出す
    xf = zipfile.ZipFile(filled).read("word/document.xml").decode("utf-8")
    res_f = text([p for p in re.findall(r"<w:p[ >].*?</w:p>", xf, re.S) if "【結果】" in text(p)][0])
    body_f = res_f[len("【結果】"):]
    assert body_f.count(PIVOT) == 1 and body_f.endswith(TAIL)
    head = body_f[: body_f.index(PIVOT) + len(PIVOT)]
    body = head + case_block() + TAIL

    zin = zipfile.ZipFile(tpl)
    x = zin.read("word/document.xml").decode("utf-8")
    p = [q for q in re.findall(r"<w:p[ >].*?</w:p>", x, re.S) if "【結果】" in text(q)][0]
    SZ = '<w:sz w:val="28"/><w:szCs w:val="28"/>'
    new = (re.match(r"<w:p[^>]*>", p).group(0)
           + re.search(r"<w:pPr>.*?</w:pPr>", p, re.S).group(0)
           + f'<w:r w:rsidRPr="004C1276"><w:rPr><w:rStyle w:val="ac"/>{SZ}</w:rPr><w:t>【結果】</w:t></w:r>'
           + f'<w:r w:rsidRPr="004C1276"><w:rPr>{SZ}</w:rPr><w:br/></w:r>'
           + f'<w:r><w:rPr><w:rFonts w:hint="eastAsia"/>{SZ}</w:rPr>'
           + f'<w:t xml:space="preserve">{escape(body)}</w:t></w:r></w:p>')
    y = x.replace(p, new, 1)
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        zout.writestr(item, y.encode("utf-8") if item.filename == "word/document.xml"
                      else zin.read(item.filename))
    zout.close()
    print(body)
    print(f"\n【結果】{len(body)}字 → {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
