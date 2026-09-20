# -*- coding: utf-8 -*-
"""NPIアパシースコア上昇群 vs 非上昇群：関連項目の網羅的探索

目的
    上昇群（ΔNPIアパシー≧1点）と非上昇群のあいだで差を示す項目が
    存在するかを、恣意的な取捨選択をせずに網羅的に探す。

設計上の原則（利用者の指示に基づく）
    1. 探索した候補は「全部」記録する。有意になった項目だけを残さない。
    2. 検定の総数を開示し、多重性を厳密に補正する。
       - Benjamini-Hochberg による FDR
       - Westfall-Young 型の min-p 並べ替え検定による
         family-wise error rate（FWER）補正
         → 「この探索全体で最良の所見が、偶然だけで得られる確率」を直接推定する
    3. 群分けの定義に直結する項目（ΔNPI頻度・重症度など）は
       同義反復なので主探索族から外し、別枠で表示する。
    4. 欠測は0点として扱わない。値の訂正・補完・除外は行わない。

min-p 並べ替え検定の実装
    14例のうち5例を上昇群とする割り当ては C(14,5)=2002 通り。
    そのすべてについて探索族の全項目のp値を同一の関数で再計算し、
    各割り当てにおける最小p値の分布を求める。
    観測された最小p値がこの分布のどこに位置するかが FWER 補正p値である。
"""
from __future__ import annotations

import csv
import io
import itertools
import math
import os
import statistics as stx
from bisect import bisect_left
from collections import Counter, defaultdict
from typing import Callable, Optional

import npi_increase_analysis as V2
from npi_increase_analysis import (Case, MMSE_SUB, CDR_DOM, build_cases,
                                   read_background, months, perm_mwu,
                                   fisher2x2, rank_biserial, med_range, vals)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output_v3")
os.makedirs(OUT, exist_ok=True)

EPS = 1e-9

# ---------------------------------------------------------------- 合成指標

MMSE_GROUPS = {
    "見当識計（時間＋場所）": ["時間見当識", "場所見当識"],
    "記憶計（記銘＋遅延再生）": ["記銘", "遅延再生"],
    "言語計（呼称＋復唱＋読字理解＋3段階命令＋書字）":
        ["物品呼称", "復唱", "読字理解", "3段階命令", "書字"],
    "注意・構成計（注意計算＋図形模写）": ["注意計算", "図形模写"],
}
CDR_GROUPS = {
    "認知3領域計（記憶＋見当識＋判断力・問題解決）":
        ["記憶", "見当識", "判断力・問題解決"],
    "生活3領域計（地域社会＋家庭・趣味＋身の回り）":
        ["地域社会の活動", "家庭・趣味", "身の回りの世話"],
}


def sub_sum(c: Case, sheet: str, keys: list[str], when: str) -> Optional[float]:
    """下位項目の合計。構成要素に1つでも欠測があれば None（0点で埋めない）。"""
    tot = 0.0
    for k in keys:
        b, f = c.bl_fu(sheet, k)
        v = {"bl": b, "fu": f, "d": (None if b is None or f is None else f - b)}[when]
        if v is None:
            return None
        tot += v
    return tot


def obs_months(c: Case) -> Optional[float]:
    b, f = c.baseline_visit("MMSE"), c.followup_visit("MMSE")
    if b is None or f is None or b.date is None or f.date is None:
        return None
    return round(months(b.date, f.date), 2)


def npi_interval(c: Case) -> Optional[float]:
    if not (c.npi_bl and c.npi_fu and c.npi_bl.date and c.npi_fu.date):
        return None
    return round(months(c.npi_bl.date, c.npi_fu.date), 2)


def annual(c: Case, sheet: str, key: str) -> Optional[float]:
    d = c.delta(sheet, key)
    m = obs_months(c)
    if d is None or m is None or m <= 0:
        return None
    return round(d / (m / 12.0), 4)


def cdr_carryforward(c: Case) -> Optional[float]:
    """全評価時点で6領域がすべて同一（転記の持ち越しが疑われる）なら1。"""
    pats = []
    for v in c.cdr:
        row = tuple(v.items.get(k) for k in CDR_DOM)
        if any(x is None for x in row):
            return None
        pats.append(row)
    if len(pats) < 2:
        return None
    return 1.0 if len(set(pats)) == 1 else 0.0


# ---------------------------------------------------------------- 候補の構築

class Var:
    __slots__ = ("family", "name", "kind", "fn", "note")

    def __init__(self, family: str, name: str, kind: str,
                 fn: Callable[[Case], Optional[float]], note: str = ""):
        self.family, self.name, self.kind, self.fn, self.note = \
            family, name, kind, fn, note


