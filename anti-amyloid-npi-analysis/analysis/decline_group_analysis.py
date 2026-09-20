# -*- coding: utf-8 -*-
"""NPI-Apathy score 低下例／非低下例の比較（探索的・記述的）

群分け  低下例 : 初回→追跡時に NPI-Apathy score が1点以上低下
        非低下例: それ以外（不変・上昇）

この解析は既存データを確認したのちに設定した群分けであり、
研究開始前に規定したものではない。
非低下例には初回0点の症例を含むため、両群の比較は治療反応性の比較ではない。

出力する内容は、抄録で指摘された次の点をすべて数値で埋めるためのもの。
  (1) 両群の初回認知機能・初回NPI得点・観察期間
  (2) 両群の認知機能の変化（低下例だけでなく非低下例も）
  (3) 低下2例の下位項目変化が合計点変化と一致することの検証
  (4) 初回0点の実人数（平均値からの推定ではなく実データで数える）
"""
from __future__ import annotations

import csv
import io
import os
import statistics as stx
from typing import Optional

from npi_increase_analysis import (MMSE_SUB, CDR_DOM, build_cases,
                                   read_background, months, perm_mwu,
                                   fisher2x2, med_range)
from exhaustive_search import obs_months

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output_v4")
os.makedirs(OUT, exist_ok=True)


def ms(v: list[float]) -> str:
    """平均±標準偏差（前回抄録の記載様式に合わせる）。"""
    v = [x for x in v if x is not None]
    if not v:
        return "－"
    if len(v) == 1:
        return f"{v[0]:.1f}"
    return f"{stx.mean(v):.1f}±{stx.stdev(v):.1f}"


def group_of(c) -> str:
    return "低下例" if (c.d_npi is not None and c.d_npi <= -1) else "非低下例"


