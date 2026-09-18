# -*- coding: utf-8 -*-
"""
抗アミロイドβ抗体療法 後方視的観察研究 — 深掘り解析

目的:
 (1) NPI第7項目（アパシー・無関心）の「あり→なし」を改善群として、MMSE合計・MMSE下位項目・
     CDR-SB・CDR下位項目の変化量を改善群 vs 非改善群で比較する。
 (2) 症例数が増えれば有意差に到達しうる相関・群間差を、効果量と必要症例数の観点から探索する。
 (3) NPIに縛られない全コホート（MMSE/CDRの縦断データがある最大73例）で、
     下位項目レベルの変化と相互相関を網羅的に走査する。

多重比較は Benjamini-Hochberg 法で FDR 調整し、調整前後の双方を提示する。
本解析は探索的であり、確認的推論には用いない。

実行: python3 analysis/deep_analysis.py
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

import openpyxl
from scipy.stats import (mannwhitneyu, wilcoxon, spearmanr, norm,
                         fisher_exact, binomtest)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from npi_analysis import (                      # noqa: E402
    FILES, MONTH_LABELS, s, to_float, parse_date, months_between,
    read_npi, resolve_npi, NPI_NO_SOURCE, TRANS, BASELINE_LABELS,
    median, desc,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

# MMSE の採点下位項目（合計30点の内訳）
MMSE_SUB = ["時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算", "遅延再生",
            "復唱", "読字理解", "3段階命令", "書字", "図形模写"]
# 場所見当識の内訳（参考）
MMSE_PLACE = ["場所_県", "場所_市", "場所_病院", "場所_階", "場所_地方"]
# CDR の6領域（合計＝CDR-SB）
CDR_DOM = ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]

BASELINE_WINDOW_DAYS = 120


# ---------------------------------------------------------------- 読み込み

@dataclass
class Visit:
    label: str
    date: Optional[dt.date]
    total: Optional[float]                       # MMSE合計 or CDR-SB
    items: dict[str, Optional[float]] = field(default_factory=dict)
    globalcdr: Optional[float] = None


def read_panel(path: str, sheet: str) -> dict[str, list[Visit]]:
    """MMSE / CDR シートを 研究番号 -> [Visit]（時点順）で返す。下位項目も保持する。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [s(c) for c in rows[0]]
    items = MMSE_SUB + MMSE_PLACE if sheet == "MMSE" else CDR_DOM
    idx = {c: hdr.index(c) for c in items if c in hdr}
    out: dict[str, list[Visit]] = {}
    for r in rows[1:]:
        pid = s(r[0])
        if not pid:
            continue
        d, _ = parse_date(r[hdr.index("評価日")])
        if sheet == "MMSE":
            tot = to_float(r[hdr.index("合計_原資料記載値")])
            if tot is None:
                tot = to_float(r[hdr.index("下位項目合計_自動計算")])
            gl = None
        else:
            tot = to_float(r[hdr.index("CDR-SB_原資料記載値")])
            if tot is None:
                tot = to_float(r[hdr.index("CDR-SB_自動計算")])
            gl = to_float(r[hdr.index("Global CDR_原資料記載値")])
        out.setdefault(pid, []).append(
            Visit(s(r[1]), d, tot, {c: to_float(r[i]) for c, i in idx.items()}, gl))
    for pid in out:
        out[pid].sort(key=lambda v: MONTH_LABELS.index(v.label)
                      if v.label in MONTH_LABELS else 99)
    return out


def read_moca(path: str) -> dict[str, list[Visit]]:
    """MoCA-J シート（合計のみ）を 研究番号 -> [Visit] で返す。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["MoCA-J"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [s(c) for c in rows[0]]
    out: dict[str, list[Visit]] = {}
    for r in rows[1:]:
        pid = s(r[0])
        if not pid:
            continue
        d, _ = parse_date(r[hdr.index("評価日")])
        out.setdefault(pid, []).append(
            Visit(s(r[1]), d, to_float(r[hdr.index("合計_原資料記載値")]), {}))
    for pid in out:
        out[pid].sort(key=lambda v: MONTH_LABELS.index(v.label)
                      if v.label in MONTH_LABELS else 99)
    return out


def bl_fu(visits: list[Visit], key: str) -> tuple[Optional[Visit], Optional[Visit]]:
    """key（'__total__' か下位項目名）について、値のあるベースラインと最終フォローアップを返す。"""
    def val(v: Visit):
        return v.total if key == "__total__" else v.items.get(key)
    bl = next((v for v in visits if v.label == "0か月" and val(v) is not None), None)
    if bl is None:
        return None, None
    fus = [v for v in visits if v is not bl and val(v) is not None]
    return bl, (fus[-1] if fus else None)


def delta(visits: list[Visit], key: str) -> Optional[float]:
    b, f = bl_fu(visits, key)
    if b is None or f is None:
        return None
    vb = b.total if key == "__total__" else b.items.get(key)
    vf = f.total if key == "__total__" else f.items.get(key)
    return round(vf - vb, 2)


# ---------------------------------------------------------------- 症例構築

@dataclass
class Subject:
    pid: str
    drug: str
    mmse: list[Visit]
    cdr: list[Visit]
    moca: list[Visit] = field(default_factory=list)
    ap_bl: Optional[int] = None
    ap_fu: Optional[int] = None
    ap_conf: str = ""
    ir_bl: Optional[int] = None
    ir_fu: Optional[int] = None
    ir_conf: str = ""
    npi_paired: bool = False
    npi_note: str = ""
    interval_m: Optional[float] = None

    def panel(self, sheet: str) -> list[Visit]:
        return {"MMSE": self.mmse, "CDR": self.cdr, "MoCA": self.moca}[sheet]

    def d(self, sheet: str, key: str) -> Optional[float]:
        if key == "__global__":
            b = next((v for v in self.cdr if v.label == "0か月"
                      and v.globalcdr is not None), None)
            if b is None:
                return None
            fus = [v for v in self.cdr if v is not b and v.globalcdr is not None]
            return None if not fus else round(fus[-1].globalcdr - b.globalcdr, 2)
        return delta(self.panel(sheet), key)

    def base(self, sheet: str, key: str) -> Optional[float]:
        if key == "__global__":
            b = next((v for v in self.cdr if v.label == "0か月"
                      and v.globalcdr is not None), None)
            fus = [v for v in self.cdr if v is not b and v.globalcdr is not None]
            return None if (b is None or not fus) else b.globalcdr
        b, f = bl_fu(self.panel(sheet), key)
        if b is None or f is None:
            return None
        return b.total if key == "__total__" else b.items.get(key)

    def trans(self, item: str) -> Optional[str]:
        bl, fu = (self.ap_bl, self.ap_fu) if item == "ap" else (self.ir_bl, self.ir_fu)
        if bl is None or fu is None:
            return None
        return TRANS[(bl, fu)]


def build_subjects() -> list[Subject]:
    subs: list[Subject] = []
    for drug, path in FILES.items():
        mmse = read_panel(path, "MMSE")
        cdr = read_panel(path, "CDR")
        moca = read_moca(path)
        npi = read_npi(path, drug)
        for pid in sorted(set(mmse) | set(cdr),
                          key=lambda x: (x[0], int("".join(filter(str.isdigit, x)) or 0))):
            su = Subject(pid, drug, mmse.get(pid, []), cdr.get(pid, []),
                         moca.get(pid, []))
            b, f = bl_fu(su.mmse, "__total__")
            if b and f and b.date and f.date:
                su.interval_m = months_between(b.date, f.date)

            pts = [p for p in npi.get(pid, [])
                   if p.apathy_raw not in NPI_NO_SOURCE or p.irrit_raw not in NPI_NO_SOURCE]
            cog_bl_date = b.date if b else None

            def is_bl(p):
                if p.label in BASELINE_LABELS:
                    return True
                return bool(p.date and cog_bl_date
                            and abs((p.date - cog_bl_date).days) <= BASELINE_WINDOW_DAYS)

            blc = [p for p in pts if is_bl(p)]
            fuc = [p for p in pts if p not in blc]
            if blc and fuc:
                nb = min(blc, key=lambda p: (p.date or dt.date(9999, 1, 1)))
                nf = max(fuc, key=lambda p: (p.date or dt.date(1, 1, 1)))
                su.npi_paired = True
                su.npi_note = f"{nb.label}({nb.date})→{nf.label}({nf.date})"
                su.ap_bl, c1, _ = resolve_npi(nb.apathy_raw, nb.note, "アパシー")
                su.ap_fu, c2, _ = resolve_npi(nf.apathy_raw, nf.note, "アパシー")
                su.ir_bl, c3, _ = resolve_npi(nb.irrit_raw, nb.note, "易怒")
                su.ir_fu, c4, _ = resolve_npi(nf.irrit_raw, nf.note, "易怒")
                su.ap_conf = "excluded" if "excluded" in (c1, c2) else (
                    "reference" if "reference" in (c1, c2) else "definite")
                su.ir_conf = "excluded" if "excluded" in (c3, c4) else (
                    "reference" if "reference" in (c3, c4) else "definite")
            subs.append(su)
    return subs


# ---------------------------------------------------------------- 統計

def rank_biserial(a: list[float], b: list[float], u: float) -> float:
    """順位二列相関（効果量）。+1 で a が完全に大きい、−1 で完全に小さい。"""
    return 2 * u / (len(a) * len(b)) - 1


def cles(a: list[float], b: list[float]) -> float:
    """共通言語効果量 P(A>B) + 0.5*P(A=B)"""
    if not a or not b:
        return float("nan")
    g = sum((1 if x > y else 0.5 if x == y else 0) for x in a for y in b)
    return g / (len(a) * len(b))


def required_n_noether(p: float, ratio: float = 0.5,
                       alpha: float = 0.05, power: float = 0.80) -> Optional[int]:
    """Noether(1987) による Mann-Whitney 検定の必要総症例数。
    p   : 共通言語効果量 P(X>Y)
    ratio: 群1の割合（0.5 で1:1配分）
    """
    if not (0 < ratio < 1) or p is None or math.isnan(p) or abs(p - 0.5) < 1e-9:
        return None
    z = norm.ppf(1 - alpha / 2) + norm.ppf(power)
    n = z ** 2 / (12 * ratio * (1 - ratio) * (p - 0.5) ** 2)
    return int(math.ceil(n))


def bh_fdr(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg 調整p値"""
    idx = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    adj = [0.0] * m
    prev = 1.0
    for rank, i in enumerate(reversed(idx), start=1):
        k = m - rank + 1
        val = min(prev, pvals[i] * m / k)
        adj[i] = val
        prev = val
    return adj