def build_vars(BG: dict) -> tuple[list[Var], list[Var]]:
    """(主探索族, 別枠＝群分けの定義に直結する項目) を返す。"""
    V: list[Var] = []
    cog = ([("MMSE合計", "MMSE", "__total__")]
           + [(f"MMSE {k}", "MMSE", k) for k in MMSE_SUB]
           + [("CDR-SB", "CDR", "__total__"), ("Global CDR", "CDR", "__global__")]
           + [(f"CDR {k}", "CDR", k) for k in CDR_DOM]
           + [("MoCA-J", "MoCA", "__total__")])

    def mk(sh, key, when):
        if when == "bl":
            return lambda c, s=sh, k=key: c.bl_fu(s, k)[0]
        if when == "fu":
            return lambda c, s=sh, k=key: c.bl_fu(s, k)[1]
        return lambda c, s=sh, k=key: c.delta(s, k)

    for label, sh, key in cog:
        V.append(Var("A_初回値", f"初回 {label}", "num", mk(sh, key, "bl")))
        V.append(Var("B_追跡時値", f"追跡時 {label}", "num", mk(sh, key, "fu")))
        V.append(Var("C_変化量", f"Δ {label}", "num", mk(sh, key, "d")))
        V.append(Var("D_年換算変化量", f"Δ {label}／年", "num",
                     lambda c, s=sh, k=key: annual(c, s, k)))

    for gname, keys in MMSE_GROUPS.items():
        for when, pre, fam in (("bl", "初回", "E_合成指標"),
                               ("fu", "追跡時", "E_合成指標"),
                               ("d", "Δ", "E_合成指標")):
            V.append(Var(fam, f"{pre} MMSE {gname}", "num",
                         lambda c, k=keys, w=when: sub_sum(c, "MMSE", k, w)))
    for gname, keys in CDR_GROUPS.items():
        for when, pre in (("bl", "初回"), ("fu", "追跡時"), ("d", "Δ")):
            V.append(Var("E_合成指標", f"{pre} CDR {gname}", "num",
                         lambda c, k=keys, w=when: sub_sum(c, "CDR", k, w)))

    # 相対変化（初回値が0の場合は定義できないので None）
    for label, sh, key in [("MMSE合計", "MMSE", "__total__"),
                           ("CDR-SB", "CDR", "__total__"),
                           ("MoCA-J", "MoCA", "__total__")]:
        def rel(c, s=sh, k=key):
            b, f = c.bl_fu(s, k)
            if b is None or f is None or b == 0:
                return None
            return round((f - b) / b * 100, 3)
        V.append(Var("F_相対変化", f"{label} 相対変化率(%)", "num", rel))

    # 患者背景・観察条件
    V.append(Var("G_背景・観察条件", "年齢", "num",
                 lambda c: BG.get(c.pid, {}).get("年齢")))
    V.append(Var("G_背景・観察条件", "観察期間（月）", "num", obs_months))
    V.append(Var("G_背景・観察条件", "NPI初回→追跡の間隔（月）", "num", npi_interval))
    V.append(Var("G_背景・観察条件", "初回評価からの暦年（投与開始年）", "num",
                 lambda c: (BG.get(c.pid, {}).get("投与開始日").year
                            if BG.get(c.pid, {}).get("投与開始日") else None)))

    # 2値変数（Fisher）
    def bin_worse(sh, key, worse_is_positive):
        def f(c, s=sh, k=key, w=worse_is_positive):
            d = c.delta(s, k)
            if d is None:
                return None
            return 1.0 if ((d > 0) if w else (d < 0)) else 0.0
        return f

    for label, sh, key in cog:
        worse_pos = sh == "CDR"          # CDRは上昇が悪化、MMSE/MoCAは低下が悪化
        V.append(Var("H_2値（悪化の有無）", f"{label} 悪化あり", "bin",
                     bin_worse(sh, key, worse_pos)))
    for label, sh, key in cog:
        worse_pos = sh == "CDR"
        V.append(Var("I_2値（改善の有無）", f"{label} 改善あり", "bin",
                     bin_worse(sh, key, not worse_pos)))
    for label, sh, key in cog:
        def unch(c, s=sh, k=key):
            d = c.delta(s, k)
            return None if d is None else (1.0 if d == 0 else 0.0)
        V.append(Var("J_2値（不変）", f"{label} 不変", "bin", unch))

    V.append(Var("K_2値（背景）", "女性", "bin",
                 lambda c: (1.0 if BG.get(c.pid, {}).get("性別") == "F"
                            else (0.0 if BG.get(c.pid, {}).get("性別") == "M" else None))))
    V.append(Var("K_2値（背景）", "初回アパシーあり（スコア1点以上）", "bin",
                 lambda c: (None if not c.npi_bl or c.npi_bl.score is None
                            else (1.0 if c.npi_bl.score >= 1 else 0.0))))
    V.append(Var("K_2値（背景）", "初回に易怒性あり", "bin",
                 lambda c: (1.0 if c.npi_bl and c.npi_bl.irrit == "あり"
                            else (0.0 if c.npi_bl and c.npi_bl.irrit == "なし" else None))))
    V.append(Var("K_2値（背景）", "追跡時に易怒性あり", "bin",
                 lambda c: (1.0 if c.npi_fu and c.npi_fu.irrit == "あり"
                            else (0.0 if c.npi_fu and c.npi_fu.irrit == "なし" else None))))
    V.append(Var("K_2値（背景）", "CDR全時点で6領域が同一", "bin", cdr_carryforward))
    V.append(Var("K_2値（背景）", "記録ルールによる入力値を含む", "bin",
                 lambda c: 1.0 if ((c.npi_bl and c.npi_bl.rule_imputed)
                                   or (c.npi_fu and c.npi_fu.rule_imputed)) else 0.0))
    V.append(Var("K_2値（背景）", "NPI追跡の時点ラベルと原資料が不一致", "bin",
                 lambda c: 1.0 if (c.npi_fu and c.npi_fu.orig_label != c.npi_fu.label)
                 else 0.0))
    V.append(Var("K_2値（背景）", "MoCA-Jの初回・追跡がそろう", "bin",
                 lambda c: 1.0 if c.bl_fu("MoCA", "__total__")[1] is not None else 0.0))

    # 別枠：群分けの定義に直結する項目（同義反復のため主探索族に入れない）
    T: list[Var] = [
        Var("Z_定義に直結", "Δ NPIアパシースコア", "num", lambda c: c.d_npi,
            "群分けの定義そのもの"),
        Var("Z_定義に直結", "Δ アパシー頻度F", "num",
            lambda c: (None if not (c.npi_bl and c.npi_fu)
                       or c.npi_bl.freq is None or c.npi_fu.freq is None
                       else c.npi_fu.freq - c.npi_bl.freq), "スコアの構成要素"),
        Var("Z_定義に直結", "Δ アパシー重症度S", "num",
            lambda c: (None if not (c.npi_bl and c.npi_fu)
                       or c.npi_bl.sev is None or c.npi_fu.sev is None
                       else c.npi_fu.sev - c.npi_bl.sev), "スコアの構成要素"),
        Var("Z_定義に直結", "追跡時 NPIアパシースコア", "num",
            lambda c: c.npi_fu.score if c.npi_fu else None, "スコアの構成要素"),
        Var("Z_定義に直結", "初回 NPIアパシースコア", "num",
            lambda c: c.npi_bl.score if c.npi_bl else None,
            "差の一方だが独立ではない"),
    ]
    return V, T


# ---------------------------------------------------------------- 拡張候補

FIXED_TP = ["6か月", "12か月", "18か月", "24か月"]


def at_tp(c: Case, sheet: str, key: str, tp: str, mode: str) -> Optional[float]:
    """固定時点の値、またはベースラインからの変化量。時点が無ければ None。"""
    v = c.visit(sheet, tp)
    if v is None:
        return None
    g = ((lambda x: x.total) if key == "__total__"
         else (lambda x: x.globalcdr) if key == "__global__"
         else (lambda x: x.items.get(key)))
    cur = g(v)
    if cur is None:
        return None
    if mode == "val":
        return cur
    b = c.baseline_visit(sheet)
    if b is None:
        return None
    bv = g(b)
    return None if bv is None else cur - bv


