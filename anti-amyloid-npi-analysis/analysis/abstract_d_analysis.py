# -*- coding: utf-8 -*-
"""
抄録D用の解析 — NPIの経過が追えた症例に限定した、アパシー改善2例の位置づけ

前回抄録（日本神経学会 No.1000218）の記載様式に合わせ、
  ・記述統計は 平均±標準偏差
  ・連続量の群間比較は Mann-Whitney U 検定
  ・比率の群間比較は Fisher の正確確率検定
  ・患者背景と認知機能を、非改善群・改善群の順に対比して提示
という形式で出力する。

対象集団は「NPI原票がベースラインと追跡時の両方で確認でき、かつ認知機能の
追跡も可能であった症例」に限定する。全治療例の分布のなかでの順位づけは用いない。

実行: python3 analysis/abstract_d_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import os
import statistics as st
import sys
from typing import Optional

from scipy.stats import mannwhitneyu, fisher_exact

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_analysis import (                                   # noqa: E402
    MMSE_SUB, CDR_DOM, Subject, build_subjects, bl_fu, outcomes,
    outcome_meta, median,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def ms(vals: list[float], nd: int = 1) -> str:
    """平均±標準偏差。n=1 では標準偏差を出さない。"""
    if not vals:
        return "－"
    if len(vals) == 1:
        return f"{vals[0]:.{nd}f}"
    return f"{st.mean(vals):.{nd}f}±{st.stdev(vals):.{nd}f}"


def mw(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 1 or len(b) < 1 or len(set(a + b)) == 1:
        return None
    return float(mannwhitneyu(a, b, alternative="two-sided", method="exact")[1])


def fp(p: Optional[float]) -> str:
    return "－" if p is None else f"p={p:.2f}"


def fp3(p: Optional[float]) -> str:
    return "－" if p is None else (f"p={p:.3f}" if p >= 0.001 else "p<0.001")


def main() -> None:
    subs = build_subjects()

    # --- 対象集団: NPIが対で評価でき、かつ認知機能の追跡もある症例
    npi_paired = [x for x in subs if x.npi_paired
                  and x.ap_bl is not None and x.ap_fu is not None]
    pop = [x for x in npi_paired
           if x.d("MMSE", "__total__") is not None
           and x.d("CDR", "__total__") is not None]
    imp = [x for x in pop if x.ap_bl == 1 and x.ap_fu == 0]
    non = [x for x in pop if not (x.ap_bl == 1 and x.ap_fu == 0)]

    R: list[str] = []
    A = R.append
    A("# 抄録D用 解析結果 — NPI評価例に限定したアパシー改善2例の位置づけ\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("前回抄録（日本神経学会 No.1000218）の様式に合わせ、"
      "記述統計は平均±標準偏差、群間比較は Mann-Whitney U 検定"
      "および Fisher の正確確率検定を用いた。\n")

    # --- 組み入れフロー
    A("\n## 1. 対象\n")
    A(f"- 抗アミロイドβ抗体療法施行例: {len(subs)}例"
      f"（レカネマブ {sum(1 for x in subs if x.drug=='レカネマブ')}例、"
      f"ドナネマブ {sum(1 for x in subs if x.drug=='ドナネマブ')}例）")
    A(f"- NPI原票がベースラインと追跡時の両方で確認でき、第7項目が判定できた症例: "
      f"{len(npi_paired)}例")
    nocog = [x for x in npi_paired if x not in pop]
    A(f"- うち MMSE・CDR の追跡も可能であった症例（解析対象）: **{len(pop)}例**"
      f"（{', '.join(x.pid for x in pop)}）")
    A(f"- 認知機能の追跡値がなく除外: {len(nocog)}例"
      f"（{', '.join(x.pid for x in nocog)}）")
    A(f"- 解析対象{len(pop)}例の薬剤: "
      + "、".join(f"{d} {sum(1 for x in pop if x.drug==d)}例"
                for d in ("レカネマブ", "ドナネマブ")))
    A(f"\n- **アパシー改善群（あり→なし）: {len(imp)}例**"
      f"（{', '.join(x.pid for x in imp)}）")
    A(f"- **非改善群: {len(non)}例**（{', '.join(x.pid for x in non)}）")
    tr = {}
    for x in non:
        tr[x.trans("ap")] = tr.get(x.trans("ap"), 0) + 1
    A(f"  - 内訳: " + "、".join(f"{k} {v}例" for k, v in sorted(tr.items())))

    # --- 観察期間
    A("\n## 2. 観察期間\n")
    bls = [bl_fu(x.mmse, "__total__")[0].date for x in pop
           if bl_fu(x.mmse, "__total__")[0] and bl_fu(x.mmse, "__total__")[0].date]
    nbl = [x for x in pop if getattr(x, "npi_note", "")]
    A(f"- MMSEベースライン評価日が判明した{len(bls)}例の範囲: "
      f"{min(bls)} 〜 {max(bls)}")
    ivs = [x.interval_m for x in pop if x.interval_m is not None]
    A(f"- MMSEベースラインから最終評価までの期間（{len(ivs)}例）: "
      f"{ms(ivs)}か月［{min(ivs):g}, {max(ivs):g}］")
    ia = [x.interval_m for x in imp if x.interval_m is not None]
    ib = [x.interval_m for x in non if x.interval_m is not None]
    A(f"  - 改善群 {ms(ia)}か月 / 非改善群 {ms(ib)}か月（{fp(mw(ia, ib))}）")

    # --- 患者背景と認知機能の比較
    def get_bl(x, ok):
        return x.base(*outcome_meta(ok)[:2])

    def get_fu(x, ok):
        b = get_bl(x, ok)
        d = outcomes(x)[ok]
        return None if b is None or d is None else b + d

    ROWS = [
        ("患者背景", "ベースライン MMSE合計（点）", lambda x: get_bl(x, "ΔMMSE合計"), 1),
        ("患者背景", "ベースライン CDR-SB（点）", lambda x: get_bl(x, "ΔCDR-SB"), 1),
        ("患者背景", "ベースライン Global CDR", lambda x: get_bl(x, "ΔGlobalCDR"), 2),
        ("患者背景", "ベースライン MoCA-J（点）", lambda x: get_bl(x, "ΔMoCA-J"), 1),
        ("患者背景", "ベースライン MMSE時間見当識（点）",
         lambda x: get_bl(x, "ΔMMSE_時間見当識"), 1),
        ("患者背景", "観察期間（か月）", lambda x: x.interval_m, 1),
        ("追跡時", "追跡時 MMSE合計（点）", lambda x: get_fu(x, "ΔMMSE合計"), 1),
        ("追跡時", "追跡時 CDR-SB（点）", lambda x: get_fu(x, "ΔCDR-SB"), 1),
        ("追跡時", "追跡時 MMSE時間見当識（点）",
         lambda x: get_fu(x, "ΔMMSE_時間見当識"), 1),
        ("変化量", "ΔMMSE合計（点）", lambda x: outcomes(x)["ΔMMSE合計"], 1),
        ("変化量", "ΔCDR-SB（点）", lambda x: outcomes(x)["ΔCDR-SB"], 1),
        ("変化量", "ΔGlobal CDR", lambda x: outcomes(x)["ΔGlobalCDR"], 2),
        ("変化量", "ΔMMSE時間見当識（点）",
         lambda x: outcomes(x)["ΔMMSE_時間見当識"], 1),
    ]
    for k in MMSE_SUB:
        if k == "時間見当識":
            continue
        ROWS.append(("変化量（MMSE他下位項目）", f"ΔMMSE {k}（点）",
                     (lambda kk: (lambda x: outcomes(x)[f"ΔMMSE_{kk}"]))(k), 1))
    for k in CDR_DOM:
        ROWS.append(("変化量（CDR下位領域）", f"ΔCDR {k}（点）",
                     (lambda kk: (lambda x: outcomes(x)[f"ΔCDR_{kk}"]))(k), 2))

    A("\n\n## 3. 患者背景および認知機能の比較\n")
    A("前回抄録と同じく、平均±標準偏差と Mann-Whitney U 検定の p 値を示す。\n")
    A("| 区分 | 項目 | 非改善群（n=%d） | 改善群（n=%d） | p |" % (len(non), len(imp)))
    A("|---|---|---|---|---|")
    tbl = []
    for sec, name, fn, nd in ROWS:
        a = [fn(x) for x in imp]
        b = [fn(x) for x in non]
        a = [v for v in a if v is not None]
        b = [v for v in b if v is not None]
        if not a and not b:
            continue
        p = mw(a, b)
        A(f"| {sec} | {name} | {ms(b, nd)}"
          f"{f'（n={len(b)}）' if len(b) != len(non) else ''} | {ms(a, nd)}"
          f"{f'（n={len(a)}）' if len(a) != len(imp) else ''} | {fp3(p)} |")
        tbl.append({"区分": sec, "項目": name,
                    "非改善群": ms(b, nd), "非改善群n": len(b),
                    "改善群": ms(a, nd), "改善群n": len(a),
                    "改善群の個別値": ", ".join(f"{v:g}" for v in a),
                    "非改善群中央値": median(b) if b else None,
                    "p": p})

    # 比率の比較
    A("\n### 比率の比較（Fisher の正確確率検定）\n")
    A("| 項目 | 非改善群 | 改善群 | p |")
    A("|---|---|---|---|")
    rate_rows = []
    for name, fn in [
            ("ベースラインで易怒性あり", lambda x: x.ir_bl == 1),
            ("追跡時に易怒性あり", lambda x: x.ir_fu == 1),
            ("易怒性が新規出現（なし→あり）",
             lambda x: x.ir_bl == 0 and x.ir_fu == 1),
            ("MMSE時間見当識が改善（Δ≧+1）",
             lambda x: (outcomes(x)["ΔMMSE_時間見当識"] or 0) >= 1),
            ("MMSE時間見当識が低下（Δ≦−1）",
             lambda x: (outcomes(x)["ΔMMSE_時間見当識"] or 0) <= -1),
            ("MMSE合計が低下（Δ≦−1）",
             lambda x: (outcomes(x)["ΔMMSE合計"] or 0) <= -1),
            ("CDR-SBが悪化（Δ≧+0.5）",
             lambda x: (outcomes(x)["ΔCDR-SB"] or 0) >= 0.5)]:
        ca = sum(1 for x in imp if fn(x))
        cb = sum(1 for x in non if fn(x))
        _, p = fisher_exact([[ca, len(imp) - ca], [cb, len(non) - cb]])
        A(f"| {name} | {cb}/{len(non)}例（{cb/len(non)*100:.0f}％） | "
          f"{ca}/{len(imp)}例（{ca/len(imp)*100:.0f}％） | {fp3(p)} |")
        rate_rows.append({"項目": name,
                          "非改善群": f"{cb}/{len(non)}",
                          "非改善群%": round(cb / len(non) * 100, 1),
                          "改善群": f"{ca}/{len(imp)}",
                          "改善群%": round(ca / len(imp) * 100, 1), "p": p})

    # --- 改善2例の個別記載
    A("\n\n## 4. アパシー改善2例の個別データ\n")
    A("| 項目 | " + " | ".join(x.pid for x in imp) + " |")
    A("|---|" + "---|" * len(imp))
    yn = {1: "あり", 0: "なし", None: "－"}
    A("| 薬剤 | " + " | ".join(x.drug for x in imp) + " |")
    A("| 観察期間 | " + " | ".join(
        f"{x.interval_m:g}か月" if x.interval_m is not None else "不明"
        for x in imp) + " |")
    A("| NPI第7項目（アパシー） | "
      + " | ".join(f"{yn[x.ap_bl]}→{yn[x.ap_fu]}" for x in imp) + " |")
    A("| NPI第9項目（易怒性） | "
      + " | ".join(f"{yn[x.ir_bl]}→{yn[x.ir_fu]}" for x in imp) + " |")
    for ok, nm in [("ΔMMSE合計", "MMSE合計"), ("ΔCDR-SB", "CDR-SB"),
                   ("ΔGlobalCDR", "Global CDR"), ("ΔMoCA-J", "MoCA-J"),
                   ("ΔMMSE_時間見当識", "MMSE時間見当識")]:
        cells = []
        for x in imp:
            b, d = get_bl(x, ok), outcomes(x)[ok]
            cells.append("－" if b is None or d is None else f"{b:g}→{b+d:g}")
        A(f"| {nm}（初回→追跡時） | " + " | ".join(cells) + " |")

    A("\n### 非改善群12例の内訳（参考）\n")
    A("| 研究番号 | アパシー | 易怒性 | 観察期間 | MMSE合計 | CDR-SB | 時間見当識 |")
    A("|---|---|---|---|---|---|---|")
    for x in sorted(non, key=lambda z: z.pid):
        def cell(ok):
            b, d = get_bl(x, ok), outcomes(x)[ok]
            return "－" if b is None or d is None else f"{b:g}→{b+d:g}"
        A(f"| {x.pid} | {yn[x.ap_bl]}→{yn[x.ap_fu]} | {yn[x.ir_bl]}→{yn[x.ir_fu]} | "
          f"{f'{x.interval_m:g}か月' if x.interval_m is not None else '不明'} | "
          f"{cell('ΔMMSE合計')} | {cell('ΔCDR-SB')} | {cell('ΔMMSE_時間見当識')} |")

    # --- 時間見当識の位置づけ（NPI評価例内）
    A("\n\n## 5. MMSE時間見当識の位置づけ（NPI評価例に限定）\n")
    dto = {x.pid: outcomes(x)["ΔMMSE_時間見当識"] for x in pop}
    up = [p for p, v in dto.items() if v is not None and v >= 1]
    flat = [p for p, v in dto.items() if v == 0]
    down = [p for p, v in dto.items() if v is not None and v <= -1]
    A(f"解析対象{len(pop)}例における時間見当識の変化:")
    A(f"- 改善（Δ≧+1点）: {len(up)}例（{', '.join(sorted(up))}）")
    A(f"- 不変: {len(flat)}例（{', '.join(sorted(flat))}）")
    A(f"- 低下（Δ≦−1点）: {len(down)}例（{', '.join(sorted(down))}）")
    A(f"\n**アパシー改善2例は、時間見当識が改善した{len(up)}例の全てを占めた。**"
      if set(up) == {x.pid for x in imp} else
      f"\n時間見当識が改善した{len(up)}例のうち、アパシー改善例は"
      f"{len(set(up) & {x.pid for x in imp})}例であった。")
    ca = sum(1 for x in imp if (dto[x.pid] or 0) >= 1)
    cb = sum(1 for x in non if (dto[x.pid] or 0) >= 1)
    _, pf = fisher_exact([[ca, len(imp) - ca], [cb, len(non) - cb]])
    A(f"\n改善群 {ca}/{len(imp)}例 vs 非改善群 {cb}/{len(non)}例、"
      f"Fisher の正確確率検定 {fp3(pf)}")

    # ベースラインの偏りの確認
    bta = [get_bl(x, "ΔMMSE_時間見当識") for x in imp]
    btb = [get_bl(x, "ΔMMSE_時間見当識") for x in non]
    A(f"\nベースラインの時間見当識は 改善群 {ms(bta)}点、非改善群 {ms(btb)}点"
      f"（{fp3(mw(bta, btb))}）。")
    lo = [x for x in pop if (get_bl(x, "ΔMMSE_時間見当識") or 9) <= max(bta)]
    la = [x for x in lo if x in imp]
    ln = [x for x in lo if x not in imp]
    A(f"ベースラインが{max(bta):g}点以下の症例に限ると、改善群{len(la)}例に対し"
      f"非改善群は{len(ln)}例"
      + (f"（{', '.join(x.pid for x in ln)}）" if ln else "")
      + "であった。")
    if ln:
        A(f"この{len(ln)}例の時間見当識の変化は "
          + "、".join(f"{x.pid} {outcomes(x)['ΔMMSE_時間見当識']:+g}点" for x in ln)
          + "であった。")

    with io.open(os.path.join(OUT, "abstract_d_numbers.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tbl[0].keys()))
        w.writeheader()
        for r in tbl:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    with io.open(os.path.join(OUT, "abstract_d_rates.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rate_rows[0].keys()))
        w.writeheader()
        w.writerows(rate_rows)

    text = "\n".join(R)
    with io.open(os.path.join(OUT, "abstract_d_report.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