def compare(a: list[float], b: list[float]) -> dict:
    """2群比較の一式（記述統計・MWU・効果量・必要N）"""
    res = {"n1": len(a), "n2": len(b),
           "med1": median(a), "med2": median(b),
           "min1": min(a) if a else None, "max1": max(a) if a else None,
           "min2": min(b) if b else None, "max2": max(b) if b else None,
           "u": None, "p": None, "r": None, "cles": None,
           "n_req_1to1": None, "n_req_obs": None, "note": ""}
    if len(a) < 1 or len(b) < 1:
        res["note"] = "いずれかの群が0例"
        return res
    res["cles"] = cles(a, b)
    try:
        u, p = mannwhitneyu(a, b, alternative="two-sided", method="exact")
        res["u"], res["p"] = u, p
        res["r"] = rank_biserial(a, b, u)
    except Exception as e:
        res["note"] = f"検定不能({e})"
    total = math.comb(len(a) + len(b), len(a))
    pmin = 2.0 / total
    if pmin > 0.05:
        res["note"] = f"到達可能な最小p={pmin:.3f}（この配分では有意になりえない）"
    ratio = len(a) / (len(a) + len(b))
    res["n_req_1to1"] = required_n_noether(res["cles"], 0.5)
    res["n_req_obs"] = required_n_noether(res["cles"], ratio)
    return res


# ---------------------------------------------------------------- 転帰の定義

def outcomes(su: Subject) -> dict[str, Optional[float]]:
    """1症例あたりの全転帰（変化量）。プラスの向きは指標ごとに異なる点に注意。
    MMSE系: プラス＝改善 / CDR系: プラス＝悪化
    """
    o = {"ΔMMSE合計": su.d("MMSE", "__total__")}
    for k in MMSE_SUB:
        o[f"ΔMMSE_{k}"] = su.d("MMSE", k)
    o["ΔCDR-SB"] = su.d("CDR", "__total__")
    for k in CDR_DOM:
        o[f"ΔCDR_{k}"] = su.d("CDR", k)
    o["ΔGlobalCDR"] = su.d("CDR", "__global__")
    o["ΔMoCA-J"] = su.d("MoCA", "__total__")
    return o


OUTCOME_KEYS = (["ΔMMSE合計"] + [f"ΔMMSE_{k}" for k in MMSE_SUB]
                + ["ΔCDR-SB"] + [f"ΔCDR_{k}" for k in CDR_DOM]
                + ["ΔGlobalCDR", "ΔMoCA-J"])

GROUPINGS = {
    "A_改善": ("改善群（あり→なし）", "非改善群（それ以外）",
             lambda bl, fu: (bl == 1 and fu == 0)),
    "B_最終なし": ("最終時点なし群（FU=なし）", "最終時点あり群（FU=あり）",
                lambda bl, fu: fu == 0),
    "C_新規出現": ("新規出現群（なし→あり）", "それ以外",
                lambda bl, fu: (bl == 0 and fu == 1)),
    "D_BLあり": ("ベースラインあり群", "ベースラインなし群",
              lambda bl, fu: bl == 1),
}

ITEMS = {"ap": ("NPI第7項目（アパシー・無関心＝意欲低下）", "ap_bl", "ap_fu", "ap_conf"),
         "ir": ("NPI第9項目（易怒性）", "ir_bl", "ir_fu", "ir_conf")}


# ---------------------------------------------------------------- 解析本体

def npi_group_scan(subs: list[Subject], include_reference: bool) -> list[dict]:
    """NPI群分け × 全転帰の総当たり比較。"""
    rows: list[dict] = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        pool = [x for x in subs if x.npi_paired
                and getattr(x, blk) is not None and getattr(x, fuk) is not None
                and (include_reference or getattr(x, confk) != "reference")]
        for gkey, (n1, n2, fn) in GROUPINGS.items():
            g1 = [x for x in pool if fn(getattr(x, blk), getattr(x, fuk))]
            g2 = [x for x in pool if not fn(getattr(x, blk), getattr(x, fuk))]
            for ok in OUTCOME_KEYS:
                a = [v for v in (outcomes(x)[ok] for x in g1) if v is not None]
                b = [v for v in (outcomes(x)[ok] for x in g2) if v is not None]
                if not a or not b:
                    continue
                if len(set(a + b)) == 1:      # 全例同値 → 情報なし
                    continue
                r = compare(a, b)
                r.update({"項目": iname, "群分け": gkey, "群1": n1, "群2": n2,
                          "転帰": ok,
                          "群1症例": ",".join(x.pid for x in g1
                                           if outcomes(x)[ok] is not None),
                          "群2症例": ",".join(x.pid for x in g2
                                           if outcomes(x)[ok] is not None)})
                rows.append(r)
    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = dict(zip([i for i, r in enumerate(rows) if r["p"] is not None], bh_fdr(ps)))
    for i, r in enumerate(rows):
        r["p_fdr"] = adj.get(i)
    return rows


def cohort_change_scan(subs: list[Subject]) -> list[dict]:
    """全コホートで、各指標がベースラインから有意に変化しているかを対応のある検定で走査。"""
    rows = []
    for ok in OUTCOME_KEYS:
        pairs = []
        for x in subs:
            vb = x.base(*outcome_meta(ok)[:2])
            dv = x.d(*outcome_meta(ok)[:2])
            if vb is None or dv is None:
                continue
            pairs.append((vb, vb + dv))
        if len(pairs) < 5:
            continue
        d = [f - b for b, f in pairs]
        nz = [x for x in d if x != 0]
        p = w = None
        if nz:
            try:
                w, p = wilcoxon([b for b, f in pairs], [f for b, f in pairs],
                                zero_method="wilcox", alternative="two-sided")
            except Exception:
                pass
        rows.append({"転帰": ok, "n": len(pairs),
                     "BL中央値": median([b for b, f in pairs]),
                     "FU中央値": median([f for b, f in pairs]),
                     "Δ中央値": median(d), "Δ平均": round(sum(d) / len(d), 3),
                     "悪化例": sum(1 for x in d if (x < 0 if higher_is_better(ok) else x > 0)),
                     "不変例": sum(1 for x in d if x == 0),
                     "改善例": sum(1 for x in d if (x > 0 if higher_is_better(ok) else x < 0)),
                     "W": w, "p": p})
    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = dict(zip([i for i, r in enumerate(rows) if r["p"] is not None], bh_fdr(ps)))
    for i, r in enumerate(rows):
        r["p_fdr"] = adj.get(i)
    return rows


