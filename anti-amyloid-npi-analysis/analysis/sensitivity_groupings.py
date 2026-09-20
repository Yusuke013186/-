# -*- coding: utf-8 -*-
"""群分けの切り方を変えても差を示す項目が現れるかを確認する感度解析。

主解析（ΔNPIアパシー≧1点で上昇群）以外の切り方も機械的に試す。
切り方を変えること自体が多重性であるため、各切り方について
min-p 並べ替え検定（Westfall-Young）の FWER 補正p値を併記する。
「どの切り方なら有意になるか」を選ぶための道具ではない。
"""
from __future__ import annotations

import io
import itertools
import math
import os
from collections import Counter, defaultdict
from typing import Callable, Optional

import exhaustive_search as X
from npi_increase_analysis import build_cases, read_background

EPS = X.EPS


# どの切り方もNPIアパシーの得点から定義されるため、得点そのものに由来する候補は
# 同義反復になる。全ての切り方で一律に除外する。
DEF_DERIVED = {"初回アパシーあり（スコア1点以上）"}


def run(inc, sel: set[int], MAIN) -> dict:
    n = len(inc)
    n1 = len(sel)
    if n1 == 0 or n1 == n:
        return {}
    assigns = [frozenset(t) for t in itertools.combinations(range(n), n1)]
    obs_group = frozenset(sel)
    null_min = [1.0] * len(assigns)
    ps, reach05 = [], 0
    for v in MAIN:
        if v.name in DEF_DERIVED:
            continue
        vv = [v.fn(c) for c in inc]
        if all(x is None for x in vv):
            continue
        a = [vv[i] for i in obs_group if vv[i] is not None]
        b = [vv[i] for i in range(n) if i not in obs_group and vv[i] is not None]
        if not a or not b or len(set(a + b)) == 1:
            continue
        t = X.NumTester(vv) if v.kind == "num" else X.BinTester(vv)
        p = t.p(obs_group)
        if p is None:
            continue
        parr = [t.p(A) for A in assigns]
        for j, pv in enumerate(parr):
            if pv is not None and pv < null_min[j]:
                null_min[j] = pv
        mn = min((x for x in parr if x is not None), default=None)
        if mn is not None and mn < 0.05:
            reach05 += 1
        ps.append(p)
    if not ps:
        return {}
    obs_min = min(ps)
    fwer = sum(1 for x in null_min if x <= obs_min + EPS) / len(assigns)
    qs = X.bh_fdr(ps)
    return {"上昇群n": n1, "対照群n": n - n1, "割り当て総数": len(assigns),
            "理論上の最小p": round(2 / len(assigns), 5),
            "検定した候補": len(ps), "p<0.05に到達しうる候補": reach05,
            "p<0.05だった候補": sum(1 for p in ps if p < 0.05),
            "最小p": round(obs_min, 5),
            "BH-FDR q<0.05": sum(1 for q in qs if q < 0.05),
            "FWER補正p（min-p並べ替え）": round(fwer, 4)}


def main() -> None:
    cases, _ = build_cases()
    BG = read_background()
    inc = [c for c in cases if c.step == "S5_解析対象"]
    inc.sort(key=lambda c: (c.pid[0],
                            int("".join(ch for ch in c.pid if ch.isdigit()))))
    MAIN, _ = X.build_vars(BG)
    MAIN = MAIN + X.build_vars_extended(BG, inc)
    seen, uniq = set(), []
    for v in MAIN:
        sig = (v.kind, tuple(v.fn(c) for c in inc))
        if all(x is None for x in sig[1]) or sig in seen:
            continue
        seen.add(sig)
        uniq.append(v)
    MAIN = uniq

    defs: list[tuple[str, Callable, Optional[Callable]]] = [
        ("主解析：ΔNPIアパシー≧1点（上昇）vs ≦0点",
         lambda c: c.d_npi >= 1, None),
        ("ΔNPIアパシー≧2点 vs ≦1点", lambda c: c.d_npi >= 2, None),
        ("ΔNPIアパシー≧3点 vs ≦2点", lambda c: c.d_npi >= 3, None),
        ("ΔNPIアパシー>0 vs <0（不変例を除外）",
         lambda c: c.d_npi > 0, lambda c: c.d_npi != 0),
        ("追跡時スコア≧1点 vs 0点", lambda c: c.npi_fu.score >= 1, None),
        ("追跡時スコア≧2点 vs ≦1点", lambda c: c.npi_fu.score >= 2, None),
        ("初回スコア≧1点 vs 0点", lambda c: c.npi_bl.score >= 1, None),
        ("頻度Fが上昇 vs 非上昇",
         lambda c: (c.npi_fu.freq or 0) - (c.npi_bl.freq or 0) >= 1, None),
        ("重症度Sが上昇 vs 非上昇",
         lambda c: (c.npi_fu.sev or 0) - (c.npi_bl.sev or 0) >= 1, None),
    ]

    rows = []
    for label, pred, keep in defs:
        sub = [c for c in inc if (keep(c) if keep else True)]
        if len(sub) < 4:
            rows.append({"群分けの定義": label, "備考": "例数が足りない"})
            continue
        sel = {i for i, c in enumerate(sub) if pred(c)}
        # 部分集合を使う場合は候補を作り直す
        if len(sub) != len(inc):
            M2, _ = X.build_vars(BG)
            M2 = M2 + X.build_vars_extended(BG, sub)
            s2, u2 = set(), []
            for v in M2:
                sig = (v.kind, tuple(v.fn(c) for c in sub))
                if all(x is None for x in sig[1]) or sig in s2:
                    continue
                s2.add(sig)
                u2.append(v)
            r = run(sub, sel, u2)
        else:
            r = run(sub, sel, MAIN)
        if not r:
            rows.append({"群分けの定義": label, "備考": "一方の群が0例で比較できない"})
            continue
        r["群分けの定義"] = label
        r["対象例数"] = len(sub)
        r["研究番号（上昇側）"] = ",".join(sub[i].pid for i in sorted(sel))
        rows.append(r)

    keys = ["群分けの定義", "対象例数", "上昇群n", "対照群n", "割り当て総数",
            "理論上の最小p", "検定した候補", "p<0.05に到達しうる候補",
            "p<0.05だった候補", "最小p", "BH-FDR q<0.05",
            "FWER補正p（min-p並べ替え）", "研究番号（上昇側）", "備考"]
    import csv
    with io.open(os.path.join(X.OUT, "v3_群分けの感度解析.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in keys})
    for r in rows:
        print(f"{r['群分けの定義']}: n={r.get('対象例数')} "
              f"{r.get('上昇群n')}vs{r.get('対照群n')} 候補={r.get('検定した候補')} "
              f"最小p={r.get('最小p')} FWER={r.get('FWER補正p（min-p並べ替え）')} "
              f"到達可能={r.get('p<0.05に到達しうる候補')} {r.get('備考','')}")


if __name__ == "__main__":
    main()
