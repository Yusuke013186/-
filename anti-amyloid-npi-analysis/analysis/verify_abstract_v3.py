# -*- coding: utf-8 -*-
"""抄録本文の数値を解析結果と機械的に突き合わせる。

抄録に現れる数値を1つずつ再計算し、一致しないものを列挙する。
一致しない項目が残っている原稿を完成稿として扱わないための確認。
"""
from __future__ import annotations

import io
import os
import re
import statistics as stx

from npi_increase_analysis import MMSE_SUB, CDR_DOM, build_cases, read_background
from exhaustive_search import obs_months
from decline_group_analysis import group_of, ms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "abstract_v3",
                   "抄録_NPI-Apathyscore低下例の認知機能推移.md")


def main() -> None:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    dec = [c for c in inc if group_of(c) == "低下例"]
    non = [c for c in inc if group_of(c) == "非低下例"]
    txt = io.open(DOC, encoding="utf-8").read()

    def g(c, sh, key, w):
        b, f = c.bl_fu(sh, key)
        return b if w == "bl" else f if w == "fu" else (
            None if b is None or f is None else f - b)

    checks: list[tuple[str, str]] = []

    def chk(label, expected):
        checks.append((label, str(expected)))

    chk("解析対象14例", 14 if len(inc) == 14 else len(inc))
    chk("低下例2例", len(dec))
    chk("非低下例12例", len(non))
    chk("低下例14.3％", f"{len(dec) / len(inc) * 100:.1f}")
    chk("非低下例85.7％", f"{len(non) / len(inc) * 100:.1f}")
    chk("非低下例 初回0点10例", sum(1 for c in non if c.npi_bl.score == 0))
    chk("非低下例 初回1点1例", sum(1 for c in non if c.npi_bl.score == 1))
    chk("非低下例 初回2点1例", sum(1 for c in non if c.npi_bl.score == 2))
    chk("低下例 全例1点→0点",
        all(c.npi_bl.score == 1 and c.npi_fu.score == 0 for c in dec))
    chk("年齢 低下例78.0±4.2",
        ms([BG[c.pid]["年齢"] for c in dec]))
    chk("年齢 非低下例74.8±4.6",
        ms([BG[c.pid]["年齢"] for c in non]))
    chk("女性 低下例2/2",
        f"{sum(1 for c in dec if BG[c.pid]['性別'] == '女性')}/{len(dec)}")
    chk("女性 非低下例7/12",
        f"{sum(1 for c in non if BG[c.pid]['性別'] == '女性')}/{len(non)}")
    for lab, gr, sh, key, w in (
            ("初回MMSE 低下例22.5±0.7", dec, "MMSE", "__total__", "bl"),
            ("初回MMSE 非低下例24.9±2.0", non, "MMSE", "__total__", "bl"),
            ("初回CDR-SB 低下例1.8±0.4", dec, "CDR", "__total__", "bl"),
            ("初回CDR-SB 非低下例1.5±0.7", non, "CDR", "__total__", "bl"),
            ("初回時間見当識 低下例2.0±0.0", dec, "MMSE", "時間見当識", "bl"),
            ("初回時間見当識 非低下例4.2±1.0", non, "MMSE", "時間見当識", "bl"),
            ("ΔMMSE 低下例+1.5±2.1", dec, "MMSE", "__total__", "d"),
            ("ΔMMSE 非低下例-0.5±1.9", non, "MMSE", "__total__", "d"),
            ("ΔCDR-SB 低下例+1.0±1.4", dec, "CDR", "__total__", "d"),
            ("ΔCDR-SB 非低下例+0.9±0.8", non, "CDR", "__total__", "d"),
            ("Δ時間見当識 低下例+1.5±0.7", dec, "MMSE", "時間見当識", "d"),
            ("Δ時間見当識 非低下例-0.8±0.8", non, "MMSE", "時間見当識", "d")):
        chk(lab, ms([g(c, sh, key, w) for c in gr]))
    chk("時間見当識改善 低下例2/2",
        f"{sum(1 for c in dec if (g(c, 'MMSE', '時間見当識', 'd') or 0) > 0)}/{len(dec)}")
    chk("時間見当識改善 非低下例0/12",
        f"{sum(1 for c in non if (g(c, 'MMSE', '時間見当識', 'd') or 0) > 0)}/{len(non)}")

    from collections import Counter
    for lab, gr in (("低下例", dec), ("非低下例", non)):
        cnt = Counter(c.followup_visit("MMSE").label for c in gr)
        chk(f"{lab} 評価時点の分布",
            "、".join(f"{k}{v}例" for k, v in sorted(cnt.items())))

    # 低下2例の個別値と、下位項目Δの総和が合計点Δと一致すること
    for c in sorted(dec, key=lambda x: x.followup_visit("MMSE").label,
                    reverse=True):
        bt, ft = c.bl_fu("MMSE", "__total__")
        bs, fs = c.bl_fu("CDR", "__total__")
        chk(f"{c.pid} 年齢", BG[c.pid]["年齢"])
        chk(f"{c.pid} MMSE", f"{bt:g}→{ft:g}")
        chk(f"{c.pid} CDR-SB", f"{bs:g}→{fs:g}")
        sub = [(k,) + c.bl_fu("MMSE", k) for k in MMSE_SUB]
        chg = [f"{k}{b:g}→{f:g}" for k, b, f in sub if b != f]
        chk(f"{c.pid} 変化したMMSE下位項目", "、".join(chg))
        chk(f"{c.pid} 下位項目Δの総和＝合計点Δ",
            sum(f - b for _, b, f in sub) == ft - bt)
        cd = [(k,) + c.bl_fu("CDR", k) for k in CDR_DOM]
        chk(f"{c.pid} 変化したCDR領域",
            "、".join(f"{k}{b:g}→{f:g}" for k, b, f in cd if b != f) or "なし")
        chk(f"{c.pid} 易怒性",
            f"{c.npi_bl.irrit}→{c.npi_fu.irrit}")

    # 合計点と下位項目合計の整合性（解析対象全例）
    bad = 0
    for c in inc:
        for v in c.mmse:
            s = [v.items.get(k) for k in MMSE_SUB]
            if v.total is None or any(x is None for x in s):
                continue
            if abs(sum(s) - v.total) > 1e-9:
                bad += 1
    chk("MMSE合計と下位項目合計の不一致（解析対象）", bad)

    print("=== 抄録の数値と解析結果の突き合わせ ===")
    for lab, val in checks:
        print(f"  {lab}: {val}")

    # 抄録本文に書かれている数値が実際に出現するか
    need = [
        "14例", "2例（14.3％）", "12例（85.7％）", "0点10例", "1点1例", "2点1例",
        "78.0±4.2", "74.8±4.6", "2/2例", "7/12例",
        "22.5±0.7", "24.9±2.0", "1.8±0.4", "1.5±0.7",
        "2.0±0.0", "4.2±1.0", "＋1.5±2.1", "−0.5±1.9",
        "＋1.0±1.4", "＋0.9±0.8", "＋1.5±0.7", "−0.8±0.8",
        "低下例2/2例", "非低下例0/12例",
        "75歳女性", "23→23点", "2.0→4.0点", "時間見当識2→3", "注意計算5→3",
        "図形模写0→1",
        "81歳女性", "22→25点", "1.5→1.5点", "時間見当識2→4", "場所見当識4→5",
        "注意計算3→4", "遅延再生1→0",
        "6か月4例", "12か月3例", "18か月4例", "24か月1例",
    ]
    miss = [x for x in need if x not in txt]
    print("\n=== 抄録本文に含まれるべき表記の確認 ===")
    print(f"  確認項目 {len(need)}件 / 見当たらない {len(miss)}件")
    for x in miss:
        print(f"  ✗ {x}")

    # 本文に現れる「a→b」の下位項目記載が、合計点の変化と整合するか
    print("\n=== 抄録本文の下位項目記載が合計点変化と一致するか ===")
    for pid, pat in (("1例目", r"MMSE (\d+)→(\d+)点（([^）]+)）"),):
        for m in re.finditer(pat, txt):
            b, f = int(m.group(1)), int(m.group(2))
            items = re.findall(r"(\d+)→(\d+)", m.group(3))
            s = sum(int(y) - int(x) for x, y in items)
            ok = "一致" if s == f - b else "**不一致**"
            print(f"  MMSE {b}→{f}（Δ{f - b:+d}）: "
                  f"記載された下位項目Δの総和 {s:+d} → {ok}")


if __name__ == "__main__":
    main()