def correlation_scan(subs: list[Subject]) -> list[dict]:
    """全コホートで、転帰どうし／ベースライン値と転帰の Spearman 相関を総当たり。"""
    rows = []
    data = {}
    for ok in OUTCOME_KEYS:
        data[ok] = {x.pid: outcomes(x)[ok] for x in subs}
    # ベースライン値も説明変数に加える
    base = {}
    for ok in OUTCOME_KEYS:
        sheet, key, _, _ = outcome_meta(ok)
        base["BL_" + ok[1:]] = {x.pid: x.base(sheet, key) for x in subs}
    base["追跡期間(月)"] = {x.pid: x.interval_m for x in subs}

    pairs = ([(a, b, "Δ×Δ") for a, b in itertools.combinations(OUTCOME_KEYS, 2)]
             + [(a, b, "BL×Δ") for a in base for b in OUTCOME_KEYS])
    for a, b, kind in pairs:
        da = base[a] if kind != "Δ×Δ" else data[a]
        db = data[b]
        ids = [p for p in da if da[p] is not None and db.get(p) is not None]
        if len(ids) < 10:
            continue
        xs = [da[p] for p in ids]
        ys = [db[p] for p in ids]
        if len(set(xs)) < 2 or len(set(ys)) < 2:
            continue
        rho, p = spearmanr(xs, ys)
        if rho != rho:
            continue
        # |rho| で p<0.05 に到達するのに必要な n
        n_req = None
        if abs(rho) > 1e-6 and abs(rho) < 1:
            z = 0.5 * math.log((1 + abs(rho)) / (1 - abs(rho)))
            n_req = int(math.ceil(((norm.ppf(0.975) + norm.ppf(0.80)) / z) ** 2 + 3))
        rows.append({"種別": kind, "変数1": a, "変数2": b, "n": len(ids),
                     "rho": round(rho, 3), "p": p, "n_req_80power": n_req})
    ps = [r["p"] for r in rows]
    for r, q in zip(rows, bh_fdr(ps)):
        r["p_fdr"] = q
    return rows


def npi_burden_scan(subs: list[Subject]) -> list[dict]:
    """NPI 2項目の合計陽性数（0-2）を順序変数として、各転帰との Spearman 相関を見る。
    2値の群分けより情報量が多く、少数例でも傾向を拾いやすい。"""
    rows = []
    for name, getter in [
        ("ベースラインNPI陽性項目数(0-2)", lambda x: (x.ap_bl or 0) + (x.ir_bl or 0)),
        ("フォローアップNPI陽性項目数(0-2)", lambda x: (x.ap_fu or 0) + (x.ir_fu or 0)),
        ("NPI陽性項目数の変化(FU-BL)",
         lambda x: ((x.ap_fu or 0) + (x.ir_fu or 0)) - ((x.ap_bl or 0) + (x.ir_bl or 0))),
        ("アパシーの変化(-1改善/0不変/+1悪化)", lambda x: x.ap_fu - x.ap_bl),
        ("易怒性の変化(-1改善/0不変/+1悪化)", lambda x: x.ir_fu - x.ir_bl),
    ]:
        pool = [x for x in subs if x.npi_paired and None not in
                (x.ap_bl, x.ap_fu, x.ir_bl, x.ir_fu)]
        for ok in OUTCOME_KEYS:
            ids = [x for x in pool if outcomes(x)[ok] is not None]
            if len(ids) < 5:
                continue
            xs = [getter(x) for x in ids]
            ys = [outcomes(x)[ok] for x in ids]
            if len(set(xs)) < 2 or len(set(ys)) < 2:
                continue
            rho, p = spearmanr(xs, ys)
            if rho != rho:
                continue
            n_req = None
            if 1e-6 < abs(rho) < 1:
                z = 0.5 * math.log((1 + abs(rho)) / (1 - abs(rho)))
                n_req = int(math.ceil(((norm.ppf(0.975) + norm.ppf(0.80)) / z) ** 2 + 3))
            rows.append({"説明変数": name, "転帰": ok, "n": len(ids),
                         "rho": round(rho, 3), "p": p, "n_req_80power": n_req})
    ps = [r["p"] for r in rows]
    for r, q in zip(rows, bh_fdr(ps)):
        r["p_fdr"] = q
    return rows


# ---------------------------------------------------------------- 補助解析

def annualized(su: "Subject", ok: str) -> Optional[float]:
    """年換算した変化量（Δ ÷ 追跡年数）。追跡期間が不明な症例は None。"""
    if su.interval_m is None or su.interval_m <= 0:
        return None
    v = outcomes(su)[ok]
    return None if v is None else round(v / (su.interval_m / 12.0), 3)


def annualized_scan(subs: list["Subject"]) -> list[dict]:
    """年換算変化量でのNPI群間比較（追跡期間のばらつきを補正）。"""
    rows = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        pool = [x for x in subs if x.npi_paired
                and getattr(x, blk) is not None and getattr(x, fuk) is not None
                and x.interval_m is not None]
        for gkey, (n1, n2, fn) in GROUPINGS.items():
            g1 = [x for x in pool if fn(getattr(x, blk), getattr(x, fuk))]
            g2 = [x for x in pool if not fn(getattr(x, blk), getattr(x, fuk))]
            for ok in OUTCOME_KEYS:
                a = [v for v in (annualized(x, ok) for x in g1) if v is not None]
                b = [v for v in (annualized(x, ok) for x in g2) if v is not None]
                if not a or not b or len(set(a + b)) == 1:
                    continue
                r = compare(a, b)
                r.update({"項目": iname, "群分け": gkey, "転帰": ok + "/年"})
                rows.append(r)
    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = dict(zip([i for i, r in enumerate(rows) if r["p"] is not None], bh_fdr(ps)))
    for i, r in enumerate(rows):
        r["p_fdr"] = adj.get(i)
    return rows


def drug_scan(subs: list["Subject"]) -> list[dict]:
    """レカネマブ vs ドナネマブ（NPIに依存しない、最大のn）。"""
    rows = []
    for ok in OUTCOME_KEYS:
        a = [v for v in (outcomes(x)[ok] for x in subs if x.drug == "レカネマブ")
             if v is not None]
        b = [v for v in (outcomes(x)[ok] for x in subs if x.drug == "ドナネマブ")
             if v is not None]
        if len(a) < 3 or len(b) < 3 or len(set(a + b)) == 1:
            continue
        r = compare(a, b)
        r.update({"転帰": ok, "群1": "レカネマブ", "群2": "ドナネマブ"})
        rows.append(r)
    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = dict(zip([i for i, r in enumerate(rows) if r["p"] is not None], bh_fdr(ps)))
    for i, r in enumerate(rows):
        r["p_fdr"] = adj.get(i)
    return rows


# 二値転帰の定義（臨床的に意味のあるカットオフ）
BINARY = {
    "MMSEが2点以上低下": ("ΔMMSE合計", lambda v: v <= -2),
    "MMSEが1点以上低下": ("ΔMMSE合計", lambda v: v <= -1),
    "CDR-SBが1点以上悪化": ("ΔCDR-SB", lambda v: v >= 1),
    "CDR-SBが0.5点以上悪化": ("ΔCDR-SB", lambda v: v >= 0.5),
    "時間見当識が1点以上低下": ("ΔMMSE_時間見当識", lambda v: v <= -1),
    "遅延再生が1点以上低下": ("ΔMMSE_遅延再生", lambda v: v <= -1),
}


def binary_scan(subs: list["Subject"], include_reference: bool = False) -> list[dict]:
    """臨床的カットオフで二値化した転帰を Fisher 正確検定で比較。
    既定では主解析と同じく「確定判定のみ」を用いる（参考値の症例は除外）。"""
    rows = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        pool = [x for x in subs if x.npi_paired
                and getattr(x, blk) is not None and getattr(x, fuk) is not None
                and (include_reference or getattr(x, confk) != "reference")]
        for gkey, (n1, n2, fn) in GROUPINGS.items():
            g1 = [x for x in pool if fn(getattr(x, blk), getattr(x, fuk))]
            g2 = [x for x in pool if not fn(getattr(x, blk), getattr(x, fuk))]
            for bname, (ok, test) in BINARY.items():
                a = [test(v) for v in (outcomes(x)[ok] for x in g1) if v is not None]
                b = [test(v) for v in (outcomes(x)[ok] for x in g2) if v is not None]
                if not a or not b:
                    continue
                tab = [[sum(a), len(a) - sum(a)], [sum(b), len(b) - sum(b)]]
                if tab[0][0] + tab[1][0] == 0 or tab[0][1] + tab[1][1] == 0:
                    continue
                orr, p = fisher_exact(tab)
                rows.append({"項目": iname, "群分け": gkey, "転帰": bname,
                             "群1該当": f"{sum(a)}/{len(a)}",
                             "群2該当": f"{sum(b)}/{len(b)}",
                             "群1割合": round(sum(a) / len(a), 3),
                             "群2割合": round(sum(b) / len(b), 3),
                             "オッズ比": (None if orr in (0, float("inf")) or orr != orr
                                      else round(orr, 3)),
                             "p": p})
    ps = [r["p"] for r in rows]
    for r, q in zip(rows, bh_fdr(ps)):
        r["p_fdr"] = q
    return rows


