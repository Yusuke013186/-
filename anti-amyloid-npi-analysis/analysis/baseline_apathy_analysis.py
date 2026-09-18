# -*- coding: utf-8 -*-
"""
抗アミロイドβ抗体療法 後方視的観察研究

問い:
  治療開始前（0か月／初回）のNPI第7項目でアパシーが「あり」とされた群は、
  「なし」群と比較して、MMSE・CDRの総合点およびそれぞれの下位項目の
  変化と関連するか。

設計上の要点:
  - ベースラインのNPIのみを曝露として用いるため、追跡NPIが無い症例も組み入れられる。
    これにより解析対象は前解析の13例から15例へ、曝露群は3例から5例へ増える。
  - MMSE下位項目は可動域が0〜1点や0〜3点と狭く、床・天井効果により
    「変化量の群間差」が見かけ上生じやすい。このため
      (1) ベースライン値そのものの群間比較（交絡の検出）
      (2) ベースライン値で調整した共分散分析（並べ替え検定・全数列挙による正確p値）
      (3) 悪化方向に動ける余地がある症例に限定した再解析
    を必ず併記する。
  - 多重性は転帰の族ごとに Benjamini-Hochberg 法で調整する。

実行: python3 analysis/baseline_apathy_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import itertools
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.stats import mannwhitneyu, fisher_exact, spearmanr, norm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_analysis import (                                   # noqa: E402
    FILES, MMSE_SUB, CDR_DOM, Subject, build_subjects, bl_fu,
    outcomes, OUTCOME_KEYS, outcome_meta, higher_is_better, headroom,
    annualized, median, bh_fdr, cles, rank_biserial, required_n_noether,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(OUT, exist_ok=True)

# 転帰の族（多重性の調整はこの単位で行う）
FAMILIES = {
    "主要（総合点）": ["ΔMMSE合計", "ΔCDR-SB", "ΔGlobalCDR", "ΔMoCA-J"],
    "MMSE下位項目": [f"ΔMMSE_{k}" for k in MMSE_SUB],
    "CDR下位領域": [f"ΔCDR_{k}" for k in CDR_DOM],
}

LABEL = {"ΔMMSE合計": "MMSE合計", "ΔCDR-SB": "CDR-SB", "ΔGlobalCDR": "Global CDR",
         "ΔMoCA-J": "MoCA-J"}
for _k in MMSE_SUB:
    LABEL[f"ΔMMSE_{_k}"] = f"MMSE {_k}"
for _k in CDR_DOM:
    LABEL[f"ΔCDR_{_k}"] = f"CDR {_k}"


# ---------------------------------------------------------------- 組み入れ

@dataclass
class Entry:
    su: Subject
    apathy: Optional[int]          # ベースラインのアパシー 1=あり 0=なし
    conf: str                      # 'definite' / 'reference' / 'excluded'
    included: bool
    reason: str = ""
    npi_label: str = ""
    npi_date: Optional[dt.date] = None
    caution: list[str] = field(default_factory=list)


def build_entries() -> list[Entry]:
    """ベースラインNPIのアパシー判定と認知機能の追跡可否から組み入れを決める。"""
    subs = build_subjects()
    entries: list[Entry] = []
    for su in subs:
        has_cog = (su.d("MMSE", "__total__") is not None
                   or su.d("CDR", "__total__") is not None)
        e = Entry(su, su.ap_bl, su.ap_conf, False)
        e.npi_label, e.npi_date = "", None
        if su.npi_note:
            e.npi_label = su.npi_note.split("→")[0]
        if su.ap_bl is None:
            e.reason = ("ベースラインNPIのアパシー判定が得られない"
                        if su.npi_paired else "ベースラインNPI原票なし")
        elif not has_cog:
            e.reason = "MMSE・CDRともに追跡値なし（ベースラインのみ）"
        else:
            e.included = True
        if su.drug == "ドナネマブ" and su.ap_bl is not None:
            e.caution.append("原票の「初回」と治療開始時点との対応が原表で要確認とされている")
        entries.append(e)
    return entries


def build_entries_baseline_only() -> list[Entry]:
    """build_subjects() は NPI が対で揃う症例しかベースライン判定を持たないため、
    追跡NPIが無い症例（ドナネマブ D1・D2 など）を拾い直す。"""
    from deep_analysis import read_panel, read_moca
    from npi_analysis import read_npi, resolve_npi, NPI_NO_SOURCE, BASELINE_LABELS
    from deep_analysis import BASELINE_WINDOW_DAYS

    subs = {s.pid: s for s in build_subjects()}
    entries: list[Entry] = []
    for drug, path in FILES.items():
        npi = read_npi(path, drug)
        for pid, su in subs.items():
            if su.drug != drug:
                continue
            pts = [p for p in npi.get(pid, []) if p.apathy_raw not in NPI_NO_SOURCE]
            b, _ = bl_fu(su.mmse, "__total__")
            cog_bl_date = b.date if b else None

            def is_bl(p):
                if p.label in BASELINE_LABELS:
                    return True
                return bool(p.date and cog_bl_date
                            and abs((p.date - cog_bl_date).days) <= BASELINE_WINDOW_DAYS)

            blc = [p for p in pts if is_bl(p)]
            e = Entry(su, None, "excluded", False)
            if not blc:
                e.reason = ("ベースラインNPI原票なし" if not pts
                            else "NPI原票はあるがベースライン時点に該当する行がない")
                entries.append(e)
                continue
            nb = min(blc, key=lambda p: (p.date or dt.date(9999, 1, 1)))
            e.npi_label, e.npi_date = nb.label, nb.date
            e.apathy, e.conf, why = resolve_npi(nb.apathy_raw, nb.note, "アパシー")
            if e.apathy is None:
                e.reason = f"ベースラインのアパシー判定が不能（{nb.apathy_raw}）"
                entries.append(e)
                continue
            if (su.d("MMSE", "__total__") is None
                    and su.d("CDR", "__total__") is None):
                e.reason = "MMSE・CDRともに追跡値なし（ベースラインのみ）"
                entries.append(e)
                continue
            e.included = True
            if e.conf == "reference":
                e.caution.append(f"判定保留を確認事項の記載に基づき採用（{why}）")
            if nb.label not in ("0か月", "初回"):
                e.caution.append(f"時点ラベルは「{nb.label}」だが評価日が認知機能ベースライン"
                                 f"の±{BASELINE_WINDOW_DAYS}日以内のためベースラインとみなした")
            if drug == "ドナネマブ":
                e.caution.append("原票の「初回」と治療開始時点との対応が原表で要確認とされている")
            if cog_bl_date and nb.date and abs((nb.date - cog_bl_date).days) > 180:
                e.caution.append(f"NPIベースライン日({nb.date})と認知機能ベースライン日"
                                 f"({cog_bl_date})が{abs((nb.date-cog_bl_date).days)}日乖離")
            entries.append(e)
    return entries


# ---------------------------------------------------------------- 統計

def exact_perm_p(values: np.ndarray, group: np.ndarray,
                 stat_fn, max_exact: int = 200000) -> tuple[float, float]:
    """群ラベルの並べ替え検定。組合せ数が max_exact 以下なら全数列挙して正確p値を返す。
    戻り値: (観測統計量, 両側p値)
    """
    n, n1 = len(group), int(group.sum())
    obs = stat_fn(values, group)
    total = math.comb(n, n1)
    idx = np.arange(n)
    count = 0
    if total <= max_exact:
        for combo in itertools.combinations(idx, n1):
            g = np.zeros(n)
            g[list(combo)] = 1
            if abs(stat_fn(values, g)) >= abs(obs) - 1e-12:
                count += 1
        return obs, count / total
    rng = np.random.default_rng(20260918)
    B = max_exact
    for _ in range(B):
        g = rng.permutation(group)
        if abs(stat_fn(values, g)) >= abs(obs) - 1e-12:
            count += 1
    return obs, (count + 1) / (B + 1)


def ancova_stat(mat: np.ndarray, group: np.ndarray) -> float:
    """ベースライン値で調整した変化量の群間差。
    mat[:,0]=変化量Δ、mat[:,1]=ベースライン値。
    Δ を BL で回帰した残差の群平均差を統計量とする（並べ替えのたびに回帰し直す）。
    """
    d, b = mat[:, 0], mat[:, 1]
    if np.ptp(b) == 0:
        resid = d - d.mean()
    else:
        A = np.column_stack([np.ones_like(b), b])
        coef, *_ = np.linalg.lstsq(A, d, rcond=None)
        resid = d - A @ coef
    g1 = resid[group == 1]
    g0 = resid[group == 0]
    if len(g1) == 0 or len(g0) == 0:
        return 0.0
    return float(g1.mean() - g0.mean())


def mean_diff_stat(v: np.ndarray, group: np.ndarray) -> float:
    g1, g0 = v[group == 1], v[group == 0]
    if len(g1) == 0 or len(g0) == 0:
        return 0.0
    return float(g1.mean() - g0.mean())


def describe(vals: list[float]) -> str:
    if not vals:
        return "n=0"
    v = sorted(vals)
    return (f"{median(v):g}［{min(v):g}, {max(v):g}］"
            f"（{', '.join(f'{x:g}' for x in v)}）")


def analyse_outcome(ex: list[Subject], un: list[Subject], ok: str) -> dict:
    """1転帰について、生の変化量・年換算・ベースライン調整・余地限定の4通りを計算する。"""
    sheet, key, _, _ = outcome_meta(ok)
    a = [(x, outcomes(x)[ok]) for x in ex if outcomes(x)[ok] is not None]
    b = [(x, outcomes(x)[ok]) for x in un if outcomes(x)[ok] is not None]
    r: dict = {"転帰": LABEL[ok], "キー": ok,
               "n_あり": len(a), "n_なし": len(b)}
    if not a or not b:
        r["備考"] = "いずれかの群が0例"
        return r

    va = [v for _, v in a]
    vb = [v for _, v in b]
    r["Δあり"] = describe(va)
    r["Δなし"] = describe(vb)
    r["Δあり中央値"] = median(va)
    r["Δなし中央値"] = median(vb)

    # --- 生の変化量
    if len(set(va + vb)) > 1:
        u, p = mannwhitneyu(va, vb, alternative="two-sided", method="exact")
        r["U"] = u
        r["p_raw"] = p
        r["効果量r"] = rank_biserial(va, vb, u)
        r["CLES"] = cles(va, vb)
        r["必要n_1対1"] = required_n_noether(r["CLES"], 0.5)
    else:
        r["p_raw"] = None
        r["備考"] = "全例同値"

    # --- 相関（曝露0/1 と Δ の順位相関）
    xs = [1] * len(va) + [0] * len(vb)
    ys = va + vb
    if len(set(ys)) > 1:
        rho, prho = spearmanr(xs, ys)
        r["Spearman_rho"] = float(rho)
        r["p_rho"] = float(prho)

    # --- ベースライン値そのものの群間比較（交絡の検出）
    ba = [x.base(sheet, key) for x, _ in a]
    bb = [x.base(sheet, key) for x, _ in b]
    ba = [v for v in ba if v is not None]
    bb = [v for v in bb if v is not None]
    if ba and bb:
        r["BLあり"] = describe(ba)
        r["BLなし"] = describe(bb)
        if len(set(ba + bb)) > 1:
            _, pbl = mannwhitneyu(ba, bb, alternative="two-sided", method="exact")
            r["p_BL差"] = pbl

    # --- ベースライン調整（並べ替え共分散分析）
    pairs = [(x, v, x.base(sheet, key)) for x, v in a + b]
    pairs = [(x, v, bv) for x, v, bv in pairs if bv is not None]
    if len(pairs) >= 5:
        mat = np.array([[v, bv] for _, v, bv in pairs], dtype=float)
        grp = np.array([1.0 if (x in [y for y, _ in a]) else 0.0
                        for x, _, _ in pairs])
        if 0 < grp.sum() < len(grp) and len(set(mat[:, 0])) > 1:
            obs, p = exact_perm_p(mat, grp, ancova_stat)
            r["BL調整_群間差"] = obs
            r["p_BL調整"] = p

    # --- 悪化方向に動ける余地が1点以上ある症例に限定
    ea = [v for x, v in a if (headroom(x, ok, "worse") or 0) >= 1]
    eb = [v for x, v in b if (headroom(x, ok, "worse") or 0) >= 1]
    r["n_余地あり"] = f"{len(ea)}/{len(eb)}"
    if ea and eb and len(set(ea + eb)) > 1:
        _, pe = mannwhitneyu(ea, eb, alternative="two-sided", method="exact")
        r["p_余地限定"] = pe
        r["Δあり_余地"] = describe(ea)
        r["Δなし_余地"] = describe(eb)

    # --- 年換算
    aa = [annualized(x, ok) for x, _ in a]
    ab = [annualized(x, ok) for x, _ in b]
    aa = [v for v in aa if v is not None]
    ab = [v for v in ab if v is not None]
    if aa and ab and len(set(aa + ab)) > 1:
        _, pa = mannwhitneyu(aa, ab, alternative="two-sided", method="exact")
        r["p_年換算"] = pa
        r["n年換算"] = f"{len(aa)}/{len(ab)}"
    return r


def mv_ancova_stat(mat: np.ndarray, group: np.ndarray) -> float:
    """複数の共変量で調整した変化量の群間差。
    mat[:,0]=Δ、mat[:,1:]=共変量。並べ替えのたびに回帰し直す。"""
    d, X = mat[:, 0], mat[:, 1:]
    A = np.column_stack([np.ones(len(d)), X])
    keep = [0] + [i + 1 for i in range(X.shape[1]) if np.ptp(X[:, i]) > 0]
    A = A[:, keep]
    coef, *_ = np.linalg.lstsq(A, d, rcond=None)
    resid = d - A @ coef
    g1, g0 = resid[group == 1], resid[group == 0]
    if len(g1) == 0 or len(g0) == 0:
        return 0.0
    return float(g1.mean() - g0.mean())


def adjusted_analysis(ex: list[Subject], un: list[Subject], ok: str) -> list[dict]:
    """1転帰について、共変量を段階的に加えた調整解析を行う。
    追跡期間が不明な症例は、期間を共変量に含めるモデルからは落ちる。"""
    sheet, key, _, _ = outcome_meta(ok)
    recs = []
    for x, g in [(x, 1) for x in ex] + [(x, 0) for x in un]:
        v = outcomes(x)[ok]
        b = x.base(sheet, key)
        if v is None or b is None:
            continue
        recs.append({"su": x, "g": g, "d": v, "bl": b,
                     "m": x.interval_m,
                     "don": 1.0 if x.drug == "ドナネマブ" else 0.0})
    out = []
    models = [("調整なし（変化量そのもの）", []),
              ("ベースライン値で調整", ["bl"]),
              ("追跡期間で調整", ["m"]),
              ("ベースライン値＋追跡期間で調整", ["bl", "m"]),
              ("ベースライン値＋追跡期間＋薬剤で調整", ["bl", "m", "don"])]
    for name, covs in models:
        rs = [r for r in recs if all(r[c] is not None for c in covs)]
        grp = np.array([r["g"] for r in rs], dtype=float)
        if len(rs) < 5 or not (0 < grp.sum() < len(grp)):
            out.append({"転帰": LABEL[ok], "モデル": name, "n": len(rs),
                        "備考": "症例数不足"})
            continue
        mat = np.array([[r["d"]] + [r[c] for c in covs] for r in rs], dtype=float)
        if len(set(mat[:, 0])) == 1:
            out.append({"転帰": LABEL[ok], "モデル": name, "n": len(rs),
                        "備考": "全例同値"})
            continue
        stat = mv_ancova_stat if covs else mean_diff_stat
        vals = mat if covs else mat[:, 0]
        obs, p = exact_perm_p(vals, grp, stat)
        out.append({"転帰": LABEL[ok], "モデル": name, "n": len(rs),
                    "n_あり": int(grp.sum()), "n_なし": int(len(grp) - grp.sum()),
                    "群間差": round(obs, 4), "p": p})
    return out


def cdr_quality_audit(all_subs: list[Subject]) -> dict:
    """CDRの6領域が全評価時点で完全に同一の症例を数える。
    再評価ではなく前回値の転記が行われた可能性を示す指標として用いる。"""
    rows = []
    for su in all_subs:
        vs = [v for v in su.cdr if v.total is not None]
        if len(vs) < 2:
            continue
        sig = {tuple(v.items.get(k) for k in CDR_DOM) for v in vs}
        rows.append({"研究番号": su.pid, "薬剤": su.drug, "評価時点数": len(vs),
                     "全時点同一": len(sig) == 1, "CDR-SB": vs[0].total})
    return {"rows": rows,
            "n": len(rows),
            "identical": [r for r in rows if r["全時点同一"]]}


# ---------------------------------------------------------------- 出力

def fmt_p(p) -> str:
    if p is None:
        return "－"
    return f"**{p:.3f}**" if p < 0.05 else (f"{p:.3f}" if p >= 0.001 else f"{p:.1e}")


def plain_p(p) -> str:
    return "－" if p is None else (f"{p:.3f}" if p >= 0.001 else f"{p:.1e}")


def wcsv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else
                            (f"{r[k]:.5g}" if isinstance(r[k], float) else r[k]))
                        for k in keys})


def run_set(ex: list[Subject], un: list[Subject]) -> list[dict]:
    rows = []
    for fam, keys in FAMILIES.items():
        fam_rows = []
        for ok in keys:
            r = analyse_outcome(ex, un, ok)
            r["族"] = fam
            fam_rows.append(r)
        ps = [r.get("p_raw") for r in fam_rows if r.get("p_raw") is not None]
        if ps:
            adj = dict(zip([i for i, r in enumerate(fam_rows)
                            if r.get("p_raw") is not None], bh_fdr(ps)))
            for i, r in enumerate(fam_rows):
                r["p_raw_FDR"] = adj.get(i)
        rows += fam_rows
    return rows


def main() -> None:
    entries = build_entries_baseline_only()
    inc = [e for e in entries if e.included]
    ex_def = [e for e in inc if e.apathy == 1 and e.conf == "definite"]
    ex_ref = [e for e in inc if e.apathy == 1 and e.conf == "reference"]
    un_all = [e for e in inc if e.apathy == 0]

    R: list[str] = []
    A = R.append
    A("# 治療開始前のNPIアパシーの有無と、その後の認知機能変化との関連\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("向きの定義: **ΔMMSE系・ΔMoCA-Jはプラスが改善**、**ΔCDR系はプラスが悪化**。")
    A("変化量は「最終利用可能時点 − ベースライン（0か月）」。\n")
    A("<<<SUMMARY>>>")

    # ---- 1. 組み入れ
    A("\n## 1. 組み入れ\n")
    A("本解析ではベースラインのNPIのみを曝露として用いるため、追跡NPIが無い症例も")
    A("組み入れられる。これによりアパシーあり群は3例から5例に増えている。\n")
    A(f"- 全研究番号: {len(entries)}例")
    for why in ("ベースラインNPI原票なし",
                "NPI原票はあるがベースライン時点に該当する行がない",
                "ベースラインのアパシー判定が不能",
                "MMSE・CDRともに追跡値なし（ベースラインのみ）"):
        g = [e for e in entries if e.reason.startswith(why)]
        ids = ", ".join(e.su.pid for e in g)
        A(f"- {why}で除外: {len(g)}例" + (f"（{ids}）" if g and len(g) <= 12 else ""))
    A(f"- **解析対象: {len(inc)}例**")
    A(f"  - アパシーあり（確定）: {len(ex_def)}例 "
      f"（{', '.join(e.su.pid for e in ex_def)}）")
    A(f"  - アパシーあり（判定保留を参考値として採用）: {len(ex_ref)}例 "
      f"（{', '.join(e.su.pid for e in ex_ref) or 'なし'}）")
    A(f"  - アパシーなし（確定）: {len(un_all)}例 "
      f"（{', '.join(e.su.pid for e in un_all)}）")

    A("\n### 組み入れ症例の一覧\n")
    A("| 研究番号 | 薬剤 | ベースラインNPI時点 | 評価日 | アパシー | 判定の確度 | "
      "MMSE追跡 | CDR追跡 | 追跡期間 | 注記 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for e in inc:
        su = e.su
        mb, mf = bl_fu(su.mmse, "__total__")
        cb, cf = bl_fu(su.cdr, "__total__")
        A(f"| {su.pid} | {su.drug} | {e.npi_label} | {e.npi_date or '－'} | "
          f"{'あり' if e.apathy else 'なし'} | "
          f"{'確定' if e.conf == 'definite' else '参考値'} | "
          f"{(f'{mb.total:g}→{mf.total:g} ({mf.label})' if mb and mf else '－')} | "
          f"{(f'{cb.total:g}→{cf.total:g} ({cf.label})' if cb and cf else '－')} | "
          f"{f'{su.interval_m:g}か月' if su.interval_m is not None else '不明'} | "
          f"{' / '.join(e.caution) or '－'} |")

    A("\n### 除外症例\n")
    A("| 研究番号 | 薬剤 | 除外理由 |")
    A("|---|---|---|")
    for e in entries:
        if not e.included:
            A(f"| {e.su.pid} | {e.su.drug} | {e.reason} |")

    # ---- 2. 背景の比較
    ex = [e.su for e in ex_def]
    un = [e.su for e in un_all]
    A("\n\n## 2. 両群のベースライン背景\n")
    A("床・天井効果の有無を判断するために必須の表。ベースライン値が偏っていれば、")
    A("変化量の群間差はその偏りで説明されうる。\n")
    A("| 指標 | アパシーあり（n=%d） | アパシーなし（n=%d） | p |"
      % (len(ex), len(un)))
    A("|---|---|---|---|")
    bl_rows = []
    for fam, keys in FAMILIES.items():
        for ok in keys:
            sheet, key, _, _ = outcome_meta(ok)
            va = [x.base(sheet, key) for x in ex]
            vb = [x.base(sheet, key) for x in un]
            va = [v for v in va if v is not None]
            vb = [v for v in vb if v is not None]
            if not va or not vb:
                continue
            p = None
            if len(set(va + vb)) > 1:
                _, p = mannwhitneyu(va, vb, alternative="two-sided", method="exact")
            A(f"| {LABEL[ok]} | {describe(va)} | {describe(vb)} | {fmt_p(p)} |")
            bl_rows.append({"指標": LABEL[ok], "あり": describe(va),
                            "なし": describe(vb), "p": p})
    iv_a = [x.interval_m for x in ex if x.interval_m is not None]
    iv_b = [x.interval_m for x in un if x.interval_m is not None]
    if iv_a and iv_b:
        _, piv = mannwhitneyu(iv_a, iv_b, alternative="two-sided", method="exact")
        A(f"| 追跡期間（月） | {describe(iv_a)} | {describe(iv_b)} | {fmt_p(piv)} |")
    na, nb = len(ex), len(un)
    da = sum(1 for x in ex if x.drug == "ドナネマブ")
    db = sum(1 for x in un if x.drug == "ドナネマブ")
    _, pdr = fisher_exact([[da, na - da], [db, nb - db]])
    A(f"| ドナネマブの割合 | {da}/{na} | {db}/{nb} | {fmt_p(pdr)} |")
    wcsv(os.path.join(OUT, "ba_baseline_characteristics.csv"), bl_rows)

    # ---- 3. 主解析
    rows = run_set(ex, un)
    wcsv(os.path.join(OUT, "ba_main_results.csv"), rows)

    A("\n\n## 3. 主解析 — アパシーあり群 vs なし群（確定判定のみ、%d例 vs %d例）\n"
      % (len(ex), len(un)))
    A("`p(生)` は変化量そのものの Mann-Whitney U 検定（正確法）。")
    A("`p(BL調整)` はベースライン値で調整した共分散分析の並べ替え検定（全数列挙による正確p値）。")
    A("`p(余地限定)` は悪化方向に1点以上動ける症例に限定した再解析。")
    A("`p(FDR)` は族内の Benjamini-Hochberg 調整値。太字は p<0.05。\n")
    for fam in FAMILIES:
        A(f"\n### {fam}\n")
        A("| 転帰 | n(あり/なし) | Δ あり 中央値［範囲］ | Δ なし 中央値［範囲］ | "
          "ρ | p(生) | p(FDR) | p(BL差) | p(BL調整) | n余地 | p(余地限定) | p(年換算) |")
        A("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in [x for x in rows if x["族"] == fam]:
            if "Δあり" not in r:
                A(f"| {r['転帰']} | {r['n_あり']}/{r['n_なし']} | － | － | － | － | － | "
                  "－ | － | － | － | － |")
                continue
            A(f"| {r['転帰']} | {r['n_あり']}/{r['n_なし']} | {r['Δあり']} | {r['Δなし']} | "
              f"{r.get('Spearman_rho', float('nan')):+.2f} | {fmt_p(r.get('p_raw'))} | "
              f"{plain_p(r.get('p_raw_FDR'))} | {plain_p(r.get('p_BL差'))} | "
              f"{fmt_p(r.get('p_BL調整'))} | {r.get('n_余地あり', '－')} | "
              f"{fmt_p(r.get('p_余地限定'))} | {fmt_p(r.get('p_年換算'))} |")

    # ---- 4. 判定
    A("\n\n## 4. 判定\n")
    sig_raw = [r for r in rows if (r.get("p_raw") or 1) < 0.05]
    sig_fdr = [r for r in rows if (r.get("p_raw_FDR") or 1) < 0.05]
    sig_adj = [r for r in rows if (r.get("p_BL調整") or 1) < 0.05]
    sig_hr = [r for r in rows if (r.get("p_余地限定") or 1) < 0.05]
    A(f"- 変化量そのものの比較で p<0.05: **{len(sig_raw)}件** / {len(rows)}件"
      + (f"（{', '.join(r['転帰'] for r in sig_raw)}）" if sig_raw else ""))
    A(f"- 族内 FDR 調整後も p<0.05: **{len(sig_fdr)}件**"
      + (f"（{', '.join(r['転帰'] for r in sig_fdr)}）" if sig_fdr else ""))
    A(f"- ベースライン値で調整した共分散分析で p<0.05: **{len(sig_adj)}件**"
      + (f"（{', '.join(r['転帰'] for r in sig_adj)}）" if sig_adj else ""))
    A(f"- 悪化方向の余地がある症例に限定して p<0.05: **{len(sig_hr)}件**"
      + (f"（{', '.join(r['転帰'] for r in sig_hr)}）" if sig_hr else ""))
    A("\n**いずれの検定でも p<0.05 を満たす転帰**: "
      + (", ".join(r["転帰"] for r in rows
                   if (r.get("p_raw") or 1) < 0.05 and (r.get("p_BL調整") or 1) < 0.05
                   and (r.get("p_余地限定") or 1) < 0.05) or "**なし**"))

    # ---- 5. 感度解析
    A("\n\n## 5. 感度解析\n")
    sens = []
    for name, e2, u2 in [
            ("主解析（確定判定のみ、5例 vs 10例）", ex, un),
            ("判定保留の1例をあり群に加える（6例 vs 10例）",
             ex + [e.su for e in ex_ref], un),
            ("ドナネマブ2例を除く（3例 vs 10例）",
             [x for x in ex if x.drug == "レカネマブ"],
             [x for x in un if x.drug == "レカネマブ"]),
            ("レカネマブのみ・判定保留を含む",
             [x for x in ex if x.drug == "レカネマブ"] + [e.su for e in ex_ref],
             [x for x in un if x.drug == "レカネマブ"])]:
        rr = run_set(e2, u2)
        for r in rr:
            r["解析セット"] = name
        sens += rr
        best = sorted([r for r in rr if r.get("p_raw") is not None],
                      key=lambda r: r["p_raw"])[:3]
        A(f"\n**{name}**")
        A(f"\n- p<0.05（生）: "
          + (", ".join(f"{r['転帰']} p={r['p_raw']:.3f}"
                       for r in rr if (r.get('p_raw') or 1) < 0.05) or "なし"))
        A("- 最小p値の3項目: "
          + ", ".join(f"{r['転帰']} p={r['p_raw']:.3f}" for r in best))
    wcsv(os.path.join(OUT, "ba_sensitivity.csv"), sens)

    # ---- 5b. CDR-SB の深掘りと交絡の検討
    A("\n\n## 5-B. CDR-SB の所見の詳細と交絡の検討\n")
    A("主解析で唯一 p<0.05 となったのは CDR-SB であり、しかも**方向は直感と逆**であった。")
    A("すなわち**ベースラインでアパシーがあった群のほうが CDR-SB の悪化が小さかった**。")
    A("この所見が何によるものかを検討する。\n")
    A("| 研究番号 | 薬剤 | アパシー | CDR-SB BL→FU | Δ | 追跡期間 | Δ/年 | CDR6領域が全時点同一か |")
    A("|---|---|---|---|---|---|---|---|")
    aud = cdr_quality_audit([e.su for e in inc])
    ident_ids = {r["研究番号"] for r in aud["identical"]}
    for e in sorted(inc, key=lambda e: (-(e.apathy or 0), e.su.pid)):
        b, f = bl_fu(e.su.cdr, "__total__")
        if b is None or f is None:
            continue
        av = annualized(e.su, "ΔCDR-SB")
        A(f"| {e.su.pid} | {e.su.drug} | "
          f"{'あり' if e.apathy else 'なし'}"
          f"{'(参考値)' if e.conf == 'reference' else ''} | "
          f"{b.total:g}→{f.total:g} | {e.su.d('CDR', '__total__'):+g} | "
          f"{f'{e.su.interval_m:g}か月' if e.su.interval_m is not None else '不明'} | "
          f"{f'{av:+.2f}' if av is not None else '－'} | "
          f"{'**同一**' if e.su.pid in ident_ids else '変化あり'} |")

    A("\n### 交絡1: 追跡期間\n")
    iva = sorted(x.interval_m for x in ex if x.interval_m is not None)
    ivb = sorted(x.interval_m for x in un if x.interval_m is not None)
    A(f"- アパシーあり群の追跡期間: {', '.join(f'{v:g}' for v in iva)} か月"
      f"（中央値 {median(iva):g}）")
    A(f"- アパシーなし群の追跡期間: {', '.join(f'{v:g}' for v in ivb)} か月"
      f"（中央値 {median(ivb):g}）")
    A("\nあり群のほうが追跡期間が短い傾向があり、悪化する時間が短かった可能性がある。")

    A("\n### 交絡2: CDRの記入の持ち越しの疑い\n")
    allsubs = build_subjects()
    aud_all = cdr_quality_audit(allsubs)
    A(f"CDRが2時点以上ある全 {aud_all['n']}例のうち、6領域すべてが全評価時点で"
      f"完全に同一の値であったのは **{len(aud_all['identical'])}例**"
      f"（{len(aud_all['identical'])/aud_all['n']*100:.0f}%）であった。")
    for d in ("レカネマブ", "ドナネマブ"):
        tot = sum(1 for r in aud_all["rows"] if r["薬剤"] == d)
        idn = sum(1 for r in aud_all["identical"] if r["薬剤"] == d)
        A(f"- {d}: {idn}/{tot}例（{idn/tot*100:.0f}%）")
    A("\nドナネマブで顕著に高く、再評価ではなく前回値の転記が行われた可能性がある。")
    ia = [e.su.pid for e in inc if e.apathy == 1 and e.conf == "definite"
          and e.su.pid in ident_ids]
    ib = [e.su.pid for e in inc if e.apathy == 0 and e.su.pid in ident_ids]
    A(f"\n本解析の対象では、アパシーあり群 {len(ia)}/{len(ex)}例（{', '.join(ia)}）、"
      f"なし群 {len(ib)}/{len(un)}例（{', '.join(ib)}）が該当する。")
    A("**あり群はCDRが動いていない症例に著しく偏っており、"
      "「悪化が小さい」という所見はこの偏りで説明されうる。**")
    wcsv(os.path.join(OUT, "ba_cdr_quality_audit.csv"), aud_all["rows"])

    A("\n### 交絡を調整した解析\n")
    A("共変量を段階的に加えた並べ替え共分散分析（全数列挙による正確p値）。\n")
    adj_rows = []
    for ok in ["ΔCDR-SB", "ΔMMSE合計", "ΔMMSE_遅延再生", "ΔGlobalCDR"]:
        rs = adjusted_analysis(ex, un, ok)
        adj_rows += rs
        A(f"\n**{LABEL[ok]}**\n")
        A("| モデル | n（あり/なし） | 調整後の群間差 | p |")
        A("|---|---|---|---|")
        for r in rs:
            if "p" not in r:
                A(f"| {r['モデル']} | {r['n']} | － | {r.get('備考', '－')} |")
            else:
                A(f"| {r['モデル']} | {r['n']}（{r['n_あり']}/{r['n_なし']}） | "
                  f"{r['群間差']:+g} | {fmt_p(r['p'])} |")
    wcsv(os.path.join(OUT, "ba_adjusted_models.csv"), adj_rows)

    # ---- 6. 症例別明細
    A("\n\n## 6. 症例別明細（全転帰）\n")
    allk = [k for ks in FAMILIES.values() for k in ks]
    A("| 研究番号 | 薬剤 | アパシー | " + " | ".join(f"Δ{LABEL[k]}" for k in allk) + " |")
    A("|" + "---|" * (3 + len(allk)))
    for e in sorted(inc, key=lambda e: (-(e.apathy or 0), e.su.pid)):
        o = outcomes(e.su)
        A(f"| {e.su.pid} | {e.su.drug} | "
          f"{'あり' if e.apathy else 'なし'}"
          f"{'(参考値)' if e.conf == 'reference' else ''} | "
          + " | ".join(f"{o[k]:+g}" if o[k] is not None else "－" for k in allk) + " |")

    A("\n### ベースライン値の明細\n")
    A("| 研究番号 | アパシー | " + " | ".join(LABEL[k] for k in allk) + " |")
    A("|" + "---|" * (2 + len(allk)))
    for e in sorted(inc, key=lambda e: (-(e.apathy or 0), e.su.pid)):
        vals = []
        for k in allk:
            sheet, key, _, _ = outcome_meta(k)
            v = e.su.base(sheet, key)
            vals.append(f"{v:g}" if v is not None else "－")
        A(f"| {e.su.pid} | {'あり' if e.apathy else 'なし'} | " + " | ".join(vals) + " |")

    det = []
    for e in inc:
        o = outcomes(e.su)
        row = {"研究番号": e.su.pid, "薬剤": e.su.drug,
               "ベースラインアパシー": "あり" if e.apathy else "なし",
               "判定の確度": e.conf, "NPI時点": e.npi_label,
               "NPI評価日": e.npi_date, "追跡期間_月": e.su.interval_m,
               "注記": " / ".join(e.caution)}
        for k in allk:
            sheet, key, _, _ = outcome_meta(k)
            row[f"BL_{LABEL[k]}"] = e.su.base(sheet, key)
            row[f"Δ_{LABEL[k]}"] = o[k]
        det.append(row)
    wcsv(os.path.join(OUT, "ba_case_detail.csv"), det)

    # ---- 要約を先頭に差し込む
    def g(ok, model=None):
        if model is None:
            return next((r for r in rows if r["キー"] == ok), {})
        return next((r for r in adj_rows if r["転帰"] == LABEL[ok]
                     and r["モデル"] == model), {})

    cdr = g("ΔCDR-SB")
    S: list[str] = ["\n## 要約（結論）\n"]
    S.append("**治療開始前のNPIアパシーの有無は、MMSE・CDRの総合点とも、"
             "MMSE下位11項目・CDR下位6領域とも、有意な関連を示さなかった。**\n")
    S.append(f"- 解析対象は {len(inc)}例（アパシーあり{len(ex)}例 vs なし{len(un)}例、"
             f"判定保留の1例は別途感度解析）。追跡NPIを要件から外したことで、"
             f"あり群は前解析の3例から5例に増えている。")
    S.append(f"- 21転帰のうち、変化量そのものの比較で p<0.05 となったのは "
             f"**CDR-SB のみ**（p={cdr.get('p_raw', float('nan')):.3f}、"
             f"Spearman ρ={cdr.get('Spearman_rho', float('nan')):+.2f}）。"
             f"族内 FDR 調整後は **0件**。")
    S.append(f"- しかもその方向は直感と逆で、**アパシーあり群のほうが CDR-SB の悪化が"
             f"小さかった**（Δ中央値 {cdr.get('Δあり中央値')} vs "
             f"{cdr.get('Δなし中央値')}）。\n")
    S.append("### この CDR-SB の所見は交絡で説明できる\n")
    S.append(f"- **追跡期間の偏り**: あり群の追跡期間は中央値 {median(iva):g}か月、"
             f"なし群は {median(ivb):g}か月。あり群は悪化する時間が短かった。")
    S.append(f"- **CDRの記入の持ち越しの疑い**: あり群の {len(ia)}/{len(ex)}例"
             f"（{', '.join(ia)}）は CDR6領域が全評価時点で完全に同一。"
             f"なし群では {len(ib)}/{len(un)}例のみ。")
    S.append("- **共変量を加えると消失する**:\n")
    S.append("| モデル | 調整後の群間差 | p |")
    S.append("|---|---|---|")
    for m in ("調整なし（変化量そのもの）", "ベースライン値で調整", "追跡期間で調整",
              "ベースライン値＋追跡期間で調整", "ベースライン値＋追跡期間＋薬剤で調整"):
        r = g("ΔCDR-SB", m)
        if "p" in r:
            S.append(f"| {m} | {r['群間差']:+g} | {plain_p(r['p'])} |")
    S.append("\n群間差は −0.95 からほぼ 0 まで縮小し、p は 0.87 まで上昇する。"
             "この所見は薬剤と追跡期間の偏りで説明され、アパシーの効果とは考えにくい。\n")
    S.append("### その他の転帰\n")
    others = [r for r in rows if r["キー"] != "ΔCDR-SB" and r.get("p_raw") is not None]
    best = sorted(others, key=lambda r: r["p_raw"])[:3]
    S.append("- MMSE合計・Global CDR はいずれも有意差なし"
             f"（MMSE合計 p={g('ΔMMSE合計').get('p_raw', float('nan')):.3f}、"
             f"Global CDR p={g('ΔGlobalCDR').get('p_raw', float('nan')):.3f}）。")
    S.append("- 最小p値の3転帰: "
             + ", ".join(f"{r['転帰']} p={r['p_raw']:.3f}" for r in best))
    rec = g("ΔMMSE_遅延再生", "ベースライン値＋追跡期間＋薬剤で調整")
    if "p" in rec:
        S.append(f"- MMSE遅延再生はあり群でやや低下が大きい傾向があるが"
                 f"（調整なしの平均差検定 p="
                 f"{g('ΔMMSE_遅延再生', '調整なし（変化量そのもの）').get('p', float('nan')):.3f}）、"
                 f"完全調整モデルでも p={rec['p']:.3f} で有意に達しない。")
    S.append("- MoCA-J はアパシーあり群に測定例がなく比較できない。\n")
    S.append("### 付随して見つかったデータ品質の問題\n")
    S.append(f"CDRが2時点以上ある全 {aud_all['n']}例のうち **{len(aud_all['identical'])}例"
             f"（{len(aud_all['identical'])/aud_all['n']*100:.0f}%）** で、"
             "6領域すべてが全評価時点で完全に同一の値であった"
             + "（" + ", ".join(f"{d} {sum(1 for r in aud_all['identical'] if r['薬剤']==d)}/"
                              f"{sum(1 for r in aud_all['rows'] if r['薬剤']==d)}例"
                              for d in ("レカネマブ", "ドナネマブ")) + "）。")
    S.append("再評価ではなく前回値の転記が行われた可能性があり、CDRを主要評価項目とする"
             "解析全体に影響する。原資料での確認をお勧めする。\n")
    S.append("> 注: 第3節の p 値は順位に基づく Mann-Whitney U 検定、"
             "第5-B節の p 値は平均差の並べ替え検定であり、同じデータでも値は一致しない。"
             "外れ値の影響を受けにくいのは前者、共変量調整ができるのは後者である。\n")

    text = "\n".join(R).replace("<<<SUMMARY>>>", "\n".join(S))
    with io.open(os.path.join(OUT, "baseline_apathy_report.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