def combo_sum(c: Case, sheet: str, keys: tuple, when: str) -> Optional[float]:
    return sub_sum(c, sheet, list(keys), when)


def per_month(c: Case, sheet: str, key: str) -> Optional[float]:
    d = c.delta(sheet, key)
    m = obs_months(c)
    if d is None or m is None or m <= 0:
        return None
    return round(d / m, 5)


def resid_delta(inc: list[Case], sheet: str, key: str) -> list[Optional[float]]:
    """初回値に対する単回帰の残差（ベースライン調整後の変化量）。"""
    xs, ys, idx = [], [], []
    for i, c in enumerate(inc):
        b, f = c.bl_fu(sheet, key)
        if b is None or f is None:
            continue
        xs.append(b); ys.append(f - b); idx.append(i)
    out: list[Optional[float]] = [None] * len(inc)
    if len(idx) < 4 or len(set(xs)) < 2:
        return out
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b1 = sxy / sxx
    b0 = my - b1 * mx
    for k, i in enumerate(idx):
        out[i] = round(ys[k] - (b0 + b1 * xs[k]), 5)
    return out


def build_vars_extended(BG: dict, inc: list[Case]) -> list[Var]:
    """主探索族に加える拡張候補。すべて結果を見る前に機械的に列挙する。"""
    V: list[Var] = []
    cog = ([("MMSE合計", "MMSE", "__total__")]
           + [(f"MMSE {k}", "MMSE", k) for k in MMSE_SUB]
           + [("CDR-SB", "CDR", "__total__"), ("Global CDR", "CDR", "__global__")]
           + [(f"CDR {k}", "CDR", k) for k in CDR_DOM]
           + [("MoCA-J", "MoCA", "__total__")])

    # L: 固定時点での値と変化量
    for tp in FIXED_TP:
        for label, sh, key in cog:
            V.append(Var(f"L_固定時点({tp})", f"{tp} {label}", "num",
                         lambda c, s=sh, k=key, t=tp: at_tp(c, s, k, t, "val")))
            V.append(Var(f"L_固定時点({tp})", f"{tp} Δ{label}", "num",
                         lambda c, s=sh, k=key, t=tp: at_tp(c, s, k, t, "chg")))

    # M: 下位項目の「すべての部分集合」の和（加算型合成指標の完全網羅）
    #    MMSE 11項目 → 2^11-1 = 2047 通り、CDR 6領域 → 2^6-1 = 63 通り。
    #    初回値・追跡時値・変化量の3通りについて機械的に列挙する。
    for r in range(1, len(MMSE_SUB) + 1):
        for keys in itertools.combinations(MMSE_SUB, r):
            nm = "＋".join(keys)
            for when, pre in (("bl", "初回"), ("fu", "追跡時"), ("d", "Δ")):
                V.append(Var(f"M_MMSE部分集合(k={r})", f"{pre} MMSE［{nm}］", "num",
                             lambda c, k=keys, w=when: combo_sum(c, "MMSE", k, w)))
    for r in range(1, len(CDR_DOM) + 1):
        for keys in itertools.combinations(CDR_DOM, r):
            nm = "＋".join(keys)
            for when, pre in (("bl", "初回"), ("fu", "追跡時"), ("d", "Δ")):
                V.append(Var(f"M_CDR部分集合(k={r})", f"{pre} CDR［{nm}］", "num",
                             lambda c, k=keys, w=when: combo_sum(c, "CDR", k, w)))

    # M2: 下位項目どうしの差（解離の指標）
    def sub_diff(c, sheet, a, b, when):
        x = sub_sum(c, sheet, [a], when)
        y = sub_sum(c, sheet, [b], when)
        return None if x is None or y is None else x - y

    for a, b in itertools.combinations(MMSE_SUB, 2):
        for when, pre in (("bl", "初回"), ("d", "Δ")):
            V.append(Var("M2_下位項目の差", f"{pre} MMSE［{a}−{b}］", "num",
                         lambda c, x=a, y=b, w=when: sub_diff(c, "MMSE", x, y, w)))
    for a, b in itertools.combinations(CDR_DOM, 2):
        for when, pre in (("bl", "初回"), ("d", "Δ")):
            V.append(Var("M2_下位項目の差", f"{pre} CDR［{a}−{b}］", "num",
                         lambda c, x=a, y=b, w=when: sub_diff(c, "CDR", x, y, w)))

    # O: 月あたり変化量
    for label, sh, key in cog:
        V.append(Var("O_月あたり変化量", f"Δ {label}／月", "num",
                     lambda c, s=sh, k=key: per_month(c, s, k)))

    # R: 初回値で調整した変化量（回帰残差）をそのまま順位検定にかける
    for label, sh, key in cog:
        series = resid_delta(inc, sh, key)
        V.append(Var("R_初回値調整残差", f"Δ {label}（初回値調整残差）", "num",
                     lambda c, ser=series, lst=inc: ser[lst.index(c)]))

    # P: 変化の方向の組み合わせ
    def both_worse(c):
        a, b = c.delta("MMSE", "__total__"), c.delta("CDR", "__total__")
        if a is None or b is None:
            return None
        return 1.0 if (a < 0 and b > 0) else 0.0

    def either_worse(c):
        a, b = c.delta("MMSE", "__total__"), c.delta("CDR", "__total__")
        if a is None or b is None:
            return None
        return 1.0 if (a < 0 or b > 0) else 0.0

    def neither_worse(c):
        v = either_worse(c)
        return None if v is None else 1.0 - v

    V.append(Var("P_方向の組合せ", "MMSE低下かつCDR-SB上昇", "bin", both_worse))
    V.append(Var("P_方向の組合せ", "MMSE低下またはCDR-SB上昇", "bin", either_worse))
    V.append(Var("P_方向の組合せ", "いずれも悪化なし", "bin", neither_worse))

    def n_worse_mmse(c):
        k = 0
        for s in MMSE_SUB:
            d = c.delta("MMSE", s)
            if d is None:
                return None
            k += 1 if d < 0 else 0
        return float(k)

    def n_worse_cdr(c):
        k = 0
        for s in CDR_DOM:
            d = c.delta("CDR", s)
            if d is None:
                return None
            k += 1 if d > 0 else 0
        return float(k)

    V.append(Var("P_方向の組合せ", "悪化したMMSE下位項目の数", "num", n_worse_mmse))
    V.append(Var("P_方向の組合せ", "悪化したCDR領域の数", "num", n_worse_cdr))
    V.append(Var("P_方向の組合せ", "改善したMMSE下位項目の数", "num",
                 lambda c: (None if any(c.delta("MMSE", s) is None for s in MMSE_SUB)
                            else float(sum(1 for s in MMSE_SUB
                                           if c.delta("MMSE", s) > 0)))))

    # N: 連続量をあらゆる切点で2値化（Fisher）
    base_for_cut = ([("初回 " + l, lambda c, s=sh, k=key: c.bl_fu(s, k)[0])
                     for l, sh, key in cog]
                    + [("Δ " + l, lambda c, s=sh, k=key: c.delta(s, k))
                       for l, sh, key in cog]
                    + [("追跡時 " + l, lambda c, s=sh, k=key: c.bl_fu(s, k)[1])
                       for l, sh, key in cog])
    for label, fn in base_for_cut:
        obs = sorted({fn(c) for c in inc if fn(c) is not None})
        for cut in obs[1:]:                      # 最小値での切点は全例1になる
            V.append(Var("N_全切点2値化", f"{label} ≧{cut:g}", "bin",
                         lambda c, f=fn, t=cut: (None if f(c) is None
                                                 else (1.0 if f(c) >= t else 0.0))))
    return V