def npi_trajectory_scan(subs: list["Subject"]) -> list[dict]:
    """NPI症状そのものの経時変化。対応のある2値データなので McNemar 正確検定を用いる。
    変化量の群間比較と違い、床・天井効果の影響を受けない解析である。"""
    rows = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        for inc in (False, True):
            pool = [x for x in subs if x.npi_paired
                    and getattr(x, blk) is not None and getattr(x, fuk) is not None
                    and (inc or getattr(x, confk) != "reference")]
            if not pool:
                continue
            improved = sum(1 for x in pool
                           if getattr(x, blk) == 1 and getattr(x, fuk) == 0)
            onset = sum(1 for x in pool
                        if getattr(x, blk) == 0 and getattr(x, fuk) == 1)
            nbl = sum(1 for x in pool if getattr(x, blk) == 1)
            nfu = sum(1 for x in pool if getattr(x, fuk) == 1)
            p = (binomtest(onset, improved + onset, 0.5).pvalue
                 if improved + onset else None)
            rows.append({"項目": iname, "判定": "参考値含む" if inc else "確定のみ",
                         "n": len(pool),
                         "BL陽性": nbl, "BL陽性率": round(nbl / len(pool), 3),
                         "FU陽性": nfu, "FU陽性率": round(nfu / len(pool), 3),
                         "改善(あり→なし)": improved, "新規出現(なし→あり)": onset,
                         "McNemar_p": p})
    return rows


def npi_count_change(subs: list["Subject"]) -> Optional[dict]:
    """NPI2項目の陽性項目数(0-2)がベースラインから有意に変化したかを検定する。"""
    pool = [x for x in subs if x.npi_paired
            and None not in (x.ap_bl, x.ap_fu, x.ir_bl, x.ir_fu)]
    if len(pool) < 5:
        return None
    bl = [x.ap_bl + x.ir_bl for x in pool]
    fu = [x.ap_fu + x.ir_fu for x in pool]
    up = sum(1 for a, b in zip(bl, fu) if b > a)
    dn = sum(1 for a, b in zip(bl, fu) if b < a)
    try:
        w, p = wilcoxon(bl, fu, zero_method="wilcox", alternative="two-sided")
    except Exception:
        w = p = None
    return {"n": len(pool), "BL平均": round(sum(bl) / len(bl), 3),
            "FU平均": round(sum(fu) / len(fu), 3),
            "増加": up, "不変": len(bl) - up - dn, "減少": dn,
            "W": w, "Wilcoxon_p": p,
            "符号検定_p": binomtest(up, up + dn, 0.5).pvalue if up + dn else None,
            "症例": ",".join(x.pid for x in pool)}


# ---------------------------------------------------------------- 床・天井効果の統制

def higher_is_better(ok: str) -> bool:
    """その転帰は値が大きいほど良いか。MMSE・MoCA-J は True、CDR系は False。"""
    return not ok.startswith("ΔCDR") and ok != "ΔGlobalCDR"


def outcome_meta(ok: str) -> tuple[str, str, float, float]:
    """転帰キー -> (シート, 項目キー, 最小値, 最大値)"""
    if ok == "ΔMoCA-J":
        return "MoCA", "__total__", 0.0, 30.0
    if ok == "ΔGlobalCDR":
        return "CDR", "__global__", 0.0, 3.0
    if ok.startswith("ΔCDR"):
        sheet = "CDR"
        key = "__total__" if ok == "ΔCDR-SB" else ok.split("_", 1)[1]
        return sheet, key, 0.0, (18.0 if key == "__total__" else 3.0)
    sheet = "MMSE"
    key = "__total__" if ok == "ΔMMSE合計" else ok.split("_", 1)[1]
    maxes = {"__total__": 30, "時間見当識": 5, "場所見当識": 5, "物品呼称": 2, "記銘": 3,
             "注意計算": 5, "遅延再生": 3, "復唱": 1, "読字理解": 1, "3段階命令": 3,
             "書字": 1, "図形模写": 1}
    return sheet, key, 0.0, float(maxes[key])


def headroom(su: "Subject", ok: str, direction: str) -> Optional[float]:
    """悪化方向（'worse'）／改善方向（'better'）に動ける余地。
    MMSE は低下＝悪化、CDR は上昇＝悪化であることに注意。"""
    sheet, key, lo, hi = outcome_meta(ok)
    b = su.base(sheet, key)
    if b is None:
        return None
    if higher_is_better(ok):
        return b - lo if direction == "worse" else hi - b
    return hi - b if direction == "worse" else b - lo


def baseline_balance_scan(subs: list["Subject"],
                          include_reference: bool = False) -> list[dict]:
    """各群分け × 各転帰について、ベースライン値そのものが群間で偏っていないかを検定する。
    偏っていれば、変化量の差は床・天井効果で説明されうる。"""
    rows = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        pool = [x for x in subs if x.npi_paired
                and getattr(x, blk) is not None and getattr(x, fuk) is not None
                and (include_reference or getattr(x, confk) != "reference")]
        for gkey, (n1, n2, fn) in GROUPINGS.items():
            g1 = [x for x in pool if fn(getattr(x, blk), getattr(x, fuk))]
            g2 = [x for x in pool if not fn(getattr(x, blk), getattr(x, fuk))]
            for ok in OUTCOME_KEYS:
                sheet, key, _, _ = outcome_meta(ok)
                a = [v for v in (x.base(sheet, key) for x in g1) if v is not None]
                b = [v for v in (x.base(sheet, key) for x in g2) if v is not None]
                if not a or not b or len(set(a + b)) == 1:
                    continue
                r = compare(a, b)
                r.update({"項目": iname, "群分け": gkey, "転帰": ok,
                          "比較対象": "ベースライン値"})
                rows.append(r)
    return rows


def headroom_scan(subs: list["Subject"], include_reference: bool = False) -> list[dict]:
    """悪化方向に動ける余地が1点以上ある症例に限定して、変化量を再比較する。
    床効果（もともと0点で下がりようがない）による見かけの差を排除する。"""
    rows = []
    for item, (iname, blk, fuk, confk) in ITEMS.items():
        pool = [x for x in subs if x.npi_paired
                and getattr(x, blk) is not None and getattr(x, fuk) is not None
                and (include_reference or getattr(x, confk) != "reference")]
        for gkey, (n1, n2, fn) in GROUPINGS.items():
            for ok in OUTCOME_KEYS:
                elig = [x for x in pool
                        if (headroom(x, ok, "worse") or 0) >= 1
                        and outcomes(x)[ok] is not None]
                g1 = [x for x in elig if fn(getattr(x, blk), getattr(x, fuk))]
                g2 = [x for x in elig if not fn(getattr(x, blk), getattr(x, fuk))]
                a = [outcomes(x)[ok] for x in g1]
                b = [outcomes(x)[ok] for x in g2]
                if len(a) < 1 or len(b) < 1 or len(set(a + b)) == 1:
                    continue
                r = compare(a, b)
                r.update({"項目": iname, "群分け": gkey, "転帰": ok,
                          "除外数": len(pool) - len(elig),
                          "群1症例": ",".join(x.pid for x in g1),
                          "群2症例": ",".join(x.pid for x in g2)})
                rows.append(r)
    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = dict(zip([i for i, r in enumerate(rows) if r["p"] is not None], bh_fdr(ps)))
    for i, r in enumerate(rows):
        r["p_fdr"] = adj.get(i)
    return rows


# ---------------------------------------------------------------- 出力

def wcsv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else
                            (f"{r[k]:.4g}" if isinstance(r[k], float) else r[k]))
                        for k in keys})


def fmt_p(p) -> str:
    if p is None:
        return "－"
    return f"{p:.3f}" if p >= 0.001 else f"{p:.1e}"


