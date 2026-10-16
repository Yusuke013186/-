# -*- coding: utf-8 -*-
"""上野先生修正版の【結果】の空欄（［　］と○）だけを元データの値で埋める。

【演題名】【目的】【方法】【結論】と【結果】の空欄以外の文字は一切変更しない。
空欄は文書中の出現順に埋めるため、埋める値の並びもテンプレの文の順に従う。
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

from npi_increase_analysis import build_cases, read_background

BLANK, MARU = "［　］", "○"


def values() -> tuple[list[str], list[str]]:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    same = [c for c in inc if c.npi_fu.score == c.npi_bl.score]
    up = [c for c in inc if c.npi_fu.score > c.npi_bl.score]
    four = [c for c in inc if c.npi_bl.score >= 1]
    non = sorted([c for c in four if c.npi_fu.score >= c.npi_bl.score],
                 key=lambda c: -c.npi_bl.score)
    ages = [BG[c.pid]["年齢"] for c in four]
    fem = sum(1 for c in four if BG[c.pid]["性別"] == "女性")

    def g(x):
        return f"{x:g}"

    blanks = [g(len(same)), g(len(up))]                       # 不変［　］例，上昇［　］例
    for c in non:                                              # 非低下2例は［　］→［　］点，…
        blanks += [g(c.npi_bl.score), g(c.npi_fu.score)]
    for c in non:                                              # 時間見当識／MMSE／CDR-SB
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        blanks += [g(tb), g(tf), g(mb), g(mf), f"{cb:.1f}", f"{cf:.1f}"]
    maru = [g(min(ages)), g(max(ages)), g(fem)]                # 年齢○～○歳，女性○例
    return blanks, maru


def main(tpl: str, out: str) -> None:
    blanks, maru = values()
    zin = zipfile.ZipFile(tpl)
    x = zin.read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p[ >].*?</w:p>", x, re.S)
    res = [p for p in paras if "【結果】" in p]
    assert len(res) == 1
    p = res[0]
    # 空欄は【結果】にしか存在しないことを確認してから埋める
    assert x.count(BLANK) == p.count(BLANK) == len(blanks), (x.count(BLANK), len(blanks))
    assert x.count(MARU) == p.count(MARU) == len(maru), (x.count(MARU), len(maru))
    it_b, it_m = iter(blanks), iter(maru)
    q = re.sub(re.escape(BLANK), lambda m: next(it_b), p)
    q = re.sub(MARU, lambda m: next(it_m), q)
    y = x.replace(p, q, 1)
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = y.encode("utf-8") if item.filename == "word/document.xml" \
            else zin.read(item.filename)
        zout.writestr(item, data)
    zout.close()
    print("blanks:", blanks)
    print("maru  :", maru)
    print("written", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