def main() -> None:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    inc.sort(key=lambda c: (c.pid[0],
                            int("".join(ch for ch in c.pid if ch.isdigit()))))
    dec = [c for c in inc if group_of(c) == "低下例"]
    non = [c for c in inc if group_of(c) == "非低下例"]

    R: list[str] = []
    A = R.append
    A("# NPI-Apathy score 低下例／非低下例の比較 — 抄録用の数値\n")
    A("**既存データを確認したのちに設定した群分けであり、"
      "研究開始前に規定した解析ではない。**\n")
    A(f"- 解析対象 {len(inc)}例（全例レカネマブ）")
    A(f"- 低下例 {len(dec)}例: {', '.join(c.pid for c in dec)}")
    A(f"- 非低下例 {len(non)}例: {', '.join(c.pid for c in non)}\n")

    # ---------------------------------------------- (4) 初回0点の実人数
    A("## 0. 初回NPI-Apathy scoreの分布（実人数）\n")
    A("| 群 | 初回0点 | 初回1点 | 初回2点以上 | 計 |")
    A("|---|---|---|---|---|")
    for lab, g in (("低下例", dec), ("非低下例", non)):
        z = sum(1 for c in g if c.npi_bl.score == 0)
        o = sum(1 for c in g if c.npi_bl.score == 1)
        t = sum(1 for c in g if c.npi_bl.score >= 2)
        A(f"| {lab} | {z} | {o} | {t} | {len(g)} |")
    A("\n初回スコアの実値")
    for lab, g in (("低下例", dec), ("非低下例", non)):
        A(f"- {lab}: " + "、".join(f"{c.pid}={c.npi_bl.score:g}→{c.npi_fu.score:g}"
                                  for c in g))

    # ---------------------------------------------- (1)(2) 両群の比較表
    A("\n## 1. 両群の比較（初回値・観察期間・変化量）\n")
    rows = []

    def add(label: str, fn, kind="num", p=True):
        a = [fn(c) for c in dec]
        b = [fn(c) for c in non]
        a = [x for x in a if x is not None]
        b = [x for x in b if x is not None]
        if not a or not b:
            rows.append({"項目": label, "低下例": "－", "非低下例": "－",
                         "p": None, "備考": "一方の群に値がない"})
            return
        pv = perm_mwu(a, b)["p"] if p and len(set(a + b)) > 1 else None
        rows.append({"項目": label, "低下例": ms(a), "非低下例": ms(b),
                     "低下例の値": "、".join(f"{x:g}" for x in a),
                     "非低下例の値": "、".join(f"{x:g}" for x in sorted(b)),
                     "低下例n": len(a), "非低下例n": len(b),
                     "p": None if pv is None else round(pv, 4)})

    add("年齢（歳）", lambda c: BG.get(c.pid, {}).get("年齢"))
    add("観察期間（月）", obs_months)
    add("初回 NPI-Apathy score", lambda c: c.npi_bl.score)
    add("追跡時 NPI-Apathy score", lambda c: c.npi_fu.score)
    add("初回 MMSE合計", lambda c: c.bl_fu("MMSE", "__total__")[0])
    add("追跡時 MMSE合計", lambda c: c.bl_fu("MMSE", "__total__")[1])
    add("Δ MMSE合計", lambda c: c.delta("MMSE", "__total__"))
    add("初回 CDR-SB", lambda c: c.bl_fu("CDR", "__total__")[0])
    add("追跡時 CDR-SB", lambda c: c.bl_fu("CDR", "__total__")[1])
    add("Δ CDR-SB", lambda c: c.delta("CDR", "__total__"))
    add("初回 MMSE 時間見当識", lambda c: c.bl_fu("MMSE", "時間見当識")[0])
    add("追跡時 MMSE 時間見当識", lambda c: c.bl_fu("MMSE", "時間見当識")[1])
    add("Δ MMSE 時間見当識", lambda c: c.delta("MMSE", "時間見当識"))
    for k in MMSE_SUB:
        if k != "時間見当識":
            add(f"Δ MMSE {k}", lambda c, kk=k: c.delta("MMSE", kk))
    for k in CDR_DOM:
        add(f"Δ CDR {k}", lambda c, kk=k: c.delta("CDR", kk))

    A("| 項目 | 低下例 | 非低下例 | p | 低下例の値 | 非低下例の値 |")
    A("|---|---|---|---|---|---|")
    for r in rows:
        A(f"| {r['項目']} | {r['低下例']} | {r['非低下例']} | "
          f"{r.get('p') if r.get('p') is not None else '－'} | "
          f"{r.get('低下例の値', '')} | {r.get('非低下例の値', '')} |")

    # 女性割合（背景ファイルは「女性」「男性」で記録されている）
    SEX = ("女性", "男性")
    fa = sum(1 for c in dec if BG.get(c.pid, {}).get("性別") == "女性")
    fb = sum(1 for c in non if BG.get(c.pid, {}).get("性別") == "女性")
    na = sum(1 for c in dec if BG.get(c.pid, {}).get("性別") in SEX)
    nb = sum(1 for c in non if BG.get(c.pid, {}).get("性別") in SEX)
    fp = fisher2x2(fa, na - fa, fb, nb - fb)
    A(f"\n- 女性: 低下例 {fa}/{na}例、非低下例 {fb}/{nb}例（Fisher正確検定 p={fp:.4f}）")

    # 観察期間：評価日が欠測の症例があるため、時点ラベルの分布も併記する
    A("\n### 観察期間と評価時点\n")
    A("| 研究番号 | 群 | 追跡時点ラベル | 評価日から求めた観察期間（月） |")
    A("|---|---|---|---|")
    for c in inc:
        fv = c.followup_visit("MMSE")
        m = obs_months(c)
        A(f"| {c.pid} | {group_of(c)} | {fv.label if fv else '－'} | "
          f"{'－（評価日が欠測）' if m is None else f'{m:.1f}'} |")
    from collections import Counter
    for lab, g in (("低下例", dec), ("非低下例", non)):
        cnt = Counter(c.followup_visit("MMSE").label for c in g
                      if c.followup_visit("MMSE"))
        A(f"\n- {lab}の追跡時点ラベル: "
          + "、".join(f"{k} {v}例" for k, v in sorted(cnt.items())))
        mm = [obs_months(c) for c in g]
        ok = [x for x in mm if x is not None]
        A(f"  - 評価日から観察期間を算出できたのは {len(ok)}/{len(g)}例"
          + (f"（{ms(ok)}か月）" if ok else ""))

    # ---------------------------------------------- (2) 変化の方向の内訳
    A("\n## 2. 認知機能の変化の内訳（両群とも提示する）\n")
    A("| 項目 | 群 | 改善 | 不変 | 悪化 |")
    A("|---|---|---|---|---|")
    for label, sh, key, better in (("MMSE合計", "MMSE", "__total__", 1),
                                   ("MMSE 時間見当識", "MMSE", "時間見当識", 1),
                                   ("CDR-SB", "CDR", "__total__", -1)):
        for lab, g in (("低下例", dec), ("非低下例", non)):
            ds = [c.delta(sh, key) for c in g]
            ds = [d for d in ds if d is not None]
            imp = sum(1 for d in ds if d * better > 0)
            unc = sum(1 for d in ds if d == 0)
            wor = sum(1 for d in ds if d * better < 0)
            A(f"| {label} | {lab} | {imp}/{len(ds)} | {unc}/{len(ds)} | "
              f"{wor}/{len(ds)} |")

    # 時間見当識の改善例のFisher検定
    ia = sum(1 for c in dec if (c.delta("MMSE", "時間見当識") or 0) > 0)
    ib = sum(1 for c in non if (c.delta("MMSE", "時間見当識") or 0) > 0)
    p_to = fisher2x2(ia, len(dec) - ia, ib, len(non) - ib)
    A(f"\n- 時間見当識が改善した症例: 低下例 {ia}/{len(dec)}、"
      f"非低下例 {ib}/{len(non)}（Fisher正確検定 p={p_to:.4f}）")
    A(f"- この2×2表で到達しうる最小の両側p値は "
      f"{fisher2x2(len(dec), 0, 0, len(non)):.4f} である。")

    # ---------------------------------------------- (3) 低下2例の詳細
    A("\n## 3. 低下例の個別データと合計点との整合性\n")
    detail = []
    for c in dec:
        A(f"\n### {c.pid}")
        bg = BG.get(c.pid, {})
        fv = c.followup_visit("MMSE")
        A(f"- 年齢 {bg.get('年齢')}歳、性別 {bg.get('性別')}、"
          f"観察期間 {obs_months(c)}か月（追跡時点ラベル「{fv.label}」）")
        A(f"- NPI-Apathy score {c.npi_bl.score:g}→{c.npi_fu.score:g}"
          f"（頻度F {c.npi_bl.freq}→{c.npi_fu.freq}、"
          f"重症度S {c.npi_bl.sev}→{c.npi_fu.sev}）")
        A(f"- 易怒性 初回「{c.npi_bl.irrit}」→追跡時「{c.npi_fu.irrit}」")
        bt, ft = c.bl_fu("MMSE", "__total__")
        A(f"- MMSE合計 {bt:g}→{ft:g}（Δ{ft - bt:+g}）")
        chg = []
        ssum = 0.0
        for k in MMSE_SUB:
            b, f = c.bl_fu("MMSE", k)
            if b is None or f is None:
                A(f"  - {k}: 欠測")
                continue
            ssum += f - b
            if f != b:
                chg.append(f"{k} {b:g}→{f:g}")
        A(f"  - 変化した下位項目: {'、'.join(chg) if chg else 'なし'}")
        A(f"  - **下位項目Δの総和 {ssum:+g} / 合計点Δ {ft - bt:+g} → "
          f"{'一致' if abs(ssum - (ft - bt)) < 1e-9 else '不一致（要原票照合）'}**")
        bs, fs = c.bl_fu("CDR", "__total__")
        A(f"- CDR-SB {bs:g}→{fs:g}（Δ{fs - bs:+g}）")
        cchg, csum = [], 0.0
        for k in CDR_DOM:
            b, f = c.bl_fu("CDR", k)
            if b is None or f is None:
                continue
            csum += f - b
            if f != b:
                cchg.append(f"{k} {b:g}→{f:g}")
        A(f"  - 変化した領域: {'、'.join(cchg) if cchg else 'なし'}")
        A(f"  - **領域Δの総和 {csum:+g} / CDR-SB Δ {fs - bs:+g} → "
          f"{'一致' if abs(csum - (fs - bs)) < 1e-9 else '不一致（要原票照合）'}**")
        detail.append({"研究番号": c.pid, "年齢": bg.get("年齢"),
                       "性別": bg.get("性別"), "観察期間": obs_months(c),
                       "MMSE": f"{bt:g}→{ft:g}", "CDR-SB": f"{bs:g}→{fs:g}",
                       "変化したMMSE下位項目": "、".join(chg),
                       "変化したCDR領域": "、".join(cchg)})

    # ---------------------------------------------- (4) 合計点の整合性（全例）
    A("\n## 4. MMSE合計点と下位項目合計の整合性（解析対象14例すべて）\n")
    A("原票（添付PDF）そのものとの照合はこの環境では行えない。"
      "ここで確認できるのは、解析用ファイル内部の整合性のみである。\n")
    A("| 研究番号 | 時点 | 記載された合計 | 下位項目の合計 | 判定 |")
    A("|---|---|---|---|---|")
    bad = 0
    for c in inc:
        for v in c.mmse:
            if v.total is None:
                continue
            sub = [v.items.get(k) for k in MMSE_SUB]
            if any(x is None for x in sub):
                continue
            s = sum(sub)
            ok = abs(s - v.total) < 1e-9
            if not ok:
                bad += 1
                A(f"| {c.pid} | {v.label} | {v.total:g} | {s:g} | **不一致** |")
    A(f"\n- 解析対象14例では不一致 **{bad}件**。")
    A("- 解析対象外では L45（12か月、19 vs 17）と D16（6か月、21 vs 19）に"
      "不一致がある。いずれも本解析には含まれない。")
    A("- 値の訂正・補完は行っていない。")

    io.open(os.path.join(OUT, "v4_低下例_非低下例の比較.md"), "w",
            encoding="utf-8").write("\n".join(R))

    with io.open(os.path.join(OUT, "v4_群間比較.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in keys})
    print("\n".join(R))


if __name__ == "__main__":
    main()
