# -*- coding: utf-8 -*-
"""
NPI-Apathy score に基づくアパシー改善群の解析（抄録E用）

定義:
  アパシー改善 = NPI-Apathy score（頻度F×重症度S、0〜12点）が
                 ベースラインから1点以上低下した症例

本スクリプトは次の3点を行う。
  1. 認知機能の評価時点の監査。どの症例のどの時点のデータが実在するかを明示し、
     「18か月後」と記載できるかを検証する。
  2. 固定時点（6か月・12か月・18か月）および最終利用可能時点のそれぞれで、
     改善群と非改善群の患者背景・認知機能を比較する。
  3. NPI-Apathy score そのものを、ベースラインと追跡時の両方で群間比較する。

統計は前回抄録（日本神経学会 No.1000218）の様式に合わせ、
平均±標準偏差、Mann-Whitney U 検定、Fisher の正確確率検定を用いる。

実行: python3 analysis/apathy_score_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

import openpyxl
from scipy.stats import mannwhitneyu, fisher_exact

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_analysis import (                                   # noqa: E402
    FILES, MMSE_SUB, CDR_DOM, MONTH_LABELS, Subject, build_subjects,
    bl_fu, outcome_meta, median, s, to_float, parse_date,
)
from abstract_d_analysis import ms, mw, fp, fp3, load_background   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
TPS = ["6か月", "12か月", "18か月", "24か月"]


# ---------------------------------------------------------------- NPIスコア

@dataclass
class NpiScore:
    label: str
    orig_label: str
    score: Optional[float]
    presence: str
    freq: Optional[float]
    sev: Optional[float]
    irrit: str
    date: Optional[dt.date]
    note: str


def read_scores(path: str) -> dict[str, list[NpiScore]]:
    """NPIシートから NPI-Apathy score を読み取る。両ファイルで列名が異なる。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["NPI"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [s(c) for c in rows[0]]

    def find(*pref) -> Optional[int]:
        for p in pref:
            for i, h in enumerate(hdr):
                if h.startswith(p):
                    return i
        return None

    i_tp = find("時点")
    i_pres = find("アパシー・無関心の有無", "無関心・アパシー有無")
    i_f = find("アパシー頻度")
    i_s = find("アパシー重症度")
    i_sc = find("NPI-Apathy score")
    i_ir = find("易怒性の有無", "易怒性有無")
    i_dt = find("評価日（年月日確定）", "評価日")
    i_raw = find("評価日_原記載", "評価日（原票記載）")
    i_note = find("確認事項")

    out: dict[str, list[NpiScore]] = {}
    for r in rows[1:]:
        pid = s(r[0])
        if not pid:
            continue
        note = s(r[i_note]) if i_note is not None else ""
        d, _ = parse_date(r[i_dt]) if i_dt is not None else (None, "")
        if d is None and i_raw is not None:
            d, _ = parse_date(r[i_raw])
        m = re.search(r"原資料：(\d+)\s*か月", note)
        out.setdefault(pid, []).append(NpiScore(
            label=s(r[i_tp]), orig_label=(m.group(1) + "か月" if m else s(r[i_tp])),
            score=to_float(r[i_sc]) if i_sc is not None else None,
            presence=s(r[i_pres]) if i_pres is not None else "",
            freq=to_float(r[i_f]) if i_f is not None else None,
            sev=to_float(r[i_s]) if i_s is not None else None,
            irrit=s(r[i_ir]) if i_ir is not None else "",
            date=d, note=note))
    return out


BASELINE_LABELS = {"0か月", "初回"}
NO_SOURCE = {"資料未提供", "原票なし", ""}


@dataclass
class Case:
    su: Subject
    bl: Optional[NpiScore] = None
    fu: Optional[NpiScore] = None
    included: bool = False
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def pid(self):
        return self.su.pid

    @property
    def d_score(self) -> Optional[float]:
        if self.bl is None or self.fu is None:
            return None
        if self.bl.score is None or self.fu.score is None:
            return None
        return self.fu.score - self.bl.score

    @property
    def improved(self) -> Optional[bool]:
        d = self.d_score
        return None if d is None else d <= -1


def build_cases() -> list[Case]:
    subs = {x.pid: x for x in build_subjects()}
    cases: list[Case] = []
    for drug, path in FILES.items():
        sc = read_scores(path)
        for pid, rows in sc.items():
            su = subs.get(pid)
            if su is None:
                continue
            if su.drug != drug:
                continue
            c = Case(su)
            usable = [p for p in rows if p.presence not in NO_SOURCE]
            mb, _ = bl_fu(su.mmse, "__total__")
            cogd = mb.date if mb else None

            def is_bl(p: NpiScore) -> bool:
                if p.label in BASELINE_LABELS:
                    return True
                return bool(p.date and cogd and abs((p.date - cogd).days) <= 120)

            blc = [p for p in usable if is_bl(p)]
            fuc = [p for p in usable if p not in blc]
            if not blc or not fuc:
                c.reason = ("NPI原票なし" if not usable
                            else "NPIのベースラインまたは追跡の一方しかない")
                cases.append(c)
                continue
            c.bl = min(blc, key=lambda p: (p.date or dt.date(9999, 1, 1)))
            c.fu = max(fuc, key=lambda p: (p.date or dt.date(1, 1, 1)))
            if c.bl.score is None or c.fu.score is None:
                c.reason = "NPI-Apathy scoreが算出できない（頻度・重症度が未記入）"
                cases.append(c)
                continue
            c.included = True
            if c.bl.presence == "判定保留":
                c.notes.append("ベースラインの有無欄は判定保留だが、"
                               "頻度・重症度が記載されておりスコアは確定している")
            if c.fu.orig_label != c.fu.label:
                c.notes.append(f"NPI追跡の時点ラベルは「{c.fu.label}」だが"
                               f"原資料は{c.fu.orig_label}")
            if "記録ルール" in c.fu.note:
                c.notes.append("追跡時のスコア0は、有無欄が「なし」であることに基づく"
                               "研究上の記録ルールによる（原資料の頻度・重症度欄は空欄）")
            cases.append(c)
    return cases


# ---------------------------------------------------------------- 転帰

def val_at(su: Subject, sheet: str, key: str, tp: str) -> Optional[float]:
    """指定時点の値。tp='last' なら最終利用可能時点。"""
    panel = {"MMSE": su.mmse, "CDR": su.cdr, "MoCA": su.moca}[sheet]
    if key == "__global__":
        cand = [v for v in su.cdr if v.globalcdr is not None]
        if tp == "last":
            cand = [v for v in cand if v.label != "0か月"]
            return cand[-1].globalcdr if cand else None
        v = next((v for v in cand if v.label == tp), None)
        return v.globalcdr if v else None
    getv = (lambda v: v.total) if key == "__total__" else (lambda v: v.items.get(key))
    cand = [v for v in panel if getv(v) is not None]
    if tp == "last":
        cand = [v for v in cand if v.label != "0か月"]
        return getv(cand[-1]) if cand else None
    v = next((v for v in cand if v.label == tp), None)
    return getv(v) if v else None


OUTCOMES = ([("ΔMMSE合計", "MMSE", "__total__", "MMSE合計", 1),
             ("ΔCDR-SB", "CDR", "__total__", "CDR-SB", 1),
             ("ΔGlobalCDR", "CDR", "__global__", "Global CDR", 2),
             ("ΔMoCA-J", "MoCA", "__total__", "MoCA-J", 1)]
            + [(f"ΔMMSE_{k}", "MMSE", k, f"MMSE {k}", 1) for k in MMSE_SUB]
            + [(f"ΔCDR_{k}", "CDR", k, f"CDR {k}", 2) for k in CDR_DOM])


def wcsv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in keys})


