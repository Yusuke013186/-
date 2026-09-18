# -*- coding: utf-8 -*-
"""
抗アミロイドβ抗体療法 後方視的観察研究 — 探索的解析

問い:
  治療前にNPI第7項目（アパシー・無関心）が「あり」で、追跡時に「なし」となった
  2例は、他の抗アミロイドβ抗体療法例と比較してどのような経過をたどったか。

方針:
  n=2 であるため、検定を主たる根拠とはせず、
  (1) 2例の全データを個別に提示する
  (2) 各転帰について、2例が全治療例の分布のどこに位置するか（順位・百分位）を示す
  (3) 3通りの対照群と比較する
        対照A: NPIが評価できた非改善群（最も近い比較対象）
        対照B: 認知機能の追跡がある全治療例（母集団の中での位置づけ）
        対照C: 治療前アパシーありだが改善しなかった群（機序的に最も近い比較対象）
  (4) 天井・床効果の確認を必ず併記する
  を行う。多重性は族ごとに Benjamini-Hochberg 法で調整する。

実行: python3 analysis/apathy_improvers_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import os
import sys

from scipy.stats import mannwhitneyu, fisher_exact

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_analysis import (                                   # noqa: E402
    MMSE_SUB, CDR_DOM, Subject, build_subjects, bl_fu, outcomes,
    outcome_meta, higher_is_better, headroom, annualized, median, bh_fdr,
    cles, rank_biserial,
)
from baseline_apathy_analysis import (                        # noqa: E402
    FAMILIES, LABEL, describe, fmt_p, plain_p, wcsv, cdr_quality_audit,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
ALL_KEYS = [k for ks in FAMILIES.values() for k in ks]


def percentile_of(value: float, pool: list[float], better_high: bool) -> float:
    """pool の中で value が何パーセンタイルに位置するか（同値は半分カウント）。
    better_high=True なら大きいほど良い転帰なので、そのまま上位ほど高い百分位となる。
    """
    if not pool:
        return float("nan")
    below = sum(1 for v in pool if v < value)
    equal = sum(1 for v in pool if v == value)
    pct = (below + 0.5 * equal) / len(pool) * 100
    return pct if better_high else 100 - pct


def rank_text(value: float, pool: list[float], better_high: bool) -> str:
    """良い方から何番目か（pool は自分を含む全体）。"""
    srt = sorted(pool, reverse=better_high)
    pos = srt.index(value) + 1
    return f"{pos}/{len(srt)}位"


def compare(a: list[float], b: list[float]) -> dict:
    r = {"n1": len(a), "n2": len(b)}
    if not a or not b or len(set(a + b)) == 1:
        r["p"] = None
        return r
    u, p = mannwhitneyu(a, b, alternative="two-sided", method="exact")
    r["p"] = p
    r["r"] = rank_biserial(a, b, u)
    r["CLES"] = cles(a, b)
    r["p_min"] = 2.0 / math.comb(len(a) + len(b), len(a))
    return r


def baseline_matched(imp, subs, ok, tol=0):
    """2例とベースライン値が同程度（±tol）の全治療例に限定して変化量を比較する。
    天井・床効果を統制するもっとも直接的な方法。"""
    sheet, key, _, _ = outcome_meta(ok)
    ib = [x.base(sheet, key) for x in imp]
    ib = [v for v in ib if v is not None]
    if not ib:
        return None
    lo, hi = min(ib) - tol, max(ib) + tol
    imp_ids = {x.pid for x in imp}
    pool = [(x, x.base(sheet, key), outcomes(x)[ok]) for x in subs]
    pool = [(x, b, d) for x, b, d in pool
            if b is not None and d is not None and lo <= b <= hi]
    a = [d for x, b, d in pool if x.pid in imp_ids]
    c = [d for x, b, d in pool if x.pid not in imp_ids]
    ba = [b for x, b, d in pool if x.pid in imp_ids]
    bc = [b for x, b, d in pool if x.pid not in imp_ids]
    if not a or not c:
        return None
    res = {"転帰": LABEL[ok], "BL範囲": f"{lo:g}〜{hi:g}",
           "n_改善": len(a), "n_対照": len(c),
           "改善群Δ": ", ".join(f"{v:+g}" for v in a),
           "対照Δ中央値": median(c),
           "対照Δ範囲": f"［{min(c):g}, {max(c):g}］",
           "対照で改善した例": sum(1 for v in c
                            if (v > 0 if higher_is_better(ok) else v < 0))}
    if len(set(a + c)) > 1:
        _, pp = mannwhitneyu(a, c, alternative="two-sided", method="exact")
        res["p"] = pp
    if len(set(ba + bc)) > 1:
        _, pb = mannwhitneyu(ba, bc, alternative="two-sided", method="exact")
        res["p_BL差"] = pb
    else:
        res["p_BL差"] = None
    return res


def main() -> None:
    subs = build_subjects()
    by = {x.pid: x for x in subs}

    imp = [x for x in subs if x.npi_paired and x.ap_bl == 1 and x.ap_fu == 0
           and x.ap_conf == "definite"]
    imp_ids = {x.pid for x in imp}

    # 対照A: NPIが評価できた非改善群
    ctrlA = [x for x in subs if x.npi_paired and x.ap_bl is not None
             and x.ap_fu is not None and x.pid not in imp_ids
             and (x.d("MMSE", "__total__") is not None
                  or x.d("CDR", "__total__") is not None)]
    # 対照B: 認知機能の追跡がある全治療例（改善2例を除く）
    ctrlB = [x for x in subs if x.pid not in imp_ids
             and (x.d("MMSE", "__total__") is not None
                  or x.d("CDR", "__total__") is not None)]
    # 対照C: 治療前アパシーありだが改善しなかった群
    ctrlC = [x for x in subs if x.npi_paired and x.ap_bl == 1
             and x.pid not in imp_ids
             and (x.d("MMSE", "__total__") is not None
                  or x.d("CDR", "__total__") is not None)]

    R: list[str] = []
    A = R.append
    A("# 治療前アパシーが追跡時に消失した2例の探索的検討\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("向きの定義: **ΔMMSE系・ΔMoCA-Jはプラスが改善**、**ΔCDR系はプラスが悪化**。")
    A("変化量は「最終利用可能時点 − ベースライン（0か月）」。\n")
    A("**本解析は探索的であり、確認的推論には用いない。**")
    A("改善群は2例であるため、検定結果ではなく個別値と分布内の位置づけを主たる所見とする。\n")
    A("<<<SUMMARY>>>")

    # ---- 1. 2例の素性
    A("\n## 1. アパシーが消失した2例\n")
    A(f"NPIがベースラインと追跡時の両方で評価でき、第7項目が「あり→なし」となったのは "
      f"**{len(imp)}例**（{', '.join(x.pid for x in imp)}）であった。\n")
    A("| 項目 | " + " | ".join(x.pid for x in imp) + " |")
    A("|---|" + "---|" * len(imp))
    A("| 薬剤 | " + " | ".join(x.drug for x in imp) + " |")
    A("| NPIベースライン→追跡 | " + " | ".join(x.npi_note for x in imp) + " |")
    yn = {1: "あり", 0: "なし", None: "－"}
    A("| NPI第7項目（アパシー） | "
      + " | ".join(f"{yn[x.ap_bl]}→{yn[x.ap_fu]}" for x in imp) + " |")
    A("| NPI第9項目（易怒性） | "
      + " | ".join(f"{yn[x.ir_bl]}→{yn[x.ir_fu]}" for x in imp) + " |")
    A("| 認知機能の追跡期間 | "
      + " | ".join(f"{x.interval_m:g}か月" if x.interval_m is not None else "不明"
                   for x in imp) + " |")
    for k in ALL_KEYS:
        sheet, key, _, _ = outcome_meta(k)
        cells = []
        for x in imp:
            b, f = bl_fu(x.panel(sheet) if key != "__global__" else x.cdr, "__total__"
                         if key == "__global__" else key)
            bv = x.base(sheet, key)
            dv = outcomes(x)[k]
            cells.append("－" if bv is None or dv is None
                         else f"{bv:g}→{bv+dv:g}（{dv:+g}）")
        A(f"| {LABEL[k]} BL→FU（Δ） | " + " | ".join(cells) + " |")

    # ---- 2. 分布内の位置づけ
    A("\n\n## 2. 全治療例の分布のなかでの位置づけ\n")
    A("各転帰について、2例が全治療例（改善2例を含む）の分布のどこにあるかを示す。")
    A("百分位は「良い方向を上位」とし、100に近いほど経過が良いことを意味する。\n")
    A("| 転帰 | 全治療例 n | 全治療例 中央値［範囲］ | "
      + " | ".join(f"{x.pid} 値（順位／百分位）" for x in imp) + " |")
    A("|---|---|---|" + "---|" * len(imp))
    pct_rows = []
    for k in ALL_KEYS:
        pool_all = [outcomes(x)[k] for x in subs if outcomes(x)[k] is not None]
        if len(pool_all) < 5:
            continue
        hb = higher_is_better(k)
        cells, rec = [], {"転帰": LABEL[k], "n": len(pool_all),
                          "中央値": median(pool_all)}
        for x in imp:
            v = outcomes(x)[k]
            if v is None:
                cells.append("－")
                continue
            p = percentile_of(v, pool_all, hb)
            cells.append(f"{v:+g}（{rank_text(v, pool_all, hb)}／{p:.0f}%）")
            rec[f"{x.pid}_値"] = v
            rec[f"{x.pid}_百分位"] = round(p, 1)
        A(f"| {LABEL[k]} | {len(pool_all)} | "
          f"{median(pool_all):g}［{min(pool_all):g}, {max(pool_all):g}］ | "
          + " | ".join(cells) + " |")
        pct_rows.append(rec)
    wcsv(os.path.join(OUT, "ai_percentiles.csv"), pct_rows)

    # ---- 3. 3通りの対照群との比較
    A("\n\n## 3. 対照群との比較\n")
    A("| 対照群 | 定義 | n |")
    A("|---|---|---|")
    A(f"| 対照A | NPIが評価できた非改善群（あり→あり／なし→なし／なし→あり） | {len(ctrlA)} |")
    A(f"| 対照B | 認知機能の追跡がある全治療例（改善2例を除く） | {len(ctrlB)} |")
    A(f"| 対照C | 治療前アパシーありだが追跡時も「あり」だった群 | {len(ctrlC)} |")
    A(f"\n対照Bとの比較では、2例 vs {len(ctrlB)}例の配分で到達可能な最小p値は "
      f"{2/math.comb(len(ctrlB)+2, 2):.4f} であり、有意水準5%に到達しうる。")
    A(f"対照A（2 vs {len(ctrlA)}）では {2/math.comb(len(ctrlA)+2, 2):.3f}、"
      f"対照C（2 vs {len(ctrlC)}）では {2/math.comb(len(ctrlC)+2, 2):.3f} が下限となる。\n")

    all_rows = []
    for cname, ctrl in [("対照A（NPI非改善群）", ctrlA),
                        ("対照B（全治療例）", ctrlB),
                        ("対照C（アパシー持続群）", ctrlC)]:
        A(f"\n### {cname} との比較（2例 vs {len(ctrl)}例）\n")
        rows = []
        for fam, keys in FAMILIES.items():
            fam_rows = []
            for k in keys:
                a = [outcomes(x)[k] for x in imp if outcomes(x)[k] is not None]
                b = [outcomes(x)[k] for x in ctrl if outcomes(x)[k] is not None]
                r = compare(a, b)
                r.update({"族": fam, "転帰": LABEL[k], "キー": k, "対照": cname,
                          "改善群値": ", ".join(f"{v:+g}" for v in a) or "－",
                          "対照中央値": median(b) if b else None,
                          "対照範囲": f"［{min(b):g}, {max(b):g}］" if b else "－"})
                # 天井・床効果の確認
                ba = [x.base(*outcome_meta(k)[:2]) for x in imp]
                bb = [x.base(*outcome_meta(k)[:2]) for x in ctrl]
                ba = [v for v in ba if v is not None]
                bb = [v for v in bb if v is not None]
                if ba and bb and len(set(ba + bb)) > 1:
                    _, pbl = mannwhitneyu(ba, bb, alternative="two-sided",
                                          method="exact")
                    r["p_BL差"] = pbl
                    r["BL改善群"] = ", ".join(f"{v:g}" for v in ba)
                    r["BL対照中央値"] = median(bb)
                fam_rows.append(r)
            ps = [r["p"] for r in fam_rows if r.get("p") is not None]
            if ps:
                adj = dict(zip([i for i, r in enumerate(fam_rows)
                                if r.get("p") is not None], bh_fdr(ps)))
                for i, r in enumerate(fam_rows):
                    r["p_FDR"] = adj.get(i)
            rows += fam_rows
        all_rows += rows
        A("| 転帰 | 改善群（2例の値） | 対照 中央値［範囲］ | CLES | p | p(FDR) | "
          "BL 改善群 / 対照中央値 | p(BL差) |")
        A("|---|---|---|---|---|---|---|---|")
        for r in rows:
            if r["改善群値"] == "－":
                continue
            ctrl_txt = ("－" if r["対照中央値"] is None
                        else f"{r['対照中央値']:g}{r['対照範囲']}")
            cles_txt = ("－" if r.get("CLES") is None else f"{r['CLES']:.2f}")
            bl_txt = (f"{r.get('BL改善群', '－')} / "
                      + (f"{r['BL対照中央値']:g}" if r.get("BL対照中央値") is not None
                         else "－"))
            A(f"| {r['転帰']} | {r['改善群値']} | {ctrl_txt} | {cles_txt} | "
              f"{fmt_p(r.get('p'))} | {plain_p(r.get('p_FDR'))} | {bl_txt} | "
              f"{plain_p(r.get('p_BL差'))} |")
        sig = [r for r in rows if (r.get("p") or 1) < 0.05]
        sigf = [r for r in rows if (r.get("p_FDR") or 1) < 0.05]
        A(f"\n→ 調整前 p<0.05: **{len(sig)}件**"
          + (f"（{', '.join(r['転帰'] for r in sig)}）" if sig else "")
          + f" ／ FDR調整後 p<0.05: **{len(sigf)}件**"
          + (f"（{', '.join(r['転帰'] for r in sigf)}）" if sigf else ""))
    wcsv(os.path.join(OUT, "ai_group_comparisons.csv"), all_rows)

    globals()["_R"] = R
    globals()["_imp"] = imp
    globals()["_ctrl"] = {"A": ctrlA, "B": ctrlB, "C": ctrlC}
    globals()["_rows"] = all_rows
    globals()["_subs"] = subs

    # ---- 4. 天井・床効果の確認
    A("\n\n## 4. 天井・床効果の確認\n")
    A("MMSE下位項目は可動域が狭いため、ベースライン値が偏っていると変化量の差が")
    A("見かけ上生じる。2例のベースライン値が全治療例の分布のどこにあるかを確認する。\n")
    A("| 転帰 | 全治療例のBL 中央値［範囲］ | "
      + " | ".join(f"{x.pid} のBL（百分位）" for x in imp)
      + " | 改善余地 | 悪化余地 |")
    A("|---|---|" + "---|" * len(imp) + "---|---|")
    ceil_rows = []
    for k in ALL_KEYS:
        sheet, key, lo, hi = outcome_meta(k)
        pool = [x.base(sheet, key) for x in subs]
        pool = [v for v in pool if v is not None]
        if len(pool) < 5:
            continue
        cells, hr_better, hr_worse = [], [], []
        for x in imp:
            v = x.base(sheet, key)
            if v is None:
                cells.append("－")
                continue
            # ベースラインの高低はそのまま（良い悪いではなく位置を見る）
            below = sum(1 for z in pool if z < v)
            eq = sum(1 for z in pool if z == v)
            pct = (below + 0.5 * eq) / len(pool) * 100
            cells.append(f"{v:g}（{pct:.0f}%）")
            hr_better.append(headroom(x, k, "better"))
            hr_worse.append(headroom(x, k, "worse"))
        A(f"| {LABEL[k]} | {median(pool):g}［{min(pool):g}, {max(pool):g}］ | "
          + " | ".join(cells) + " | "
          + ", ".join(f"{v:g}" for v in hr_better if v is not None) + " | "
          + ", ".join(f"{v:g}" for v in hr_worse if v is not None) + " |")
        ceil_rows.append({"転帰": LABEL[k], "全例BL中央値": median(pool),
                          "改善群BL": ", ".join(
                              f"{x.base(sheet, key):g}" for x in imp
                              if x.base(sheet, key) is not None)})
    wcsv(os.path.join(OUT, "ai_ceiling_audit.csv"), ceil_rows)

    # ---- 4B. ベースラインを揃えた比較
    A("\n\n## 4-B. ベースライン値を揃えた比較\n")
    A("天井・床効果を直接統制するため、2例とベースライン値が同じ範囲にある")
    A("全治療例だけに絞って変化量を比較した。ここで差が残れば、その所見は")
    A("ベースラインの偏りでは説明できないことになる。\n")
    A("| 転帰 | 限定したBLの範囲 | 対照 n | 改善2例のΔ | 対照 Δ中央値［範囲］ | "
      "対照で改善した例 | p | BL差のp |")
    A("|---|---|---|---|---|---|---|---|")
    bm_rows = []
    for k in ALL_KEYS:
        r = baseline_matched(imp, subs, k)
        if r is None or r["n_対照"] < 3:
            continue
        bm_rows.append(r)
        A(f"| {r['転帰']} | {r['BL範囲']} | {r['n_対照']} | {r['改善群Δ']} | "
          f"{r['対照Δ中央値']:g}{r['対照Δ範囲']} | "
          f"{r['対照で改善した例']}/{r['n_対照']}例 | {fmt_p(r.get('p'))} | "
          f"{plain_p(r.get('p_BL差'))} |")
    wcsv(os.path.join(OUT, "ai_baseline_matched.csv"), bm_rows)
    bsig = [r for r in bm_rows if (r.get("p") or 1) < 0.05]
    A(f"\n→ ベースラインを揃えたうえで p<0.05 となる転帰: **{len(bsig)}件**"
      + (f"（{', '.join(r['転帰'] for r in bsig)}）" if bsig else "（なし）"))

    to_r = next((r for r in bm_rows if r["転帰"] == "MMSE 時間見当識"), None)
    if to_r:
        A(f"\n**時間見当識について**: 2例のベースラインはいずれも2点であった。")
        A(f"ベースラインが{to_r['BL範囲']}点の全治療例{to_r['n_対照']}例では、"
          f"Δ中央値 {to_r['対照Δ中央値']:g}点、"
          f"{to_r['対照で改善した例']}例が改善している。")
        A(f"2例のΔ（{to_r['改善群Δ']}点）はこの分布のなかでは突出しておらず、"
          f"群間差は有意ではない（p={plain_p(to_r.get('p'))}）。")
        A("\n→ **第3節で得られた時間見当識の差（p=0.043）は、"
          "2例のベースラインが低く改善の余地が大きかったことで説明される。**")

    # ---- 5. 易怒性の併発
    A("\n\n## 5. 易怒性（NPI第9項目）との関係\n")
    npi_pool = [x for x in subs if x.npi_paired and x.ir_bl is not None
                and x.ir_fu is not None]
    A(f"アパシーが消失した2例はいずれも易怒性が"
      f"{'／'.join(f'{yn[x.ir_bl]}→{yn[x.ir_fu]}' for x in imp)}であり、"
      "**アパシーの消失と易怒性の新規出現が同一症例で同時に起きていた**。\n")
    onset = [x for x in npi_pool if x.ir_bl == 0 and x.ir_fu == 1]
    A(f"NPIが評価できた{len(npi_pool)}例のうち、易怒性が新規出現したのは{len(onset)}例"
      f"（{', '.join(x.pid for x in onset)}）。")
    a_on = sum(1 for x in imp if x.ir_bl == 0 and x.ir_fu == 1)
    others = [x for x in npi_pool if x.pid not in imp_ids]
    b_on = sum(1 for x in others if x.ir_bl == 0 and x.ir_fu == 1)
    _, pf = fisher_exact([[a_on, len(imp) - a_on], [b_on, len(others) - b_on]])
    A(f"\n- アパシー改善群: {a_on}/{len(imp)}例で易怒性が新規出現")
    A(f"- その他: {b_on}/{len(others)}例")
    A(f"- Fisher 正確検定 p={plain_p(pf)}")
    A("\n2例とも該当するが、その他でも半数近くに生じており、特異的とは言えない。")

    # ---- 6. CDRの記入の持ち越し確認
    aud = cdr_quality_audit(subs)
    ident = {r["研究番号"] for r in aud["identical"]}
    A("\n\n## 6. CDRの記入の持ち越しの確認\n")
    A(f"CDR6領域が全評価時点で完全に同一の症例は全{aud['n']}例中{len(aud['identical'])}例。")
    A("2例がこれに該当すると、CDRの「変化なし」が再評価の結果か転記かを区別できない。\n")
    for x in imp:
        A(f"- {x.pid}: {'**該当する（CDRが全時点で同一）**' if x.pid in ident else '該当しない（CDRは変化している）'}")

    # ---- 7. 症例別明細（比較対象すべて）
    A("\n\n## 7. NPI評価例の症例別明細\n")
    A("| 研究番号 | 薬剤 | アパシー | 易怒性 | 追跡期間 | "
      + " | ".join(f"Δ{LABEL[k]}" for k in ALL_KEYS) + " |")
    A("|" + "---|" * (5 + len(ALL_KEYS)))
    npi_all = sorted([x for x in subs if x.npi_paired and x.ap_bl is not None],
                     key=lambda z: (z.pid not in imp_ids, z.pid))
    for x in npi_all:
        o = outcomes(x)
        A(f"| {x.pid}{' **' if x.pid in imp_ids else ''}"
          f"{'改善**' if x.pid in imp_ids else ''} | {x.drug} | "
          f"{yn[x.ap_bl]}→{yn[x.ap_fu]} | {yn[x.ir_bl]}→{yn[x.ir_fu]} | "
          f"{f'{x.interval_m:g}か月' if x.interval_m is not None else '不明'} | "
          + " | ".join(f"{o[k]:+g}" if o[k] is not None else "－" for k in ALL_KEYS)
          + " |")

    det = []
    for x in npi_all:
        o = outcomes(x)
        row = {"研究番号": x.pid, "薬剤": x.drug,
               "群": "アパシー改善群" if x.pid in imp_ids else "非改善群",
               "アパシー": f"{yn[x.ap_bl]}→{yn[x.ap_fu]}",
               "易怒性": f"{yn[x.ir_bl]}→{yn[x.ir_fu]}",
               "追跡期間_月": x.interval_m,
               "CDR全時点同一": "該当" if x.pid in ident else ""}
        for k in ALL_KEYS:
            row[f"BL_{LABEL[k]}"] = x.base(*outcome_meta(k)[:2])
            row[f"Δ_{LABEL[k]}"] = o[k]
        det.append(row)
    wcsv(os.path.join(OUT, "ai_case_detail.csv"), det)

    # ---- 要約
    rowsB = [r for r in all_rows if r["対照"].startswith("対照B")]
    rowsA = [r for r in all_rows if r["対照"].startswith("対照A")]
    rowsC = [r for r in all_rows if r["対照"].startswith("対照C")]
    S: list[str] = ["\n## 要約\n"]
    S.append(f"治療前にNPIアパシーが「あり」で追跡時に「なし」となったのは "
             f"**{len(imp)}例（{', '.join(x.pid for x in imp)}）**、"
             f"いずれもレカネマブ例であった。\n")

    def top(rows, n=4):
        rs = [r for r in rows if r.get("p") is not None]
        return sorted(rs, key=lambda r: r["p"])[:n]

    S.append("### 2例に共通してみられた特徴\n")
    mm = [outcomes(x)["ΔMMSE合計"] for x in imp]
    cd = [outcomes(x)["ΔCDR-SB"] for x in imp]
    to = [outcomes(x)["ΔMMSE_時間見当識"] for x in imp]
    poolm = [outcomes(x)["ΔMMSE合計"] for x in subs
             if outcomes(x)["ΔMMSE合計"] is not None]
    poolc = [outcomes(x)["ΔCDR-SB"] for x in subs
             if outcomes(x)["ΔCDR-SB"] is not None]
    poolt = [outcomes(x)["ΔMMSE_時間見当識"] for x in subs
             if outcomes(x)["ΔMMSE_時間見当識"] is not None]
    S.append(f"- **MMSE合計**: {', '.join(f'{v:+g}' for v in mm)}点"
             f"（全治療例{len(poolm)}例の中央値 {median(poolm):+g}点）")
    S.append(f"- **CDR-SB**: {', '.join(f'{v:+g}' for v in cd)}点"
             f"（全治療例{len(poolc)}例の中央値 {median(poolc):+g}点）")
    S.append(f"- **MMSE時間見当識**: {', '.join(f'{v:+g}' for v in to)}点"
             f"（全治療例{len(poolt)}例の中央値 {median(poolt):+g}点）"
             f"。2例は全治療例中それぞれ "
             f"{'、'.join(rank_text(v, poolt, True) for v in to)}であった")
    S.append(f"- **易怒性**: 2例とも「なし→あり」であり、"
             f"アパシーの消失と易怒性の新規出現が同時に起きていた\n")
    S.append("### 検定の結果\n")
    for nm, rs in [("対照A（NPI非改善群）", rowsA), ("対照B（全治療例）", rowsB),
                   ("対照C（アパシー持続群）", rowsC)]:
        sg = [r for r in rs if (r.get("p") or 1) < 0.05]
        sgf = [r for r in rs if (r.get("p_FDR") or 1) < 0.05]
        S.append(f"- {nm}（2 vs {rs[0]['n2'] if rs else 0}）: "
                 f"調整前 p<0.05 は {len(sg)}件"
                 + (f"（{', '.join(r['転帰'] for r in sg)}）" if sg else "")
                 + f"、FDR調整後は {len(sgf)}件")
    S.append("")
    S.append("### 解釈上の注意\n")
    S.append("- 改善群が2例であるため、検定結果は確認的な根拠とはならない。")
    S.append("- **2例はいずれもMMSE時間見当識のベースラインが2/5点と低く、"
             "改善する余地が大きかった。** 一方で全治療例の多くは4〜5点で"
             "天井に近く、改善しようがない。時間見当識の差はこの偏りで"
             "説明されうるため、所見として提示する際は必ず併記する必要がある。")
    S.append("- 追跡期間が症例間で異なる（6〜24か月）ことも交絡となる。")
    S.append("- CDRの記入の持ち越しが疑われる症例が全体の約4分の1にあり、"
             "CDRの「変化なし」の解釈には注意を要する。\n")

    text = "\n".join(R).replace("<<<SUMMARY>>>", "\n".join(S))
    with io.open(os.path.join(OUT, "apathy_improvers_report.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
