# -*- coding: utf-8 -*-
"""上野先生修正版の【結果】を、4例を1例ずつ区切って書く形に改める。

【演題名】【目的】【方法】【結論】は原本のまま残す。
【結果】の数値は元データから組み立て、手入力しない。
"""
from __future__ import annotations

import re
import sys
import zipfile
from xml.sax.saxutils import escape

from npi_increase_analysis import build_cases, read_background


def results_text() -> str:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    dec_all = [c for c in inc if c.npi_fu.score < c.npi_bl.score]
    same = [c for c in inc if c.npi_fu.score == c.npi_bl.score]
    up = [c for c in inc if c.npi_fu.score > c.npi_bl.score]
    four = [c for c in inc if c.npi_bl.score >= 1]
    dec = sorted([c for c in four if c.npi_fu.score < c.npi_bl.score], key=lambda c: int(c.pid[1:]))
    non = sorted([c for c in four if c.npi_fu.score >= c.npi_bl.score], key=lambda c: -c.npi_bl.score)
    ages = [BG[c.pid]["年齢"] for c in four]
    fem = sum(1 for c in four if BG[c.pid]["性別"] == "女性")
    assert all(c.npi_bl.score == 1 and c.npi_fu.score == 0 for c in dec)

    def cog(c) -> str:
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        return (f"時間見当識{tb:g}→{tf:g}点，MMSE {mb:g}→{mf:g}点，"
                f"CDR-SB {cb:.1f}→{cf:.1f}点")

    def age(c) -> str:
        return f"{BG[c.pid]['年齢']:g}歳"

    s1 = (f"14例のNPI-Apathy scoreは低下{len(dec_all)}例，不変{len(same)}例，"
          f"上昇{len(up)}例であった．")
    s2 = (f"初回1点以上は{len(four)}例（年齢{min(ages):g}～{max(ages):g}歳，女性{fem}例）で，"
          f"値を初回→追跡時で示すと，低下例2例はいずれもスコア1→0点で，"
          f"1例目（{age(dec[0])}）は{cog(dec[0])}，"
          f"2例目（{age(dec[1])}）は{cog(dec[1])}であった．")
    s3 = ("非低下例2例は，"
          + "，".join(f"{i}例目（{age(c)}）がスコア{c.npi_bl.score:g}→{c.npi_fu.score:g}点，{cog(c)}"
                     for i, c in enumerate(non, 1))
          + "であった．")
    s4 = "時間見当識は低下2例で上昇し，非低下2例では上昇しなかったが，MMSEとCDR-SBの変化は一様でなかった．"
    return s1 + s2 + s3 + s4


def main(tpl: str, out: str) -> None:
    body = results_text()
    zin = zipfile.ZipFile(tpl)
    x = zin.read("word/document.xml").decode("utf-8")
    p = [q for q in re.findall(r"<w:p[ >].*?</w:p>", x, re.S) if "【結果】" in q]
    assert len(p) == 1
    p = p[0]
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
    main(sys.argv[1], sys.argv[2])
