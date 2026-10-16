# -*- coding: utf-8 -*-
"""穴埋め版の検証。
(1) 【結果】以外の段落と、docx内の document.xml 以外のファイルが原本とバイト単位で同一か
(2) 【結果】の差分が空欄の位置だけか（空欄を除いた文字列が原本と一致するか）
(3) 埋めた値と【結果】の記述が元データと一致するか
"""
from __future__ import annotations

import html
import re
import sys
import zipfile

from npi_increase_analysis import build_cases, read_background


def text(p: str) -> str:
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))


def main(orig: str, new: str) -> None:
    a, b = zipfile.ZipFile(orig), zipfile.ZipFile(new)
    ng = 0
    assert a.namelist() == b.namelist()
    for n in a.namelist():
        if n != "word/document.xml":
            same = a.read(n) == b.read(n)
            ng += 0 if same else 1
            if not same:
                print("NG 変更されたファイル:", n)
    xa = a.read("word/document.xml").decode()
    xb = b.read("word/document.xml").decode()
    pa = re.findall(r"<w:p[ >].*?</w:p>", xa, re.S)
    pb = re.findall(r"<w:p[ >].*?</w:p>", xb, re.S)
    assert len(pa) == len(pb)
    # 段落の外側（sectPr など）も同一か
    outside_a = re.sub(r"<w:p[ >].*?</w:p>", "", xa, flags=re.S)
    outside_b = re.sub(r"<w:p[ >].*?</w:p>", "", xb, flags=re.S)
    print(f"{'OK' if outside_a == outside_b else 'NG'} 段落以外のXML（ページ設定など）")
    ng += 0 if outside_a == outside_b else 1
    for x, y in zip(pa, pb):
        head = (re.match(r"【[^】]+】", text(x)) or [""])[0] or "（空段落）"
        if "【結果】" in text(x):
            # 空欄を正規表現に変えて、原本の文がそのまま残っているかを確認
            pat = re.escape(text(x)).replace(re.escape("［　］"), r"([0-9.]+)") \
                .replace(re.escape("○"), r"([0-9.]+)")
            m = re.fullmatch(pat, text(y))
            ok = m is not None
            print(f"{'OK' if ok else 'NG'} {head} 空欄以外の文字は原本と同一"
                  f"（埋めた空欄 {len(m.groups()) if m else '?'}か所）")
            ng += 0 if ok else 1
        else:
            ok = x == y
            print(f"{'OK' if ok else 'NG'} {head} XMLが原本とバイト単位で同一")
            ng += 0 if ok else 1

    # 内容の確認
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    four = [c for c in inc if c.npi_bl.score >= 1]
    dec = sorted([c for c in four if c.npi_fu.score < c.npi_bl.score], key=lambda c: int(c.pid[1:]))
    non = sorted([c for c in four if c.npi_fu.score >= c.npi_bl.score], key=lambda c: -c.npi_bl.score)
    res = text([p for p in pb if "【結果】" in text(p)][0])

    def trip(c):
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        return f"{tb:g}→{tf:g}／{mb:g}→{mf:g}／{cb:.1f}→{cf:.1f}"

    checks = [
        ("14例", len(inc) == 14),
        (f"低下{sum(1 for c in inc if c.npi_fu.score < c.npi_bl.score)}例", None),
        (f"不変{sum(1 for c in inc if c.npi_fu.score == c.npi_bl.score)}例", None),
        (f"上昇{sum(1 for c in inc if c.npi_fu.score > c.npi_bl.score)}例", None),
        (f"初回1点以上は{len(four)}例", None),
        (f"年齢{min(BG[c.pid]['年齢'] for c in four):g}～{max(BG[c.pid]['年齢'] for c in four):g}歳", None),
        (f"女性{sum(1 for c in four if BG[c.pid]['性別'] == '女性')}例", None),
        ("低下2例はいずれも1→0点", all(c.npi_bl.score == 1 and c.npi_fu.score == 0 for c in dec)),
        ("非低下2例は" + "，".join(f"{c.npi_bl.score:g}→{c.npi_fu.score:g}点" for c in non), None),
        ("低下例が" + "，".join(trip(c) for c in dec), None),
        ("非低下例が" + "，".join(trip(c) for c in non), None),
        ("時間見当識は低下2例で上昇し", all(c.delta("MMSE", "時間見当識") > 0 for c in dec)),
        ("非低下2例では上昇しなかった", all(c.delta("MMSE", "時間見当識") <= 0 for c in non)),
        ("MMSEとCDR-SBの変化は一様でなかった",
         len({c.delta("MMSE", "__total__") for c in four}) > 1
         and len({c.delta("CDR", "__total__") for c in four}) > 1),
    ]
    print("\n=== 【結果】の内容と元データ ===")
    for s, extra in checks:
        ok = s in res and (extra is None or extra)
        ng += 0 if ok else 1
        print(f"  {'OK' if ok else 'NG'} {s}")
    print(f"\n不一致 合計 {ng}件")
    print("\n=== 穴埋め後の【結果】 ===\n" + res)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
