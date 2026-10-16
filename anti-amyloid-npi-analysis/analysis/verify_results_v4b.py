# -*- coding: utf-8 -*-
"""【結果】改訂2の検証。
(1) 【結果】以外が上野先生の原本とバイト単位で同一
(2) 【結果】の「…低下例が」までと末尾の一文が、原本（空欄を除く）と同一
(3) 1例ずつ切り出し、年齢から患者を特定して3つ組が同じ患者の値か
(4) 非低下例の並びが前の文「非低下2例は2→3点，1→3点」と同じ順か
"""
from __future__ import annotations

import html
import re
import sys
import zipfile

from npi_increase_analysis import build_cases, read_background

PIVOT = "時間見当識／MMSE／CDR-SB（初回→追跡時）は，低下例が"


def text(p):
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))


def main(tpl, new):
    a, b = zipfile.ZipFile(tpl), zipfile.ZipFile(new)
    ng = 0
    for n in a.namelist():
        if n != "word/document.xml" and a.read(n) != b.read(n):
            ng += 1; print("NG 変更されたファイル", n)
    xa, xb = (z.read("word/document.xml").decode() for z in (a, b))
    pa = re.findall(r"<w:p[ >].*?</w:p>", xa, re.S)
    pb = re.findall(r"<w:p[ >].*?</w:p>", xb, re.S)
    same_out = re.sub(r"<w:p[ >].*?</w:p>", "", xa, flags=re.S) == re.sub(r"<w:p[ >].*?</w:p>", "", xb, flags=re.S)
    print(f"{'OK' if same_out else 'NG'} 段落以外のXML"); ng += 0 if same_out else 1
    for x, y in zip(pa, pb):
        h = (re.match(r"【[^】]+】", text(x)) or ["（空段落）"])[0]
        if h != "【結果】":
            print(f"{'OK' if x == y else 'NG'} {h} 原本とバイト単位で同一"); ng += 0 if x == y else 1

    orig = text([p for p in pa if "【結果】" in text(p)][0])
    res = text([p for p in pb if "【結果】" in text(p)][0])
    # 原本の前半（PIVOTまで）を、空欄を任意の数字として照合
    o_head = orig[: orig.index(PIVOT) + len(PIVOT)]
    pat = re.escape(o_head).replace(re.escape("［　］"), r"[0-9.]+").replace(re.escape("○"), r"[0-9.]+")
    ok = re.match(pat, res) is not None
    print(f"{'OK' if ok else 'NG'} 「…低下例が」までが原本と同一（空欄のみ補充）"); ng += 0 if ok else 1
    o_tail = orig[orig.rindex("．", 0, len(orig) - 1) + 1:]
    ok = res.endswith(o_tail)
    print(f"{'OK' if ok else 'NG'} 末尾の一文が原本と同一: {o_tail}"); ng += 0 if ok else 1

    cases, _ = build_cases(); BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    four = [c for c in inc if c.npi_bl.score >= 1]
    after = res[res.index(PIVOT) + len(PIVOT):]
    dec_part, non_part = after.split("，非低下例が")
    order_np = []
    for grp, part in (("低下例", dec_part), ("非低下例", non_part)):
        for idx, ag, tr in re.findall(r"(\d)例目（(\d+)歳）で([0-9.→／]+)", part):
            c = [c for c in four if BG[c.pid]["年齢"] == float(ag)][0]
            tb, tf = c.bl_fu("MMSE", "時間見当識"); mb, mf = c.bl_fu("MMSE", "__total__"); cb, cf = c.bl_fu("CDR", "__total__")
            exp = f"{tb:g}→{tf:g}／{mb:g}→{mf:g}／{cb:.1f}→{cf:.1f}"
            is_dec = c.npi_fu.score < c.npi_bl.score
            good = tr == exp and (is_dec == (grp == "低下例"))
            ng += 0 if good else 1
            print(f"  {'OK' if good else 'NG'} {grp}{idx}例目（{ag}歳）＝{c.pid} NPI {c.npi_bl.score:g}→{c.npi_fu.score:g}：{tr}")
            if grp == "非低下例":
                order_np.append(f"{c.npi_bl.score:g}→{c.npi_fu.score:g}点")
    m = re.search(r"非低下2例は(.+?)であった", res)
    ok = m and m.group(1) == "，".join(order_np)
    print(f"{'OK' if ok else 'NG'} 非低下例の並びが前の文と同じ順: {m.group(1) if m else None} ⇔ {'，'.join(order_np)}")
    ng += 0 if ok else 1
    print(f"\n不一致 合計 {ng}件")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
