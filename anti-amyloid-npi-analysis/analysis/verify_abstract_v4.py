# -*- coding: utf-8 -*-
"""総会抄録（上野先生修正版テンプレ）の数値を元データと突き合わせる。

テンプレの空欄を埋めた値と、テンプレに元から書かれていた値の両方を
再計算して照合する。一致しない項目があれば列挙する。
"""
from __future__ import annotations

import io
import os
import re
from collections import Counter

from npi_increase_analysis import build_cases, read_background, MMSE_SUB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "abstract_v4", "総会抄録_アパシーと認知・生活機能の経時的変化.md")


def f1(x: float) -> str:
    return f"{x:.1f}"


def main() -> None:
    cases, _ = build_cases()
    BG = read_background()
    inc = sorted([c for c in cases if c.step == "S5_解析対象"],
                 key=lambda c: int(c.pid[1:]))
    txt = io.open(DOC, encoding="utf-8").read()
    ng = 0
    rows = []

    def chk(label: str, expected: str, ok: bool | None = None) -> None:
        nonlocal ng
        hit = (expected in txt) if ok is None else ok
        ng += 0 if hit else 1
        rows.append((("OK " if hit else "NG ") + label, expected))

    # --- 対象
    chk("解析対象", "14例", len(inc) == 14 and "14例" in txt)
    chk("全例レカネマブ", "全例レカネマブ",
        all(c.drug == "レカネマブ" for c in inc) and "全例レカネマブ" in txt)
    total_ids = len(cases) - sum(1 for c in cases if c.pid == "L69")
    chk("96例（L69を除く研究番号数）", "96例", total_ids == 96 and "96例" in txt)

    # --- NPI推移の内訳
    dec = [c for c in inc if c.npi_fu.score < c.npi_bl.score]
    same = [c for c in inc if c.npi_fu.score == c.npi_bl.score]
    up = [c for c in inc if c.npi_fu.score > c.npi_bl.score]
    chk("低下例数", f"低下{len(dec)}例")
    chk("不変例数", f"不変{len(same)}例")
    chk("不変例はいずれも0点のまま", "いずれも0点のまま",
        all(c.npi_bl.score == 0 for c in same) and "いずれも0点のまま" in txt)
    chk("上昇例数", f"上昇{len(up)}例")

    # --- 初回1点以上の4例
    four = [c for c in inc if c.npi_bl.score >= 1]
    ages = [BG[c.pid]["年齢"] for c in four]
    fem = sum(1 for c in four if BG[c.pid]["性別"] == "女性")
    chk("初回1点以上の例数", f"初回1点以上は{len(four)}例")
    chk("年齢範囲", f"年齢{min(ages):g}～{max(ages):g}歳")
    chk("女性数", f"女性{fem}例")
    d2 = [c for c in four if c.npi_fu.score < c.npi_bl.score]
    n2 = [c for c in four if c.npi_fu.score >= c.npi_bl.score]
    chk("低下2例はいずれも1→0点", "いずれも1→0点",
        all(c.npi_bl.score == 1 and c.npi_fu.score == 0 for c in d2) and len(d2) == 2)
    nstr = "，".join(f"{c.npi_bl.score:g}→{c.npi_fu.score:g}点" for c in n2)
    chk("非低下2例のスコア", f"非低下2例は{nstr}")

    # --- 時間見当識／MMSE／CDR-SB の3つ組（テンプレの順序：低下例はL4→L59）
    def trip(c) -> str:
        tb, tf = c.bl_fu("MMSE", "時間見当識")
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        return f"{tb:g}→{tf:g}／{mb:g}→{mf:g}／{f1(cb)}→{f1(cf)}"

    dec_s = "，".join(trip(c) for c in d2)
    non_s = "，".join(trip(c) for c in n2)
    chk("低下例の3つ組", f"低下例が{dec_s}")
    chk("非低下例の3つ組（非低下2例のスコアと同じ順）", f"非低下例が{non_s}")

    # --- 記述の向き
    tdec = [c.delta("MMSE", "時間見当識") for c in d2]
    tnon = [c.delta("MMSE", "時間見当識") for c in n2]
    chk("時間見当識は低下2例で上昇", "低下2例で上昇", all(d > 0 for d in tdec))
    chk("非低下2例では上昇しなかった", "非低下2例では上昇しなかった",
        all(d <= 0 for d in tnon))
    mm = [c.delta("MMSE", "__total__") for c in four]
    cs = [c.delta("CDR", "__total__") for c in four]
    chk("MMSEとCDR-SBの変化は一様でなかった", "一様でなかった",
        len(set(mm)) > 1 and len(set(cs)) > 1)
    tb_d = [c.bl_fu("MMSE", "時間見当識")[0] for c in d2]
    tb_n = [c.bl_fu("MMSE", "時間見当識")[0] for c in n2]
    chk("初回時間見当識 低下2例がいずれも2点", "低下2例がいずれも2点",
        all(x == 2 for x in tb_d))
    chk("初回時間見当識 非低下2例が5点と3点",
        "非低下2例が" + "と".join(f"{x:g}点" for x in tb_n))

    # --- 評価間隔
    cog = sorted({c.followup_visit("MMSE").label for c in inc},
                 key=lambda x: int(x.replace("か月", "")))
    chk("認知機能の評価時点の範囲", f"（{cog[0].replace('か月','')}～{cog[-1]}）")
    labs = []
    for c in inc:
        m = re.match(r"(\d+)か月", c.npi_fu.orig_label)
        if m:
            labs.append(int(m.group(1)))
        elif c.npi_bl.ym and c.npi_fu.ym:          # 原資料に時点の記載がない例は年月で
            labs.append((c.npi_fu.ym[0] - c.npi_bl.ym[0]) * 12
                        + c.npi_fu.ym[1] - c.npi_bl.ym[1])
    chk("NPIの評価間隔（原資料の時点ラベル）",
        f"NPI-Apathy scoreが{min(labs)}～{max(labs)}か月")

    # --- 合計点と下位項目合計
    bad = sum(1 for c in inc for v in c.mmse
              if v.total is not None
              and all(v.items.get(k) is not None for k in MMSE_SUB)
              and abs(sum(v.items[k] for k in MMSE_SUB) - v.total) > 1e-9)
    chk("MMSE合計と下位項目合計の不一致（対象14例）", "0件", bad == 0)

    print("=== 総会抄録の数値と元データの突き合わせ ===")
    for lab, exp in rows:
        print(f"  {lab}: {exp}")
    print(f"\n確認 {len(rows)}項目 / 不一致 {ng}件")
    print("\n参考：4例の内訳")
    for c in four:
        print(f"  {c.pid} {BG[c.pid]['年齢']:g}歳 {BG[c.pid]['性別']} "
              f"NPI {c.npi_bl.score:g}→{c.npi_fu.score:g} 3つ組 {trip(c)} "
              f"追跡 {c.followup_visit('MMSE').label}")


if __name__ == "__main__":
    main()