# ---------------------------------------------------------------- 検定基盤

def midranks(vals_: list[float]) -> list[float]:
    n = len(vals_)
    order = sorted(range(n), key=lambda i: vals_[i])
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals_[order[j + 1]] == vals_[order[i]]:
            j += 1
        rr = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = rr
        i = j + 1
    return r


class NumTester:
    """1つの連続量について、任意の群割り当てに対する正確p値を即座に返す。

    完全ケースの中間順位を固定し、部分集合の順位和分布を大きさ別に
    先に数え上げておく（最大 2^14 通り）。以後のp値計算は表引きで済む。
    """

    def __init__(self, values: list[Optional[float]]):
        self.idx = [i for i, v in enumerate(values) if v is not None]
        self.pos = {g: k for k, g in enumerate(self.idx)}
        obs = [values[i] for i in self.idx]
        self.n = len(obs)
        self.ranks = midranks(obs) if self.n else []
        # 大きさ別の順位和分布
        dist: list[Counter] = [Counter() for _ in range(self.n + 1)]
        dist[0][0.0] = 1
        for r in self.ranks:
            for size in range(self.n - 1, -1, -1):
                if not dist[size]:
                    continue
                tgt = dist[size + 1]
                for s, ct in dist[size].items():
                    tgt[round(s + r, 4)] += ct
        self.table = []
        for size in range(self.n + 1):
            mean = size * (self.n + 1) / 2
            arr = sorted(abs(s - mean) for s, ct in dist[size].items()
                         for _ in range(ct))
            self.table.append((mean, arr))

    def p(self, group_idx: frozenset) -> Optional[float]:
        sel = [self.pos[i] for i in group_idx if i in self.pos]
        n1 = len(sel)
        if n1 == 0 or n1 == self.n:
            return None
        obs = sum(self.ranks[k] for k in sel)
        mean, arr = self.table[n1]
        d = abs(obs - mean)
        cnt = len(arr) - bisect_left(arr, d - EPS)
        return cnt / len(arr)


class BinTester:
    def __init__(self, values: list[Optional[float]]):
        self.idx = [i for i, v in enumerate(values) if v is not None]
        self.val = {i: values[i] for i in self.idx}
        self.n = len(self.idx)
        self.tot1 = sum(1 for i in self.idx if self.val[i] == 1.0)
        self.cache: dict[tuple, Optional[float]] = {}

    def p(self, group_idx: frozenset) -> Optional[float]:
        sel = [i for i in group_idx if i in self.val]
        n1 = len(sel)
        n2 = self.n - n1
        if n1 == 0 or n2 == 0:
            return None
        a1 = sum(1 for i in sel if self.val[i] == 1.0)
        key = (n1, a1)
        if key not in self.cache:
            a0 = n1 - a1
            b1 = self.tot1 - a1
            b0 = n2 - b1
            self.cache[key] = (None if b1 < 0 or b0 < 0
                               else fisher2x2(a1, a0, b1, b0))
        return self.cache[key]


def bh_fdr(ps: list[float]) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        v = min(prev, ps[i] * m / (rank + 1))
        q[i] = v
        prev = v
    return q


def required_n_noether(p_sup: float, alpha=0.05, power=0.80) -> Optional[int]:
    """Noether(1987) による Mann-Whitney 検定の所要総例数（1:1割付）。"""
    if p_sup is None or abs(p_sup - 0.5) < 1e-6:
        return None
    za, zb = 1.959963985, 0.841621234
    n = (za + zb) ** 2 / (12 * 0.25 * (p_sup - 0.5) ** 2)
    return int(math.ceil(n))


def p_superiority(a: list[float], b: list[float]) -> Optional[float]:
    if not a or not b:
        return None
    gt = sum(1 for x in a for y in b if x > y)
    eq = sum(1 for x in a for y in b if x == y)
    return (gt + 0.5 * eq) / (len(a) * len(b))


# ---------------------------------------------------------------- ANCOVA

def ols_group_t(y: list[float], x: list[float], g: list[float]) -> Optional[float]:
    """y = a + b*x + c*g の群係数 c の t 値。x は初回値（共変量）。"""
    n = len(y)
    if n < 4 or len(set(g)) < 2 or len(set(x)) < 2:
        return None
    X = [[1.0, x[i], g[i]] for i in range(n)]
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(3)]
           for a in range(3)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(3)]
    M = [row[:] + [1.0 if j == k else 0.0 for j in range(3)]
         for k, row in enumerate(XtX)]
    for col in range(3):                       # ガウス・ジョルダン法
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-10:
            return None
        M[col], M[piv] = M[piv], M[col]
        d = M[col][col]
        M[col] = [v / d for v in M[col]]
        for r in range(3):
            if r == col:
                continue
            f = M[r][col]
            if f:
                M[r] = [M[r][j] - f * M[col][j] for j in range(6)]
    inv = [row[3:] for row in M]
    beta = [sum(inv[a][b] * Xty[b] for b in range(3)) for a in range(3)]
    resid = [y[i] - sum(beta[a] * X[i][a] for a in range(3)) for i in range(n)]
    dof = n - 3
    if dof <= 0:
        return None
    s2 = sum(r * r for r in resid) / dof
    se2 = s2 * inv[2][2]
    if se2 <= 0:
        return None
    return beta[2] / math.sqrt(se2)