def main() -> None:
    cases = build_cases()
    BG = load_background()
    inc = [c for c in cases if c.included]
    R: list[str] = []
    A = R.append

    A("# NPI-Apathy score に基づくアパシー改善群の解析\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("**アパシー改善の定義: NPI-Apathy score（頻度×重症度）がベースラインから"
      "1点以上低下した症例**\n")

    # ---- 1. NPIスコアの一覧
    A("\n## 1. NPI-Apathy score の一覧\n")
    A("| 研究番号 | 薬剤 | BL時点 | BLスコア | 追跡時点（ラベル／原資料） | 追跡スコア | "
      "Δスコア | 判定 | 注記 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for c in sorted(inc, key=lambda c: (c.su.drug, int(re.sub(r"\D", "", c.pid)))):
        A(f"| {c.pid} | {c.su.drug} | {c.bl.label} | {c.bl.score:g} | "
          f"{c.fu.label}／{c.fu.orig_label} | {c.fu.score:g} | {c.d_score:+g} | "
          f"{'**改善**' if c.improved else '非改善'} | "
          f"{' / '.join(c.notes) or '－'} |")
    exc = [c for c in cases if not c.included and c.reason]
    A(f"\n除外: {len(exc)}例 — "
      + "、".join(f"{r}: {sum(1 for c in exc if c.reason == r)}例"
                for r in sorted({c.reason for c in exc})))
    nos = [c for c in exc if c.reason.startswith("NPI-Apathy score")]
    if nos:
        A(f"  - スコア算出不能で除外: {', '.join(c.pid for c in nos)}")

    imp_all = [c for c in inc if c.improved]
    A(f"\n**アパシー改善群: {len(imp_all)}例**"
      f"（{', '.join(c.pid for c in imp_all)}）")

    # ---- 2. 評価時点の監査
    A("\n\n## 2. 【重要】認知機能の評価時点の監査\n")
    A("抄録に「18か月後」と記載してよいかを検証する。\n")
    A("### 2-1. NPI評価例における MMSE・CDR の時点別データ有無\n")
    A("| 研究番号 | 0か月 | 6か月 | 12か月 | 18か月 | 24か月 | 最終利用可能時点 |")
    A("|---|---|---|---|---|---|---|")
    avail = {t: 0 for t in ["0か月"] + TPS}
    for c in sorted(inc, key=lambda c: (c.su.drug, int(re.sub(r"\D", "", c.pid)))):
        cells = []
        for t in ["0か月"] + TPS:
            m = val_at(c.su, "MMSE", "__total__", t)
            cd = val_at(c.su, "CDR", "__total__", t)
            both = m is not None and cd is not None
            if both:
                avail[t] += 1
            cells.append("○" if both else ("△" if (m is not None or cd is not None)
                                           else "×"))
        mb, mf = bl_fu(c.su.mmse, "__total__")
        A(f"| {c.pid} | " + " | ".join(cells) + " | "
          + (mf.label if mf else "－") + " |")
    A("\n（○ = MMSEとCDRの両方あり、△ = 一方のみ、× = なし）\n")
    cog = [c for c in inc if any(val_at(c.su, "MMSE", "__total__", t) is not None
                                 and val_at(c.su, "CDR", "__total__", t) is not None
                                 for t in TPS)]
    A(f"NPIスコアが対で評価できた{len(inc)}例のうち、認知機能の追跡値が1時点以上あるのは"
      f"**{len(cog)}例**（残り{len(inc)-len(cog)}例はベースラインのみ）。\n")
    A("| 時点 | MMSE・CDRが両方そろう症例数 |")
    A("|---|---|")
    for t in ["0か月"] + TPS:
        A(f"| {t} | {avail[t]}/{len(cog)}例 |")

    A("\n### 2-2. 判定\n")
    cog = [c for c in inc if any(val_at(c.su, "MMSE", "__total__", t) is not None
                                 and val_at(c.su, "CDR", "__total__", t) is not None
                                 for t in TPS)]
    n6, n18 = avail["6か月"], avail["18か月"]
    A(f"- **6か月時点は{n6}/{len(cog)}例で全例そろう。**")
    A(f"- **18か月時点がそろうのは{n18}/{len(cog)}例にとどまる。**")
    imp18 = [c for c in imp_all
             if val_at(c.su, "MMSE", "__total__", "18か月") is not None
             and val_at(c.su, "CDR", "__total__", "18か月") is not None]
    A(f"- アパシー改善群{len(imp_all)}例のうち、18か月の認知機能データがあるのは"
      f"**{len(imp18)}例**（{', '.join(c.pid for c in imp18) or 'なし'}）。")
    A(f"\n→ **これまでの抄録の「追跡時」は18か月後ではない。**")
    A("最終利用可能時点を用いており、症例により6か月・12か月・18か月・24か月と異なる。")
    A("18か月に固定すると解析対象が大きく減り、改善群も欠ける。")
    A("\n### 2-3. NPIの時点ラベル自体も原資料と一致しない\n")
    A("| 研究番号 | NPIシートのラベル | 原資料の時点 |")
    A("|---|---|---|")
    mismatch = 0
    for c in sorted(inc, key=lambda c: (c.su.drug, int(re.sub(r"\D", "", c.pid)))):
        if c.fu.label != c.fu.orig_label:
            mismatch += 1
        A(f"| {c.pid} | {c.fu.label} | {c.fu.orig_label} |")
    A(f"\nラベルと原資料が一致しない症例: {mismatch}/{len(inc)}例。")
    A("NPIの「18か月」は統一ラベルであり、実際の評価時期は12〜30か月に分布する。")

    A("\n### 2-4. NPIの評価間隔と、認知機能の評価時点のずれ\n")
    ivs = [(c, (c.fu.date - c.bl.date).days / 30.4375)
           for c in inc if c.bl.date and c.fu.date]
    if ivs:
        vv = [v for _, v in ivs]
        A(f"NPIのベースラインから追跡評価までの間隔（評価日が判明した{len(vv)}例）: "
          f"{ms(vv)}か月［{min(vv):.1f}, {max(vv):.1f}］")
        A("\n| 研究番号 | NPI間隔 | 認知機能を6か月時点で比較した場合のずれ |")
        A("|---|---|---|")
        for c, v in sorted(ivs, key=lambda t: t[0].pid):
            if val_at(c.su, "MMSE", "__total__", "6か月") is None:
                continue
            A(f"| {c.pid} | {v:.1f}か月 | NPIの方が{v-6:.1f}か月後 |")
        A("\n**NPIの変化は12〜30か月かけて観察されたものであり、"
          "認知機能を6か月時点で比較すると両者の観察期間が一致しない。**")
        A("この点は方法または限界に明記する必要がある。")

    # ---- 3. 時点別の解析
    def analyse(tp: str, label: str) -> tuple[list[dict], list[dict], list[Case], list[Case]]:
        pool = [c for c in inc
                if val_at(c.su, "MMSE", "__total__", tp) is not None
                and val_at(c.su, "CDR", "__total__", tp) is not None]
        g1 = [c for c in pool if c.improved]
        g0 = [c for c in pool if not c.improved]
        rows, rates = [], []
        if not g1 or not g0:
            return rows, rates, g1, g0

        def add(sec, name, fn, nd):
            a = [fn(c) for c in g1]
            b = [fn(c) for c in g0]
            a = [v for v in a if v is not None]
            b = [v for v in b if v is not None]
            if not a and not b:
                return
            rows.append({"時点": label, "区分": sec, "項目": name,
                         "非改善群": ms(b, nd), "非改善群n": len(b),
                         "改善群": ms(a, nd), "改善群n": len(a),
                         "改善群の個別値": ", ".join(f"{v:g}" for v in a),
                         "p": mw(a, b)})

        add("患者背景", "年齢（歳）", lambda c: BG.get(c.pid, {}).get("年齢"), 1)
        add("NPI", "NPI-Apathy score 初回（点）", lambda c: c.bl.score, 2)
        add("NPI", f"NPI-Apathy score 追跡時（点）", lambda c: c.fu.score, 2)
        add("NPI", "NPI-Apathy score 変化量（点）", lambda c: c.d_score, 2)
        for key, sheet, k, nm, nd in OUTCOMES:
            add("初回", f"初回 {nm}",
                (lambda sh, kk: (lambda c: val_at(c.su, sh, kk, "0か月")))(sheet, k), nd)
        for key, sheet, k, nm, nd in OUTCOMES:
            add(label, f"{label} {nm}",
                (lambda sh, kk: (lambda c: val_at(c.su, sh, kk, tp)))(sheet, k), nd)
        for key, sheet, k, nm, nd in OUTCOMES:
            def dv(c, sh=sheet, kk=k):
                a0 = val_at(c.su, sh, kk, "0か月")
                a1 = val_at(c.su, sh, kk, tp)
                return None if a0 is None or a1 is None else a1 - a0
            add("変化量", f"Δ{nm}", dv, nd)

        def rate(name, fn):
            ca = sum(1 for c in g1 if fn(c))
            cb = sum(1 for c in g0 if fn(c))
            _, p = fisher_exact([[ca, len(g1) - ca], [cb, len(g0) - cb]])
            rates.append({"時点": label, "項目": name,
                          "非改善群": f"{cb}/{len(g0)}",
                          "非改善群%": round(cb / len(g0) * 100, 1),
                          "改善群": f"{ca}/{len(g1)}",
                          "改善群%": round(ca / len(g1) * 100, 1), "p": p})

        rate("女性", lambda c: BG.get(c.pid, {}).get("性別") == "女性")
        rate("初回のNPI-Apathy score ≧1点", lambda c: (c.bl.score or 0) >= 1)
        rate("追跡時に易怒性あり", lambda c: c.fu.irrit == "あり")
        rate("易怒性が新規出現", lambda c: c.bl.irrit == "なし" and c.fu.irrit == "あり")

        def dfun(sh, kk):
            def f(c):
                a0 = val_at(c.su, sh, kk, "0か月")
                a1 = val_at(c.su, sh, kk, tp)
                return None if a0 is None or a1 is None else a1 - a0
            return f
        rate("MMSE時間見当識が改善（Δ≧+1）",
             lambda c: (dfun("MMSE", "時間見当識")(c) or 0) >= 1)
        rate("MMSE時間見当識が低下（Δ≦−1）",
             lambda c: (dfun("MMSE", "時間見当識")(c) or 0) <= -1)
        rate("MMSE合計が改善（Δ≧+1）", lambda c: (dfun("MMSE", "__total__")(c) or 0) >= 1)
        rate("MMSE合計が低下（Δ≦−1）", lambda c: (dfun("MMSE", "__total__")(c) or 0) <= -1)
        rate("CDR-SBが悪化（Δ≧+0.5）", lambda c: (dfun("CDR", "__total__")(c) or 0) >= 0.5)
        return rows, rates, g1, g0

    all_rows, all_rates = [], []
    A("\n\n## 3. 時点別の群間比較\n")
    A("平均±標準偏差、Mann-Whitney U 検定。太字は p<0.05。\n")
    for tp, label in [("6か月", "6か月"), ("12か月", "12か月"), ("18か月", "18か月"),
                      ("last", "最終利用可能時点")]:
        rows, rates, g1, g0 = analyse(tp, label)
        all_rows += rows
        all_rates += rates
        A(f"\n### {label}（改善群 {len(g1)}例 / 非改善群 {len(g0)}例）\n")
        if not rows:
            A("比較できる症例がそろわない。")
            continue
        A(f"改善群: {', '.join(c.pid for c in g1)} ／ "
          f"非改善群: {', '.join(c.pid for c in g0)}\n")
        A("| 区分 | 項目 | 非改善群 | 改善群 | p |")
        A("|---|---|---|---|---|")
        for r in rows:
            if r["区分"] not in ("患者背景", "NPI") and not any(
                    r["項目"].endswith(x) for x in
                    ("MMSE合計", "CDR-SB", "Global CDR", "MoCA-J",
                     "MMSE 時間見当識")):
                continue
            p = r["p"]
            ptxt = ("－" if p is None else
                    (f"**{p:.3f}**" if p < 0.05 else f"{p:.3f}"))
            A(f"| {r['区分']} | {r['項目']} | {r['非改善群']}"
              f" | {r['改善群']} | {ptxt} |")
        A("\n**比率（Fisher の正確確率検定）**\n")
        A("| 項目 | 非改善群 | 改善群 | p |")
        A("|---|---|---|---|")
        for r in rates:
            ptxt = f"**{r['p']:.3f}**" if r["p"] < 0.05 else f"{r['p']:.3f}"
            A(f"| {r['項目']} | {r['非改善群']}例（{r['非改善群%']:.0f}％） | "
              f"{r['改善群']}例（{r['改善群%']:.0f}％） | {ptxt} |")

    wcsv(os.path.join(OUT, "as_by_timepoint.csv"), all_rows)
    wcsv(os.path.join(OUT, "as_rates.csv"), all_rates)

    # ---- 4. 改善群の個別データ
    A("\n\n## 4. アパシー改善群の個別データ（全時点）\n")
    for c in imp_all:
        A(f"\n**{c.pid}**（{c.su.drug}、"
          f"{BG.get(c.pid, {}).get('年齢', '－')}歳、"
          f"{BG.get(c.pid, {}).get('性別', '－')}、"
          f"投与開始 {BG.get(c.pid, {}).get('投与開始日', '－')}）\n")
        A(f"- NPI-Apathy score: {c.bl.score:g}点（{c.bl.label}、{c.bl.date}）→ "
          f"{c.fu.score:g}点（{c.fu.label}／原資料{c.fu.orig_label}、{c.fu.date}）")
        A(f"- 易怒性: {c.bl.irrit} → {c.fu.irrit}")
        A("\n| 指標 | 0か月 | 6か月 | 12か月 | 18か月 | 24か月 |")
        A("|---|---|---|---|---|---|")
        for key, sheet, k, nm, nd in OUTCOMES[:5]:
            vals = [val_at(c.su, sheet, k, t) for t in ["0か月"] + TPS]
            A(f"| {nm} | " + " | ".join(f"{v:g}" if v is not None else "－"
                                        for v in vals) + " |")

    text = "\n".join(R)
    with io.open(os.path.join(OUT, "apathy_score_report.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
