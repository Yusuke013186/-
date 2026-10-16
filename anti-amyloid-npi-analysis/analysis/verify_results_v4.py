# -*- coding: utf-8 -*-
"""【結果】改訂版の検証。
(1) 【結果】以外が原本とバイト単位で同一か
(2) 本文を1例ずつ切り出し、年齢・スコア・時間見当識・MMSE・CDR-SBが
    同じ患者の値として対応しているか（症例間の取り違えがないか）
(3) 4例すべてが本文に現れているか
"""
from __future__ import annotations

import html
import re
import sys
import zipfile

from npi_increase_analysis import build_cases, read_background


def text(p):
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))


def main(orig, new):
    a, b = zipfile.ZipFile(orig), zipfile.ZipFile(new)
    ng = 0
    for n in a.namelist():
        if n != "word/document.xml" and a.read(n) != b.read(n):
            ng += 1; print("NG 変更されたファイル", n)
    xa, xb = (z.read("word/document.xml").decode() for z in (a, b))
    pa = re.findall(r"<w:p[ >].*?</w:p>", xa, re.S)
    pb = re.findall(r"<w:p[ >].*?</w:p>", xb, re.S)
    out_same = re.sub(r"<w:p[ >].*?</w:p>", "", xa, flags=re.S) == \
        re.sub(r"<w:p[ >].*?</w:p>", "", xb, flags=re.S)
    print(f"{'OK' if out_same else 'NG'} 段落以外のXML"); ng += 0 if out_same else 1
    for x, y in zip(pa, pb):
        h = (re.match(r"【[^】]+】", text(x)) or ["（空段落）"])[0]
        if h == "【結果】":
            continue
        print(f"{'OK' if x == y else 'NG'} {h} 原本とバイト単位で同一"); ng += 0 if x == y else 1

    res = text([p for p in pb if "【結果】" in text(p)][0])
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    four = [c for c in inc if c.npi_bl.score >= 1]

    # 1例ずつ切り出す：「n例目（xx歳）」から次の「例目（」または「であった．」まで
    segs = re.findall(r"(\d)例目（(\d+)歳）[はが](.*?)(?=，\d例目（|であった．)", res)
    print(f"\n本文から切り出した症例: {len(segs)}例")
    seen = set()
    for idx, ag, body in segs:
        cand = [c for c in four if BG[c.pid]["年齢"] == float(ag)]
        assert len(cand) == 1, ag
        c = cand[0]
        seen.add(c.pid)
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        exp = [f"時間見当識{tb:g}→{tf:g}点", f"MMSE {mb:g}→{mf:g}点", f"CDR-SB {cb:.1f}→{cf:.1f}点"]
        if c.npi_fu.score >= c.npi_bl.score:          # 非低下例はスコアを症例ごとに記載
            exp.insert(0, f"スコア{c.npi_bl.score:g}→{c.npi_fu.score:g}点")
        else:                                         # 低下例は「いずれもスコア1→0点」でまとめて記載
            ok_np = c.npi_bl.score == 1 and c.npi_fu.score == 0 and "いずれもスコア1→0点" in res
            ng += 0 if ok_np else 1
        miss = [e for e in exp if e not in body]
        grp = "低下例" if c.npi_fu.score < c.npi_bl.score else "非低下例"
        print(f"  {'OK' if not miss else 'NG'} {grp}{idx}例目（{ag}歳）＝{c.pid}: "
              f"NPI {c.npi_bl.score:g}→{c.npi_fu.score:g}／{'／'.join(exp)}"
              + (f"  欠落: {miss}" if miss else ""))
        ng += len(miss)
    allin = seen == {c.pid for c in four}
    print(f"{'OK' if allin else 'NG'} 4例すべてが本文に現れる: {sorted(seen)}"); ng += 0 if allin else 1

    for s, cond in [
        ("低下2例", True), ("不変7例", True), ("上昇5例", True),
        ("年齢71～81歳", True), ("女性4例", True),
        ("時間見当識は低下2例で上昇し", True), ("非低下2例では上昇しなかった", True),
        ("一様でなかった", True)]:
        ok = s in res and cond
        ng += 0 if ok else 1
        print(f"  {'OK' if ok else 'NG'} {s}")
    print(f"\n不一致 合計 {ng}件")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