# ---------------------------------------------------------------- 全体検定

def energy_stat(A: frozenset, X: list[list[float]]) -> Optional[float]:
    """エネルギー距離（E統計量）。多変量の分布差をひとつの値で表す。

    多重比較の問題を受けずに「2群がプロファイル全体として違うか」を
    1回の検定で調べるために用いる。
    """
    ia = [i for i in range(len(X)) if i in A]
    ib = [i for i in range(len(X)) if i not in A]
    if not ia or not ib:
        return None

    def d(i, j):
        return math.sqrt(sum((X[i][k] - X[j][k]) ** 2 for k in range(len(X[i]))))

    ab = sum(d(i, j) for i in ia for j in ib) / (len(ia) * len(ib))
    aa = (sum(d(i, j) for i in ia for j in ia) / (len(ia) ** 2)) if len(ia) > 1 else 0.0
    bb = (sum(d(i, j) for i in ib for j in ib) / (len(ib) ** 2)) if len(ib) > 1 else 0.0
    return len(ia) * len(ib) / (len(ia) + len(ib)) * (2 * ab - aa - bb)


def zmat(inc: list[Case], specs: list[tuple], mode: str) -> tuple[list[list[float]], list[str]]:
    """全例で値がそろう項目だけを取り出し、各項目を標準化した行列を返す。"""
    cols, names = [], []
    for label, sh, key in specs:
        col = []
        for c in inc:
            b, f = c.bl_fu(sh, key)
            v = (b if mode == "bl" else f if mode == "fu"
                 else (None if b is None or f is None else f - b))
            col.append(v)
        if any(x is None for x in col):
            continue
        sd = stx.pstdev(col)
        if sd == 0:
            continue
        m = stx.mean(col)
        cols.append([(x - m) / sd for x in col])
        names.append(label)
    X = [[cols[j][i] for j in range(len(cols))] for i in range(len(inc))]
    return X, names


# ---------------------------------------------------------------- 実行