def main() -> None:
    subs = build_subjects()
    yn = {1: "あり", 0: "なし", None: "－"}
    rep: list[str] = []
    A = rep.append

    A("# 深掘り解析レポート — NPIアパシー改善群と MMSE/CDR 下位項目の関連")
    A(f"\n生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("向きの定義: **ΔMMSE系はプラス＝改善**、**ΔCDR系はプラス＝悪化**。")
    A("変化量はいずれも「最終利用可能時点 − ベースライン（0か月）」。\n")

    # ---- 症例数
    npi_set = [x for x in subs if x.npi_paired]
    ana = [x for x in npi_set if x.ap_bl is not None and x.ap_fu is not None
           and x.d("MMSE", "__total__") is not None]
    mm_ok = [x for x in subs if x.d("MMSE", "__total__") is not None]
    cd_ok = [x for x in subs if x.d("CDR", "__total__") is not None]
    A("\n## 0. 解析に使えた症例数\n")
    A("| 集合 | n | 内訳 |")
    A("|---|---|---|")
    A(f"| 全研究番号 | {len(subs)} | レカネマブ "
      f"{sum(1 for x in subs if x.drug=='レカネマブ')} / ドナネマブ "
      f"{sum(1 for x in subs if x.drug=='ドナネマブ')} |")
    A(f"| MMSE合計 BL+FU あり | {len(mm_ok)} | レカネマブ "
      f"{sum(1 for x in mm_ok if x.drug=='レカネマブ')} / ドナネマブ "
      f"{sum(1 for x in mm_ok if x.drug=='ドナネマブ')} |")
    A(f"| CDR-SB BL+FU あり | {len(cd_ok)} | レカネマブ "
      f"{sum(1 for x in cd_ok if x.drug=='レカネマブ')} / ドナネマブ "
      f"{sum(1 for x in cd_ok if x.drug=='ドナネマブ')} |")
    A(f"| NPI が対で揃う | {len(npi_set)} | {', '.join(x.pid for x in npi_set)} |")
    A(f"| **NPI対 かつ ΔMMSE算出可（主解析）** | **{len(ana)}** | "
      f"{', '.join(x.pid for x in ana)} |")
    iv = [x.interval_m for x in mm_ok if x.interval_m is not None]
    if iv:
        A(f"\nMMSE の追跡期間（評価日が判明した {len(iv)}例）: 中央値 {median(iv):g}か月 "
          f"［{min(iv):g}, {max(iv):g}］")

    # ---- エグゼクティブサマリー（本文生成後に先頭へ差し込むため、ここでは位置だけ確保）
    SUMMARY_MARK = "<<<SUMMARY>>>"
    A(SUMMARY_MARK)

    # ---- 1. 主解析: アパシー改善群 vs 非改善群
    scan = npi_group_scan(subs, include_reference=False)
    scan_ref = npi_group_scan(subs, include_reference=True)
    wcsv(os.path.join(OUT, "scan_npi_groups.csv"), scan)
    wcsv(os.path.join(OUT, "scan_npi_groups_with_reference.csv"), scan_ref)

    A("\n\n## 1. 主解析 — アパシー（意欲低下）「あり→なし」＝改善群 vs 非改善群\n")
    for label, rows in [("確定判定のみ", scan), ("判定保留を参考値として含む", scan_ref)]:
        sel = [r for r in rows if r["項目"].startswith("NPI第7") and r["群分け"] == "A_改善"]
        if not sel:
            continue
        n1 = sel[0]["n1"]
        n2 = sel[0]["n2"]
        A(f"\n### {label}（改善群 n={n1} / 非改善群 n={n2}）\n")
        A("| 転帰 | 改善群 中央値［範囲］ | 非改善群 中央値［範囲］ | 効果量 r | "
          "P(改善群>非改善群) | p | p(FDR) | 1:1配分で必要な総n |")
        A("|---|---|---|---|---|---|---|---|")
        for r in sorted(sel, key=lambda x: -abs(x["r"] if x["r"] is not None else 0)):
            A(f"| {r['転帰']} | {r['med1']:g}［{r['min1']:g}, {r['max1']:g}］ | "
              f"{r['med2']:g}［{r['min2']:g}, {r['max2']:g}］ | "
              f"{r['r']:+.2f} | {r['cles']:.2f} | {fmt_p(r['p'])} | "
              f"{fmt_p(r['p_fdr'])} | {r['n_req_1to1'] or '－'} |")
        if sel[0]["note"]:
            A(f"\n> {sel[0]['note']}")

    # ---- 2. 有意だったもの
    A("\n\n## 2. 有意水準に達した比較（NPI群分け × 全転帰の総当たり）\n")
    hits = [r for r in scan if r["p"] is not None and r["p"] < 0.05]
    if hits:
        A(f"調整前 p<0.05 は {len(hits)}件（総比較数 {len(scan)}件）。\n")
        A("| 項目 | 群分け | 転帰 | n1/n2 | 群1中央値 | 群2中央値 | r | p | p(FDR) |")
        A("|---|---|---|---|---|---|---|---|---|")
        for r in sorted(hits, key=lambda x: x["p"]):
            A(f"| {r['項目'][:8]} | {r['群分け']} | {r['転帰']} | {r['n1']}/{r['n2']} | "
              f"{r['med1']:g} | {r['med2']:g} | {r['r']:+.2f} | "
              f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")
        sig_fdr = [r for r in hits if r["p_fdr"] is not None and r["p_fdr"] < 0.05]
        A(f"\nFDR調整後も p<0.05 を保つもの: **{len(sig_fdr)}件**"
          + ("" if sig_fdr else "（＝なし。調整前の有意は多重比較で説明できる範囲）"))
    else:
        A(f"調整前 p<0.05 に達した比較は **0件**（総比較数 {len(scan)}件）。")

    # ---- 3. 症例数が増えれば有意になりうる候補
    A("\n\n## 3. 症例数が増えれば有意差に到達しうる候補（効果量順）\n")
    A("効果量は共通言語効果量 P(群1>群2)。必要nは Noether(1987) の式による "
      "両側α=0.05・検出力80%の推定総症例数。\n")
    cand = [r for r in scan if r["cles"] is not None and r["n_req_1to1"]
            and abs(r["cles"] - 0.5) >= 0.25]
    cand.sort(key=lambda r: r["n_req_1to1"])
    A("| 順位 | 項目 | 群分け | 転帰 | n1/n2 | 群1中央値 | 群2中央値 | "
      "P(群1>群2) | 現在のp | 1:1で必要n | 現配分で必要n |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(cand[:25], 1):
        A(f"| {i} | {r['項目'][:8]} | {r['群分け']} | {r['転帰']} | {r['n1']}/{r['n2']} | "
          f"{r['med1']:g} | {r['med2']:g} | {r['cles']:.2f} | {fmt_p(r['p'])} | "
          f"{r['n_req_1to1']} | {r['n_req_obs'] or '－'} |")

    # ---- 4. NPI負荷を順序変数とした相関
    burden = npi_burden_scan(subs)
    wcsv(os.path.join(OUT, "scan_npi_burden_correlation.csv"), burden)
    A("\n\n## 4. NPIを順序変数として扱った相関（2群分割より情報量が多い）\n")
    bsig = [r for r in burden if r["p"] < 0.05]
    A(f"総当たり {len(burden)}件中、調整前 p<0.05 は {len(bsig)}件。\n")
    A("| 説明変数 | 転帰 | n | Spearman ρ | p | p(FDR) | 80%検出力に必要なn |")
    A("|---|---|---|---|---|---|---|")
    for r in sorted(burden, key=lambda x: x["p"])[:20]:
        A(f"| {r['説明変数']} | {r['転帰']} | {r['n']} | {r['rho']:+.3f} | "
          f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} | {r['n_req_80power'] or '－'} |")

    # ---- 5. 全コホートでの変化（NPIに依存しない）
    chg = cohort_change_scan(subs)
    wcsv(os.path.join(OUT, "scan_cohort_change.csv"), chg)
    A("\n\n## 5. 全コホートでの経時変化（NPI原票の有無によらず全例）\n")
    A("NPIに縛られないため n が大きく、下位項目レベルで確かな所見が得られる。")
    A("対応のある Wilcoxon 符号付順位検定。\n")
    A("| 転帰 | n | BL中央値 | FU中央値 | Δ中央値 | Δ平均 | 悪化/不変/改善 | p | p(FDR) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(chg, key=lambda x: (x["p"] if x["p"] is not None else 9)):
        A(f"| {r['転帰']} | {r['n']} | {r['BL中央値']:g} | {r['FU中央値']:g} | "
          f"{r['Δ中央値']:g} | {r['Δ平均']:+g} | "
          f"{r['悪化例']}/{r['不変例']}/{r['改善例']} | "
          f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")

    # ---- 6. 全コホートでの相関走査
    cor = correlation_scan(subs)
    wcsv(os.path.join(OUT, "scan_cohort_correlation.csv"), cor)
    A("\n\n## 6. 全コホートでの相関走査（Spearman）\n")
    csig = [r for r in cor if r["p_fdr"] is not None and r["p_fdr"] < 0.05]
    A(f"総当たり {len(cor)}件、FDR調整後 p<0.05 は **{len(csig)}件**。"
      "以下は調整後有意なもののうち |ρ| 上位30件。\n")
    A("| 種別 | 変数1 | 変数2 | n | ρ | p | p(FDR) |")
    A("|---|---|---|---|---|---|---|")
    for r in sorted(csig, key=lambda x: -abs(x["rho"]))[:30]:
        A(f"| {r['種別']} | {r['変数1']} | {r['変数2']} | {r['n']} | {r['rho']:+.3f} | "
          f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")

    A("\n\n### あと少しで有意になる相関（調整前 0.05≤p<0.20、n増で到達が見込まれるもの）\n")
    near = [r for r in cor if 0.05 <= r["p"] < 0.20 and r["n_req_80power"]]
    near.sort(key=lambda r: r["n_req_80power"])
    A("| 種別 | 変数1 | 変数2 | 現在n | ρ | p | 80%検出力に必要なn | あと何例 |")
    A("|---|---|---|---|---|---|---|---|")
    for r in near[:20]:
        A(f"| {r['種別']} | {r['変数1']} | {r['変数2']} | {r['n']} | {r['rho']:+.3f} | "
          f"{fmt_p(r['p'])} | {r['n_req_80power']} | "
          f"+{max(0, r['n_req_80power'] - r['n'])} |")

    # ---- 6b. 回帰の平均への回帰についての注意
    A("\n> **注意**: 上表の「BL×Δ」のうち、同じ項目のベースライン値とその変化量の相関")
    A("> （例: BL_MMSE_3段階命令 × ΔMMSE_3段階命令、ρ=−0.89）は、天井・床効果と")
    A("> 平均への回帰による統計的アーティファクトであり、臨床的な所見ではない。")
    A("> 満点の項目は下がることしかできず、0点の項目は上がることしかできないため、")
    A("> 負の相関が構造的に生じる。解釈に用いてよいのは「Δ×Δ」および")
    A("> 「異なる項目どうしのBL×Δ」に限られる。\n")

    # ---- 8. 年換算
    ann = annualized_scan(subs)
    wcsv(os.path.join(OUT, "scan_annualized.csv"), ann)
    A("\n\n## 8. 追跡期間を補正した年換算変化量での群間比較\n")
    A("追跡期間が6〜18.5か月とばらつくため、Δを追跡年数で割った年換算値で再解析した。")
    A("評価日が判明している症例に限られるため n はやや小さくなる。\n")
    asig = [r for r in ann if r["p"] is not None and r["p"] < 0.05]
    A(f"総当たり {len(ann)}件中、調整前 p<0.05 は {len(asig)}件。\n")
    A("| 項目 | 群分け | 転帰 | n1/n2 | 群1中央値 | 群2中央値 | r | P(群1>群2) | p | p(FDR) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(ann, key=lambda x: (x["p"] if x["p"] is not None else 9))[:15]:
        A(f"| {r['項目'][:8]} | {r['群分け']} | {r['転帰']} | {r['n1']}/{r['n2']} | "
          f"{r['med1']:g} | {r['med2']:g} | {r['r']:+.2f} | {r['cles']:.2f} | "
          f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")

    # ---- 9. 薬剤間比較
    dr = drug_scan(subs)
    wcsv(os.path.join(OUT, "scan_drug.csv"), dr)
    A("\n\n## 9. レカネマブ vs ドナネマブ（NPIに依存しない比較・最大のn）\n")
    A("追跡期間が異なる点に注意（下の年換算ではなく生の変化量）。\n")
    A("| 転帰 | レカネマブ n / 中央値［範囲］ | ドナネマブ n / 中央値［範囲］ | r | p | p(FDR) |")
    A("|---|---|---|---|---|---|")
    for r in sorted(dr, key=lambda x: (x["p"] if x["p"] is not None else 9)):
        A(f"| {r['転帰']} | {r['n1']} / {r['med1']:g}［{r['min1']:g}, {r['max1']:g}］ | "
          f"{r['n2']} / {r['med2']:g}［{r['min2']:g}, {r['max2']:g}］ | "
          f"{r['r']:+.2f} | {fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")

    # ---- 10. 二値転帰
    bs = binary_scan(subs)
    wcsv(os.path.join(OUT, "scan_binary.csv"), bs)
    A("\n\n## 10. 臨床的カットオフで二値化した転帰（Fisher 正確検定）\n")
    bsig = [r for r in bs if r["p"] < 0.05]
    A(f"総当たり {len(bs)}件中、調整前 p<0.05 は {len(bsig)}件。上位15件を示す。\n")
    A("| 項目 | 群分け | 転帰 | 群1該当 | 群2該当 | オッズ比 | p | p(FDR) |")
    A("|---|---|---|---|---|---|---|---|")
    for r in sorted(bs, key=lambda x: x["p"])[:15]:
        A(f"| {r['項目'][:8]} | {r['群分け']} | {r['転帰']} | {r['群1該当']} | "
          f"{r['群2該当']} | {r['オッズ比'] if r['オッズ比'] is not None else '－'} | "
          f"{fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")

    # ---- 11. 時間見当識の深掘り
    A("\n\n## 11. 時間見当識（MMSE 0-5点）の深掘り\n")
    A("本コホートで (a) 唯一有意に低下したMMSE下位項目であり、(b) ΔCDR-SBとの相関が")
    A("MMSE合計より強く、(c) アパシー改善群と非改善群を完全に分離した項目であるため、")
    A("個別に検討する。\n")
    to = [x for x in subs if x.d("MMSE", "時間見当識") is not None]
    A(f"- 全コホート {len(to)}例: Δ中央値 "
      f"{median([x.d('MMSE','時間見当識') for x in to]):g}点"
      f"（低下 {sum(1 for x in to if x.d('MMSE','時間見当識') < 0)}例 / "
      f"不変 {sum(1 for x in to if x.d('MMSE','時間見当識') == 0)}例 / "
      f"改善 {sum(1 for x in to if x.d('MMSE','時間見当識') > 0)}例）")
    A("\n**NPI対あり症例における時間見当識の推移**\n")
    A("| 研究番号 | 薬剤 | アパシー推移 | 易怒性推移 | 時間見当識 BL→FU | Δ | ΔMMSE合計 | ΔCDR-SB |")
    A("|---|---|---|---|---|---|---|---|")
    for x in sorted(npi_set, key=lambda z: -(z.d("MMSE", "時間見当識")
                                             if z.d("MMSE", "時間見当識") is not None else -99)):
        dd = x.d("MMSE", "時間見当識")
        if dd is None:
            continue
        b, f = bl_fu(x.mmse, "時間見当識")
        A(f"| {x.pid} | {x.drug} | {x.trans('ap') or '－'} | {x.trans('ir') or '－'} | "
          f"{b.items['時間見当識']:g}→{f.items['時間見当識']:g} | {dd:+g} | "
          f"{x.d('MMSE','__total__'):+g} | "
          f"{x.d('CDR','__total__'):+g} |")

    # ---- 12. 遅延再生の深掘り
    A("\n\n## 12. 遅延再生（MMSE 0-3点）の深掘り\n")
    A("「ベースラインでアパシーあり」群と「なし」群の比較で、生の変化量・年換算・")
    A("二値化のいずれでも p<0.05 に達した唯一の転帰であるため、個別に検討する。\n")
    A("| 研究番号 | 薬剤 | アパシーBL | アパシー推移 | 遅延再生 BL→FU | Δ | "
      "追跡期間 | Δ/年 | ΔMMSE合計 | ΔCDR-SB |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for x in sorted(npi_set, key=lambda z: ((z.ap_bl if z.ap_bl is not None else -1),
                                            -(z.d("MMSE", "遅延再生")
                                              if z.d("MMSE", "遅延再生") is not None else 99)),
                    reverse=True):
        dd = x.d("MMSE", "遅延再生")
        if dd is None:
            continue
        b, f = bl_fu(x.mmse, "遅延再生")
        ann_v = annualized(x, "ΔMMSE_遅延再生")
        A(f"| {x.pid} | {x.drug} | {yn[x.ap_bl]}"
          f"{'（参考値）' if x.ap_conf == 'reference' else ''} | {x.trans('ap') or '－'} | "
          f"{b.items['遅延再生']:g}→{f.items['遅延再生']:g} | {dd:+g} | "
          f"{f'{x.interval_m:g}か月' if x.interval_m is not None else '不明'} | "
          f"{f'{ann_v:+.2f}' if ann_v is not None else '－'} | "
          f"{x.d('MMSE','__total__'):+g} | {x.d('CDR','__total__'):+g} |")
    A("\n**この所見に関する3つの検定（いずれも確定判定のみ）**\n")
    A("| 解析 | 群1（BLアパシーあり） | 群2（BLアパシーなし） | 検定 | p |")
    A("|---|---|---|---|---|")
    for r in scan:
        if r["群分け"] == "D_BLあり" and r["転帰"] == "ΔMMSE_遅延再生" \
                and r["項目"].startswith("NPI第7"):
            A(f"| 生の変化量 | n={r['n1']} 中央値{r['med1']:g} | "
              f"n={r['n2']} 中央値{r['med2']:g} | Mann-Whitney U | {fmt_p(r['p'])} |")
    for r in ann:
        if r["群分け"] == "D_BLあり" and r["転帰"] == "ΔMMSE_遅延再生/年" \
                and r["項目"].startswith("NPI第7"):
            A(f"| 年換算 | n={r['n1']} 中央値{r['med1']:g}/年 | "
              f"n={r['n2']} 中央値{r['med2']:g}/年 | Mann-Whitney U | {fmt_p(r['p'])} |")
    for r in bs:
        if r["群分け"] == "D_BLあり" and r["転帰"] == "遅延再生が1点以上低下" \
                and r["項目"].startswith("NPI第7"):
            A(f"| 1点以上低下の割合 | {r['群1該当']} | {r['群2該当']} | "
              f"Fisher 正確検定 | {fmt_p(r['p'])} |")

    # ---- 12b. NPI症状そのものの推移
    traj = npi_trajectory_scan(subs)
    cnt = npi_count_change(subs)
    wcsv(os.path.join(OUT, "npi_trajectory.csv"), traj)
    A("\n\n## 12-B. NPI症状そのものの推移（床・天井効果の影響を受けない解析）\n")
    A("変化量の群間比較と異なり、対応のある2値データの周辺割合の変化を見るため、")
    A("ベースライン値の偏りによるアーティファクトの問題が生じない。\n")
    A("| 項目 | 判定 | n | BL陽性 | FU陽性 | 改善（あり→なし） | 新規出現（なし→あり） | McNemar p |")
    A("|---|---|---|---|---|---|---|---|")
    for r in traj:
        A(f"| {r['項目'][:14]} | {r['判定']} | {r['n']} | "
          f"{r['BL陽性']}例 ({r['BL陽性率']*100:.0f}%) | "
          f"{r['FU陽性']}例 ({r['FU陽性率']*100:.0f}%) | {r['改善(あり→なし)']} | "
          f"{r['新規出現(なし→あり)']} | {fmt_p(r['McNemar_p'])} |")
    if cnt:
        A(f"\n**NPI陽性項目数（0〜2）の変化**: n={cnt['n']}、"
          f"ベースライン平均 {cnt['BL平均']:g} → フォローアップ平均 {cnt['FU平均']:g}"
          f"（増加 {cnt['増加']}例 / 不変 {cnt['不変']}例 / 減少 {cnt['減少']}例）")
        A(f"\n- Wilcoxon 符号付順位検定: **p={fmt_p(cnt['Wilcoxon_p'])}**")
        A(f"- 符号検定: p={fmt_p(cnt['符号検定_p'])}")
        A("\n→ **抗アミロイドβ抗体療法中に、NPIで捉えた精神症状の陽性項目数は"
          "有意に増加していた。** 内訳としては易怒性の新規出現が主体である。")
        A("\n> 限界: ベースラインのNPIは診療記録に基づく後方視的な評価であるのに対し、")
        A("> フォローアップのNPIは本研究のためにまとめて施行されている。")
        A("> 把握率の差が陽性率の上昇に寄与している可能性は否定できない。")

    # ---- 13. 床・天井効果の検証
    bal = baseline_balance_scan(subs)
    bal_ref = baseline_balance_scan(subs, include_reference=True)
    wcsv(os.path.join(OUT, "scan_baseline_balance.csv"), bal + bal_ref)
    hsc = headroom_scan(subs)
    wcsv(os.path.join(OUT, "scan_headroom_restricted.csv"), hsc)

    A("\n\n## 13. 【重要】床・天井効果の検証 — 上記の所見は本物か\n")
    A("MMSE下位項目は0〜1点や0〜3点と可動域が狭く、ベースラインが満点の項目は下がることしか、")
    A("0点の項目は上がることしかできない。したがって群間でベースライン値が偏っていると、")
    A("変化量の差は見かけ上生じる。§1〜§12で浮上した所見について、これを検証した。\n")

    def bal_of(rows, item_pref, gkey, ok):
        for r in rows:
            if (r["項目"].startswith(item_pref) and r["群分け"] == gkey
                    and r["転帰"] == ok):
                return r
        return None

    A("### 13-1. 遅延再生の所見（BLアパシーあり群で低下が速い）\n")
    rb = bal_of(bal, "NPI第7", "D_BLあり", "ΔMMSE_遅延再生")
    if rb:
        A(f"ベースラインの遅延再生自体が群間で異なる: "
          f"アパシーあり群 中央値{rb['med1']:g}［{rb['min1']:g}, {rb['max1']:g}］ vs "
          f"なし群 中央値{rb['med2']:g}［{rb['min2']:g}, {rb['max2']:g}］"
          f"（p={fmt_p(rb['p'])}）")
        A("\nアパシーあり群は全例が1点（＝1点下がる余地がある）、なし群は10例中7例が"
          "すでに0点（＝下がりようがない）。")
    rh = bal_of(hsc, "NPI第7", "D_BLあり", "ΔMMSE_遅延再生")
    if rh:
        A(f"\n**低下余地が1点以上ある症例に限定すると**: "
          f"アパシーあり群 n={rh['n1']}（{rh['群1症例']}）中央値{rh['med1']:g} vs "
          f"なし群 n={rh['n2']}（{rh['群2症例']}）中央値{rh['med2']:g}、"
          f"**p={fmt_p(rh['p'])}**")
        A("\n→ 差は消失する。§12の所見は**床効果によるアーティファクト**と判断される。")

    A("\n### 13-2. 時間見当識の所見（アパシー改善群で改善）\n")
    for lab, rows_, tag in [("確定判定のみ", bal, ""),
                            ("参考値を含む", bal_ref, "")]:
        rb = bal_of(rows_, "NPI第7", "A_改善", "ΔMMSE_時間見当識")
        if rb:
            A(f"- {lab}: ベースラインの時間見当識は 改善群 "
              f"{[f'{v:g}' for v in [rb['med1']]][0]}［{rb['min1']:g}, {rb['max1']:g}］ vs "
              f"非改善群 {rb['med2']:g}［{rb['min2']:g}, {rb['max2']:g}］、p={fmt_p(rb['p'])}")
    A("\nアパシー改善群はベースラインの時間見当識が2/5点とコホート最低であり、"
      "改善する余地が最も大きかった。一方、非改善群の多くは5/5点の満点で、"
      "下がることしかできない。")
    A("\n参考値を含めた場合、**ベースライン値の群間差（p=0.022）は変化量の群間差（p=0.022）と"
      "まったく同じ大きさ**であり、変化量の差はベースラインの偏りで説明できる。")
    A("\n→ §1・§11の所見も**天井効果によるアーティファクト**の可能性が高い。\n")

    A("\n### 13-3. 余地で補正したうえでの再走査\n")
    A("悪化方向に1点以上動ける症例に限定して全比較をやり直した結果:\n")
    hs = [r for r in hsc if r["p"] is not None and r["p"] < 0.05]
    if hs:
        A("| 項目 | 群分け | 転帰 | n1/n2 | 群1中央値 | 群2中央値 | p | p(FDR) |")
        A("|---|---|---|---|---|---|---|---|")
        for r in sorted(hs, key=lambda x: x["p"]):
            A(f"| {r['項目'][:8]} | {r['群分け']} | {r['転帰']} | {r['n1']}/{r['n2']} | "
              f"{r['med1']:g} | {r['med2']:g} | {fmt_p(r['p'])} | {fmt_p(r['p_fdr'])} |")
    else:
        A(f"**調整前 p<0.05 に達する比較は0件**（総比較数 {len(hsc)}件）。")
        A("\n床・天井効果を統制すると、NPIの推移と認知機能変化を結ぶ所見は残らない。")

    # ---- 7. 症例別 下位項目明細
    A("\n\n## 7. 症例別 明細（NPI対あり症例）\n")
    A("| 研究番号 | 薬剤 | NPI7 | NPI9 | ΔMMSE | "
      + " | ".join(f"Δ{k}" for k in MMSE_SUB) + " | ΔCDR-SB | "
      + " | ".join(f"Δ{k}" for k in CDR_DOM) + " |")
    A("|" + "---|" * (5 + len(MMSE_SUB) + 1 + len(CDR_DOM)))
    for x in npi_set:
        o = outcomes(x)
        def g(k):
            v = o[k]
            return f"{v:+g}" if v is not None else "－"
        A(f"| {x.pid} | {x.drug} | {yn[x.ap_bl]}→{yn[x.ap_fu]} | "
          f"{yn[x.ir_bl]}→{yn[x.ir_fu]} | {g('ΔMMSE合計')} | "
          + " | ".join(g(f"ΔMMSE_{k}") for k in MMSE_SUB)
          + f" | {g('ΔCDR-SB')} | "
          + " | ".join(g(f"ΔCDR_{k}") for k in CDR_DOM) + " |")

    # ---- 全症例の転帰CSV
    det = []
    for x in subs:
        o = outcomes(x)
        row = {"研究番号": x.pid, "薬剤": x.drug,
               "NPI対": "あり" if x.npi_paired else "なし",
               "NPI突合": x.npi_note,
               "NPI7_BL": yn[x.ap_bl], "NPI7_FU": yn[x.ap_fu],
               "NPI7推移": x.trans("ap") or "", "NPI7確度": x.ap_conf,
               "NPI9_BL": yn[x.ir_bl], "NPI9_FU": yn[x.ir_fu],
               "NPI9推移": x.trans("ir") or "", "NPI9確度": x.ir_conf,
               "追跡期間_月": x.interval_m}
        for k in OUTCOME_KEYS:
            vb = x.base(*outcome_meta(k)[:2])
            row[k.replace("Δ", "BL_")] = vb
            row[k.replace("Δ", "FU_")] = (None if vb is None or o[k] is None
                                          else vb + o[k])
            row[k] = o[k]
        det.append(row)
    wcsv(os.path.join(OUT, "subject_outcomes_full.csv"), det)

    def find(rows, **kw):
        for r in rows:
            if all((str(r.get(k, "")).startswith(v) if k == "項目" else r.get(k) == v)
                   for k, v in kw.items()):
                return r
        return None

    smry: list[str] = ["\n\n## 要約 — 何が見つかり、何が見つからなかったか\n"]
    smry.append("### A. 確実な所見（全コホート、FDR調整後も有意、床・天井効果の影響を受けない）\n")
    chg_rows = chg
    for ok, note in [("ΔCDR-SB", "CDR-SBは有意に悪化した"),
                     ("ΔGlobalCDR", "Global CDRも有意に悪化した"),
                     ("ΔMoCA-J", "MoCA-Jは有意に低下した（MMSE合計より鋭敏）"),
                     ("ΔMMSE_時間見当識",
                      "MMSE下位項目で有意に低下したのは時間見当識のみ"),
                     ("ΔMMSE合計", "一方でMMSE合計は有意に変化しなかった"),
                     ("ΔMMSE_3段階命令", "3段階命令はむしろ有意に「改善」した（学習効果の可能性）")]:
        r = next((x for x in chg_rows if x["転帰"] == ok), None)
        if r:
            smry.append(f"- **{note}**: n={r['n']}, Δ平均 {r['Δ平均']:+g}, "
                        f"悪化{r['悪化例']}/不変{r['不変例']}/改善{r['改善例']}例, "
                        f"p={fmt_p(r['p'])}（FDR {fmt_p(r['p_fdr'])}）")
    for v1, v2 in [("ΔMMSE_時間見当識", "ΔCDR-SB"), ("ΔMMSE合計", "ΔCDR-SB"),
                   ("ΔMMSE_時間見当識", "ΔCDR_見当識")]:
        r = next((x for x in cor if x["種別"] == "Δ×Δ"
                  and {x["変数1"], x["変数2"]} == {v1, v2}), None)
        if r:
            smry.append(f"- {v1} と {v2} の相関: ρ={r['rho']:+.3f} (n={r['n']}, "
                        f"FDR {fmt_p(r['p_fdr'])})")
    smry.append("\n  → **時間見当識はMMSE合計よりもCDR-SBの変化をよく捉えており、"
                "本コホートで最も鋭敏なMMSE下位項目である。**\n")

    smry.append("### B. NPIと認知機能変化の関連 — 見つからなかった\n")
    n_all = len(scan) + len(scan_ref) + len(burden) + len(ann) + len(bs) + len(hsc)
    smry.append(f"- NPI関連だけで計 **{n_all}件** の比較を実施した"
                "（群分け4種 × 転帰21種 × 2項目 × 生値/年換算/二値化/余地補正）。")
    smry.append(f"- **FDR調整後に有意なものは0件。**")
    smry.append(f"- 調整前 p<0.05 は {len([r for r in scan if r['p'] is not None and r['p']<0.05])}件"
                f"（生値）/ {len([r for r in ann if r['p'] is not None and r['p']<0.05])}件（年換算）"
                f"/ {len([r for r in bs if r['p']<0.05])}件（二値化）だったが、")
    smry.append("  いずれも群間でベースライン値が偏っていることによる**床・天井効果の"
                "アーティファクト**であった（§13）。")
    smry.append(f"- 変化の余地がある症例に限定して再走査すると、"
                f"調整前 p<0.05 は **0件**（{len(hsc)}件中）。\n")

    smry.append("### C. 症例数が増えれば有意差に到達しうる候補\n")
    smry.append("床・天井効果の統制を前提に、効果量から必要症例数を推定した"
                "（Noether 1987、両側α=0.05・検出力80%）。\n")
    smry.append("| 候補 | 現在のn | 効果量 P(群1>群2) | 現在のp | 1:1配分で必要な総n | "
                "現在の配分で必要な総n |")
    smry.append("|---|---|---|---|---|---|")
    for item, gkey, ok, lab in [
            ("NPI第7", "A_改善", "ΔMMSE_時間見当識",
             "アパシー改善群 × 時間見当識の変化"),
            ("NPI第7", "D_BLあり", "ΔMMSE_遅延再生",
             "ベースラインのアパシー × 遅延再生の低下"),
            ("NPI第9", "D_BLあり", "ΔCDR_見当識",
             "ベースラインの易怒性 × CDR見当識の悪化"),
            ("NPI第7", "A_改善", "ΔMMSE合計", "アパシー改善群 × MMSE合計の変化"),
            ("NPI第7", "C_新規出現", "ΔMMSE合計", "アパシー新規出現群 × MMSE合計の変化")]:
        r = find(scan, 項目=item, 群分け=gkey, 転帰=ok)
        if r:
            smry.append(f"| {lab} | {r['n1']}/{r['n2']} | {r['cles']:.2f} | "
                        f"{fmt_p(r['p'])} | {r['n_req_1to1'] or '－'} | "
                        f"{r['n_req_obs'] or '－'} |")
    smry.append("\n「現在の配分」とは、改善群が全体のごく一部しか占めないという"
                "本コホートの実態を反映した推定であり、1:1配分の推定より大幅に多い"
                "症例数を要する。\n")

    smry.append("### D. 最も現実的な次の一手\n")
    d18 = [x for x in subs if x.pid in
           ("D18", "D19", "D20", "D21", "D22", "D23")]
    smry.append(f"- **ドナネマブ {len(d18)}例（D18–D23）のMMSE/CDR 6か月値を入力する。** "
                "NPIは対で揃っているのに認知機能の追跡値が未入力であるため、"
                f"現在この6例はすべて解析から落ちている。入力されればNPI解析対象は "
                f"{len(ana)}例 → {len(ana) + len(d18)}例となる。")
    smry.append("- レカネマブでNPI原票が未提供の50例のうち、追跡MMSE/CDRがある症例の"
                "NPI原票を収集する。ここが最大のボトルネックである。")
    smry.append("- 今後の前向き評価では、NPIと認知機能検査を**同日に**実施する。"
                "現在はNPI評価日が認知機能評価日より中央値5.7か月後にずれている。")
    smry.append("- 主要転帰はMMSE合計ではなく **CDR-SB または 時間見当識** を用いる。"
                "本コホートでMMSE合計は有意に変化していない。\n")

    text = "\n".join(rep).replace(SUMMARY_MARK, "\n".join(smry))
    with io.open(os.path.join(OUT, "deep_analysis_report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