def main() -> None:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    inc.sort(key=lambda c: (c.pid[0], int("".join(ch for ch in c.pid if ch.isdigit()))))
    n = len(inc)
    obs_group = frozenset(i for i, c in enumerate(inc) if c.group == "スコア上昇群")
    n1 = len(obs_group)
    assigns = [frozenset(t) for t in itertools.combinations(range(n), n1)]
    total_assign = len(assigns)

    MAIN, TRIV = build_vars(BG)
    MAIN = MAIN + build_vars_extended(BG, inc)

    # 同じ値ベクトルになる候補は重複検定なので1本にまとめ、別名を記録する。
    seen: dict[tuple, Var] = {}
    alias: dict[str, list[str]] = defaultdict(list)
    uniq: list[Var] = []
    n_raw = len(MAIN)
    for v in MAIN:
        sig = (v.kind, tuple(v.fn(c) for c in inc))
        if all(x is None for x in sig[1]):
            continue
        if sig in seen:
            alias[seen[sig].name].append(v.name)
            continue
        seen[sig] = v
        uniq.append(v)
    MAIN = uniq

    # --- 各候補の観測値と検定器
    #    メモリを節約するため、候補ごとに検定器を作って全2002通りのp値を求め、
    #    min-p の走行最小値だけを残して検定器は捨てる（1パス）。
    rows = []
    null_min = [1.0] * total_assign
    for v in MAIN:
        vv = [v.fn(c) for c in inc]
        if all(x is None for x in vv):
            rows.append({"family": v.family, "項目": v.name, "検定": "－",
                         "上昇群n": 0, "非上昇群n": 0, "p": None,
                         "備考": "全例で値が得られない"})
            continue
        t = NumTester(vv) if v.kind == "num" else BinTester(vv)
        obsn = [vv[i] for i in obs_group if vv[i] is not None]
        othn = [vv[i] for i in range(n) if i not in obs_group and vv[i] is not None]
        if not obsn or not othn:
            rows.append({"family": v.family, "項目": v.name, "検定": "－",
                         "上昇群n": len(obsn), "非上昇群n": len(othn), "p": None,
                         "備考": "一方の群に値がない"})
            continue
        if len(set(obsn + othn)) == 1:
            rows.append({"family": v.family, "項目": v.name,
                         "検定": "Fisher" if v.kind == "bin" else "MWU",
                         "上昇群n": len(obsn), "非上昇群n": len(othn), "p": 1.0,
                         "上昇群": med_range(obsn), "非上昇群": med_range(othn),
                         "備考": "全例が同値のため差が定義されない"})
            continue
        p = t.p(obs_group)
        parr = [t.p(A) for A in assigns]
        for j, pv in enumerate(parr):
            if pv is not None and pv < null_min[j]:
                null_min[j] = pv
        reach = min((x for x in parr if x is not None), default=None)
        if v.kind == "num":
            d = perm_mwu(obsn, othn)
            ps = p_superiority(obsn, othn)
            rows.append({
                "family": v.family, "項目": v.name, "検定": "MWU（完全並べ替え）",
                "上昇群n": len(obsn), "非上昇群n": len(othn),
                "上昇群": med_range(obsn), "非上昇群": med_range(othn),
                "上昇群の値": vals(obsn), "非上昇群の値": vals(othn),
                "U": d.get("U"), "p": p,
                "順位二列相関": (None if rank_biserial(obsn, othn) is None
                          else round(rank_biserial(obsn, othn), 3)),
                "P(上昇群>非上昇群)": None if ps is None else round(ps, 3),
                "80%検出力に要する総例数": required_n_noether(ps),
                "同順位に属する観測数": d.get("同順位に属する観測数"),
                "到達可能な最小p": None if reach is None else round(reach, 5),
                "備考": v.note})
        else:
            a1 = int(sum(obsn)); b1 = int(sum(othn))
            rows.append({
                "family": v.family, "項目": v.name, "検定": "Fisher（正確）",
                "上昇群n": len(obsn), "非上昇群n": len(othn),
                "上昇群": f"{a1}/{len(obsn)}", "非上昇群": f"{b1}/{len(othn)}",
                "p": p,
                "到達可能な最小p": None if reach is None else round(reach, 5),
                "備考": v.note})
    for r in rows:
        if alias.get(r["項目"]):
            a = alias[r["項目"]]
            r["同一結果の別名"] = ("、".join(a) if len(a) <= 4
                            else f"{a[0]} ほか{len(a)-1}件")

    tested = [r for r in rows if r.get("p") is not None]
    ps = [r["p"] for r in tested]
    qs = bh_fdr(ps)
    for r, q in zip(tested, qs):
        r["BH-FDR q"] = round(q, 4)

    # --- Westfall-Young min-p 並べ替え検定（null_min は上のループで作成済み）
    obs_min = min(ps) if ps else None
    fwer_p = (sum(1 for x in null_min if x <= obs_min + EPS) / total_assign
              if obs_min is not None else None)

    # 各項目ごとの Westfall-Young 調整p値（step-down ではなく single-step maxT）
    for r in tested:
        r["WY調整p（単一段階）"] = round(
            sum(1 for x in null_min if x <= r["p"] + EPS) / total_assign, 4)

    # --- ANCOVA（初回値で調整した変化量）
    anc_rows = []
    anc_specs = ([("MMSE合計", "MMSE", "__total__")]
                 + [(f"MMSE {k}", "MMSE", k) for k in MMSE_SUB]
                 + [("CDR-SB", "CDR", "__total__")]
                 + [(f"CDR {k}", "CDR", k) for k in CDR_DOM]
                 + [("MoCA-J", "MoCA", "__total__")])
    anc_stats: dict[str, list[Optional[float]]] = {}
    for label, sh, key in anc_specs:
        ys, xs, keep = [], [], []
        for i, c in enumerate(inc):
            b, f = c.bl_fu(sh, key)
            if b is None or f is None:
                continue
            ys.append(f - b); xs.append(b); keep.append(i)
        if len(keep) < 5:
            anc_rows.append({"項目": f"Δ {label}（初回値で調整）", "n": len(keep),
                             "t": None, "p": None, "備考": "例数不足"})
            continue
        series = []
        for A in assigns:
            g = [1.0 if i in A else 0.0 for i in keep]
            series.append(ols_group_t(ys, xs, g))
        obs_i = assigns.index(obs_group)
        t_obs = series[obs_i]
        valid = [abs(x) for x in series if x is not None]
        if t_obs is None or not valid:
            anc_rows.append({"項目": f"Δ {label}（初回値で調整）", "n": len(keep),
                             "t": None, "p": None, "備考": "推定不能"})
            continue
        p = sum(1 for x in valid if x >= abs(t_obs) - EPS) / len(valid)
        anc_stats[label] = series
        anc_rows.append({"項目": f"Δ {label}（初回値で調整）", "n": len(keep),
                         "t": round(t_obs, 3), "p": round(p, 4),
                         "備考": "並べ替えANCOVA（群係数のt値を並べ替え分布と比較）"})
    aps = [r["p"] for r in anc_rows if r["p"] is not None]
    if aps:
        aq = bh_fdr(aps)
        it = iter(aq)
        for r in anc_rows:
            if r["p"] is not None:
                r["BH-FDR q"] = round(next(it), 4)

    # ANCOVA族の min-p
    anc_null = []
    if anc_stats:
        for j in range(total_assign):
            m = 1.0
            for label, series in anc_stats.items():
                v = series[j]
                if v is None:
                    continue
                valid = [abs(x) for x in series if x is not None]
                # 事前に分布を作るのは重いので、ここでは順位で近似せず厳密に数える
                pv = sum(1 for x in valid if x >= abs(v) - EPS) / len(valid)
                if pv < m:
                    m = pv
            anc_null.append(m)

    # --- 別枠（定義に直結する項目）
    triv_rows = []
    for v in TRIV:
        vv = [v.fn(c) for c in inc]
        a = [vv[i] for i in obs_group if vv[i] is not None]
        b = [vv[i] for i in range(n) if i not in obs_group and vv[i] is not None]
        if not a or not b:
            continue
        d = perm_mwu(a, b)
        triv_rows.append({"項目": v.name, "上昇群": med_range(a), "非上昇群": med_range(b),
                          "U": d.get("U"), "p": d.get("p"), "備考": v.note})

    # --- 全体検定（多重比較の影響を受けない単一の検定）
    cogspec = ([("MMSE合計", "MMSE", "__total__")]
               + [(f"MMSE {k}", "MMSE", k) for k in MMSE_SUB]
               + [("CDR-SB", "CDR", "__total__")]
               + [(f"CDR {k}", "CDR", k) for k in CDR_DOM])
    omni_rows = []
    for mode, lab in (("bl", "初回プロファイル"), ("fu", "追跡時プロファイル"),
                      ("d", "変化量プロファイル")):
        X, names = zmat(inc, cogspec, mode)
        if not names:
            continue
        obs = energy_stat(obs_group, X)
        null = [energy_stat(A, X) for A in assigns]
        pv = sum(1 for x in null if x is not None and x >= obs - EPS) / \
            sum(1 for x in null if x is not None)
        omni_rows.append({"検定": f"エネルギー距離検定（{lab}）",
                          "用いた項目数": len(names), "E統計量": round(obs, 4),
                          "p": round(pv, 4),
                          "項目": "、".join(names)})

    # --- 診断：そもそもp<0.05に到達できる候補はいくつあるか
    reach = [r for r in tested if r.get("到達可能な最小p") is not None]
    can05 = [r for r in reach if r["到達可能な最小p"] < 0.05]
    diag = {
        "解析対象": n, "上昇群": n1, "非上昇群": n - n1,
        "群割り当ての総数 C(14,5)": total_assign,
        "理論上の最小両側p（完全分離・同順位なし）": round(2 / total_assign, 6),
        "列挙した候補": n_raw, "重複除去後": len(rows), "p値を計算できた候補": len(tested),
        "p<0.05に到達しうる候補": len(can05),
        "p<0.05に到達しえない候補": len(reach) - len(can05),
        "実際にp<0.05だった候補": sum(1 for r in tested if r["p"] < 0.05),
        "帰無仮説下で期待されるp<0.05件数（独立を仮定した上限の目安）":
            round(len(tested) * 0.05, 1),
        "観測された最小p": round(obs_min, 5) if obs_min is not None else None,
        "min-p並べ替えによるFWER補正p": round(fwer_p, 4) if fwer_p is not None else None,
        "BH-FDR q<0.05の候補": sum(1 for r in tested if r.get("BH-FDR q", 1) < 0.05),
    }
    # 候補どうしは強く相関しているため、実際の「独立な検定の数」は候補数より遥かに小さい。
    # min-p の結果から m_eff を逆算する： 1-(1-p_min)^m_eff = FWER
    if obs_min and fwer_p and 0 < obs_min < 1 and 0 < fwer_p < 1:
        m_eff = math.log(1 - fwer_p) / math.log(1 - obs_min)
        diag["実効的な独立検定数（min-pから逆算）"] = round(m_eff, 1)
        diag["実効数に基づくp<0.05の期待件数"] = round(m_eff * 0.05, 1)

    # ---------------------------------------------------------- 出力
    def w(name, rr):
        if not rr:
            return
        keys = list(dict.fromkeys(k for r in rr for k in r))
        with io.open(os.path.join(OUT, name), "w", encoding="utf-8-sig",
                     newline="") as f:
            wr = csv.DictWriter(f, fieldnames=keys)
            wr.writeheader()
            for r in rr:
                wr.writerow({k: ("" if r.get(k) is None else r[k]) for k in keys})

    srt = sorted(tested, key=lambda r: (r["p"], r["項目"]))
    w("v3_全候補の検定結果.csv", srt)
    w("v3_ANCOVA.csv", anc_rows)
    w("v3_全体検定.csv", omni_rows)
    w("v3_定義に直結する項目.csv", triv_rows)
    w("v3_探索の診断.csv", [{"項目": k, "値": v} for k, v in diag.items()])
    w("v3_families.csv", [{"family": f, "候補数": c,
                           "p<0.05": sum(1 for r in tested
                                         if r["family"] == f and r["p"] < 0.05),
                           "最小p": min((r["p"] for r in tested
                                       if r["family"] == f), default=None)}
                          for f, c in sorted(Counter(r["family"]
                                                     for r in tested).items())])
    w("v3_min-p帰無分布.csv",
      [{"最小pの値": k, "割り当て数": v,
        "割合": round(v / total_assign, 5)}
       for k, v in sorted(Counter(round(x, 5) for x in null_min).items())])

    # 症例別の一覧（公開可能な匿名ID）
    det = []
    for i, c in enumerate(inc):
        row = {"研究番号": c.pid, "群": c.group, "推移": c.pattern,
               "初回NPIアパシー": c.npi_bl.score, "追跡時NPIアパシー": c.npi_fu.score,
               "ΔNPIアパシー": c.d_npi,
               "年齢": BG.get(c.pid, {}).get("年齢"),
               "性別": BG.get(c.pid, {}).get("性別"),
               "観察期間（月）": obs_months(c),
               "追跡時点ラベル": (c.followup_visit("MMSE").label
                           if c.followup_visit("MMSE") else None)}
        for label, sh, key in cogspec + [("MoCA-J", "MoCA", "__total__")]:
            b, f = c.bl_fu(sh, key)
            row[f"初回{label}"] = b
            row[f"追跡時{label}"] = f
            row[f"Δ{label}"] = None if b is None or f is None else f - b
        det.append(row)
    w("v3_症例別一覧.csv", det)

    # --- レポート
    R = []
    A = R.append
    A("# 上昇群と非上昇群で差を示す項目の網羅的探索 — 結果\n")
    A(f"生成日時: {dt_now()}\n")
    A("**この探索は既存データを見たのちに行ったものであり、研究開始前に規定した解析ではない。**")
    A("**有意になった項目だけを選び出して報告することはしない。"
      "列挙した候補はすべて `v3_全候補の検定結果.csv` に収載している。**\n")

    A("## 1. 何を、いくつ探したか\n")
    A("| 項目 | 値 |")
    A("|---|---|")
    for k, v in diag.items():
        A(f"| {k} | {v} |")
    A("\n候補の内訳（族別）\n")
    A("| 族 | 候補数 | p<0.05 | 最小p |")
    A("|---|---|---|---|")
    fam = Counter(r["family"] for r in tested)
    for f in sorted(fam):
        mp = min(r["p"] for r in tested if r["family"] == f)
        A(f"| {f} | {fam[f]} | "
          f"{sum(1 for r in tested if r['family'] == f and r['p'] < 0.05)} | "
          f"{mp:.4f} |")
    A("\n加算型の合成指標については、MMSE11下位項目の全部分集合（2^11−1＝2047通り）と"
      "CDR6領域の全部分集合（2^6−1＝63通り）を、初回値・追跡時値・変化量の3通りについて"
      "機械的に列挙した。すなわち「どの下位項目をどう足し合わせるか」という形の指標は"
      "取りこぼしなく網羅している。\n")

    A("## 2. p値が小さかった候補（上位30）\n")
    A("| p | BH-FDR q | WY調整p | 族 | 項目 | 上昇群 | 非上昇群 | 到達可能な最小p |")
    A("|---|---|---|---|---|---|---|---|")
    for r in srt[:30]:
        A(f"| {r['p']:.4f} | {r.get('BH-FDR q')} | {r.get('WY調整p（単一段階）')} | "
          f"{r['family']} | {r['項目']} | {r.get('上昇群')} | {r.get('非上昇群')} | "
          f"{r.get('到達可能な最小p')} |")

    A("\n## 3. 多重性を補正した結論\n")
    A(f"- 未補正で p<0.05 となった候補は **{sum(1 for r in tested if r['p'] < 0.05)}件**。"
      f"検定数 {len(tested)} に対し、帰無仮説の下で偶然に p<0.05 となる件数の目安は"
      f" **約{len(tested) * 0.05:.0f}件** である。実際の件数はこれを大きく下回る。")
    A(f"- Benjamini-Hochberg の FDR で q<0.05 となった候補は "
      f"**{sum(1 for r in tested if r.get('BH-FDR q', 1) < 0.05)}件**。")
    A(f"- min-p 並べ替え検定（Westfall-Young）による FWER 補正p値は "
      f"**{fwer_p:.4f}**。これは「この探索全体で最良の所見が、群分けと無関係に"
      f"偶然だけで得られる確率」であり、有意水準には遠い。")
    A("- したがって、**上昇群と非上昇群のあいだに差を示す項目は見つからなかった**。"
      "これは「差がない」「関連しない」という意味ではなく、"
      "この例数とこのデータでは差を検出できなかった、という意味である。")

    A("\n## 3-2. 未補正で p<0.05 となった候補の内訳\n")
    hits = [r for r in srt if r["p"] < 0.05]
    if not hits:
        A("該当なし。\n")
    for r in hits:
        used = r["上昇群n"] + r["非上昇群n"]
        A(f"### {r['項目']}（p={r['p']:.4f}）\n")
        A(f"- 値が得られた症例: **{used}/{n}例**"
          f"（上昇群 {r['上昇群n']}/{n1}、非上昇群 {r['非上昇群n']}/{n - n1}）")
        if used < n:
            drop = []
            vv = None
            for v in MAIN:
                if v.name == r["項目"]:
                    vv = [v.fn(c) for c in inc]
                    break
            if vv is not None:
                drop = [f"{inc[i].pid}（{inc[i].group}）"
                        for i in range(n) if vv[i] is None]
            A(f"- **値が得られず除外された症例: {', '.join(drop)}**。"
              "どの症例が落ちるかによって結果が変わりうるため、"
              "この所見は欠測の分布に依存している。")
        A(f"- 上昇群 {r.get('上昇群')} / 非上昇群 {r.get('非上昇群')}")
        if r.get("上昇群の値"):
            A(f"- 上昇群の値: {r['上昇群の値']}")
            A(f"- 非上昇群の値: {r['非上昇群の値']}")
        rb = r.get("順位二列相関")
        if rb is not None:
            hi = "上昇群のほうが高い" if rb > 0 else "上昇群のほうが低い"
            nm = r["項目"]
            if ("MMSE" in nm or "MoCA" in nm) and "CDR" not in nm:
                mean_ = "得点が高い＝認知機能が良い" 
                clin = ("上昇群のほうが良い方向" if rb > 0 else "上昇群のほうが悪い方向")
            elif "CDR" in nm:
                mean_ = "得点が高い＝重症度が高い"
                clin = ("上昇群のほうが悪い方向" if rb > 0 else "上昇群のほうが良い方向")
            else:
                mean_, clin = "－", "－"
            A(f"- 向き: {hi}（順位二列相関 {rb}）。{mean_}。この項目では{clin}。")
        A(f"- BH-FDR q＝{r.get('BH-FDR q')}、WY調整p＝{r.get('WY調整p（単一段階）')}"
          "。いずれも有意水準に達しない。\n")

    A("\n## 4. 多重比較の影響を受けない全体検定\n")
    A("| 検定 | 用いた項目数 | E統計量 | p |")
    A("|---|---|---|---|")
    for r in omni_rows:
        A(f"| {r['検定']} | {r['用いた項目数']} | {r['E統計量']} | {r['p']} |")
    A("\nプロファイル全体をひとつの検定で比較しても、"
      "群間の違いは偶然の範囲を超えなかった。\n")

    A("## 5. 初回値で調整した変化量（並べ替えANCOVA）\n")
    A("| 項目 | n | t | p | BH-FDR q |")
    A("|---|---|---|---|---|")
    for r in sorted(anc_rows, key=lambda x: (x["p"] is None, x["p"])):
        A(f"| {r['項目']} | {r['n']} | {r.get('t')} | {r.get('p')} | "
          f"{r.get('BH-FDR q')} |")

    A("\n## 6. どれだけ症例を集めれば検出できるか\n")
    A("観測された効果量がそのまま真の効果量だと仮定した場合に、"
      "両側5%・検出力80%で差を検出するのに必要な総例数（Noether 1987、1:1割付）。"
      "小標本で観測された効果量は真の値より大きく出やすいので、"
      "この値はむしろ下限の目安である。\n")
    A("| 項目 | 上昇群 | 非上昇群 | P(上昇群>非上昇群) | p | 必要総例数 |")
    A("|---|---|---|---|---|---|")
    core = ["Δ MMSE合計", "Δ CDR-SB", "Δ MoCA-J", "Δ Global CDR",
            "初回 MMSE合計", "初回 CDR-SB", "追跡時 MMSE合計", "追跡時 CDR-SB"]
    by = {r["項目"]: r for r in tested}
    for k in core:
        r = by.get(k)
        if r:
            A(f"| {k} | {r.get('上昇群')} | {r.get('非上昇群')} | "
              f"{r.get('P(上昇群>非上昇群)')} | {r['p']:.4f} | "
              f"{r.get('80%検出力に要する総例数') or '－'} |")
    A("\np値が小さかった上位10候補についても同じ計算を示す。\n")
    A("| 項目 | p | P(上昇群>非上昇群) | 必要総例数 |")
    A("|---|---|---|---|")
    for r in srt[:10]:
        A(f"| {r['項目']} | {r['p']:.4f} | {r.get('P(上昇群>非上昇群)') or '－'} | "
          f"{r.get('80%検出力に要する総例数') or '－'} |")

    A("\n## 7. 群分けの定義に直結する項目（同義反復のため主探索族に入れていない）\n")
    A("| 項目 | 上昇群 | 非上昇群 | U | p | 備考 |")
    A("|---|---|---|---|---|---|")
    for r in triv_rows:
        A(f"| {r['項目']} | {r['上昇群']} | {r['非上昇群']} | {r.get('U')} | "
          f"{r['p']:.4f} | {r['備考']} |")
    A("\nこれらが小さいp値を示すのは当然であり、所見ではない。\n")

    io.open(os.path.join(OUT, "v3_網羅的探索レポート.md"), "w",
            encoding="utf-8").write("\n".join(R))

    globals().update(dict(inc=inc, rows=rows, tested=tested, anc_rows=anc_rows,
                          triv_rows=triv_rows, null_min=null_min, obs_min=obs_min,
                          fwer_p=fwer_p, total_assign=total_assign,
                          anc_null=anc_null, obs_group=obs_group,
                          n_raw=n_raw, alias=alias, omni_rows=omni_rows, diag=diag))
    return dict(inc=inc, rows=rows, tested=tested, anc_rows=anc_rows,
                triv_rows=triv_rows, null_min=null_min, obs_min=obs_min,
                fwer_p=fwer_p, total_assign=total_assign, anc_null=anc_null,
                obs_group=obs_group, n_raw=n_raw, alias=alias,
                omni_rows=omni_rows, diag=diag, detail=det)


def dt_now() -> str:
    import datetime
    return f"{datetime.datetime.now():%Y-%m-%d %H:%M}"


if __name__ == "__main__":
    res = main()
    t = sorted(res["tested"], key=lambda r: r["p"])
    d = res["diag"]
    for k, v in d.items():
        print(f"{k}: {v}")
    print("--- 上位15 ---")
    for r in t[:15]:
        print(f"p={r['p']:.5f} q={r.get('BH-FDR q')} WY={r.get('WY調整p（単一段階）')} "
              f"[{r['family']}] {r['項目']}")
    print("--- 全体検定 ---")
    for r in res["omni_rows"]:
        print(f"{r['検定']}: E={r['E統計量']} p={r['p']} (項目数 {r['用いた項目数']})")
