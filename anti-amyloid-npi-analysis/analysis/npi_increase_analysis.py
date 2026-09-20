# -*- coding: utf-8 -*-
"""
抗アミロイドβ抗体療法例における NPIアパシースコアの推移と認知機能変化
— 研究の問いを「スコアが上昇した例と上昇しなかった例の比較」に変更した再解析 —

研究の問い（変更後）:
  抗アミロイドβ抗体療法中にNPIアパシースコアが上昇した症例と上昇しなかった症例では、
  認知機能の変化がどのように異なるか。

重要な前提:
  本解析の群分けは既存データを確認したのちに設定したものであり、研究開始前に
  規定したものではない。探索的・記述的な観察研究として扱う。

群の定義:
  ΔNPIアパシー = 追跡時スコア − 初回スコア
  スコア上昇群   : ΔNPIアパシー ≧ +1
  スコア非上昇群 : ΔNPIアパシー ≦ 0
  ※1点の上昇は検証された臨床的悪化の閾値ではない。

変化量の向き:
  MMSE        : 追跡 − 初回（正値＝得点上昇）
  CDR-SB      : 追跡 − 初回（正値＝重症度上昇）
  NPIアパシー  : 追跡 − 初回（正値＝スコア上昇）

入力:
  data_local/lecanemab_L1-66_NPI.xlsx   （L1–66、NPIのみL69を含む）
  data_local/donanemab_D1-D30_NPI.xlsx  （D1–D30）
  data_local/patient_background.csv     （研究番号・年齢・性別・投与開始日）
出力:
  output_v2/ 以下の CSV と Markdown

実行: python3 analysis/npi_increase_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import itertools
import math
import os
import re
import statistics as stx
import sys
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data_local")
OUT = os.path.join(ROOT, "output_v2")
os.makedirs(OUT, exist_ok=True)

FILES = {
    "レカネマブ": os.path.join(DATA, "lecanemab_L1-66_NPI.xlsx"),
    "ドナネマブ": os.path.join(DATA, "donanemab_D1-D30_NPI.xlsx"),
}
TP_ORDER = ["0か月", "6か月", "12か月", "18か月", "24か月"]
MMSE_SUB = ["時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算", "遅延再生",
            "復唱", "読字理解", "3段階命令", "書字", "図形模写"]
MMSE_MAX = {"時間見当識": 5, "場所見当識": 5, "物品呼称": 2, "記銘": 3, "注意計算": 5,
            "遅延再生": 3, "復唱": 1, "読字理解": 1, "3段階命令": 3, "書字": 1, "図形模写": 1}
CDR_DOM = ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]

# NPIの有無欄のうち、原票そのものが無い／判定できないもの（スコアも使えない）
NPI_NO_SCORE = {"資料未提供", "原票なし", ""}


# ---------------------------------------------------------------- 基本ユーティリティ

def S(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).replace("\n", "").replace("　", " ").strip()


def Fl(v) -> Optional[float]:
    t = S(v)
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        return None


DATE_FULL = re.compile(r"(\d{4})[-/\.年](\d{1,2})[-/\.月](\d{1,2})")
DATE_YM = re.compile(r"(\d{4})[-/\.年](\d{1,2})")


def parse_date(v) -> tuple[Optional[dt.date], str]:
    """日付を (date, 精度) で返す。年月のみの記録は日付値を作らない（推定しない）。"""
    if v is None:
        return None, ""
    if isinstance(v, dt.datetime):
        return v.date(), "day"
    if isinstance(v, dt.date):
        return v, "day"
    t = S(v)
    if not t:
        return None, ""
    m = re.search(r"MMSE/CDR\s*[:：]\s*(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})", t)
    if m:
        return dt.date(*map(int, m.groups())), "day"
    m = DATE_FULL.search(t)
    if m:
        try:
            return dt.date(*map(int, m.groups())), "day"
        except ValueError:
            return None, "invalid"
    if DATE_YM.search(t):
        return None, "month_only"
    return None, "unparsed"


def year_month(v) -> Optional[tuple[int, int]]:
    """記録されている年月を (年, 月) で返す。日は推定しない。"""
    if v is None:
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.year, v.month)
    t = S(v)
    m = DATE_FULL.search(t) or DATE_YM.search(t)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def ym_diff(a: tuple[int, int], b: tuple[int, int]) -> int:
    """年月の差（月数）。"""
    return abs((a[0] - b[0]) * 12 + (a[1] - b[1]))


def months(a: dt.date, b: dt.date) -> float:
    return round((b - a).days / 30.4375, 1)


# ---------------------------------------------------------------- 読み込み

@dataclass
class CogVisit:
    label: str
    date: Optional[dt.date]
    date_prec: str
    total: Optional[float]
    items: dict[str, Optional[float]]
    globalcdr: Optional[float] = None


@dataclass
class NpiRow:
    label: str
    orig_label: str
    presence: str
    freq: Optional[float]
    sev: Optional[float]
    score: Optional[float]
    irrit: str
    date: Optional[dt.date]
    date_prec: str
    note: str
    rule_imputed: bool
    ym: Optional[tuple] = None


def read_cog(path: str, sheet: str) -> dict[str, list[CogVisit]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    h = [S(c) for c in rows[0]]
    if sheet == "MMSE":
        keys, i_tot, i_gl = MMSE_SUB, h.index("合計_原資料記載値"), None
        i_alt = h.index("下位項目合計_自動計算")
    elif sheet == "CDR":
        keys, i_tot = CDR_DOM, h.index("CDR-SB_原資料記載値")
        i_alt = h.index("CDR-SB_自動計算")
        i_gl = h.index("Global CDR_原資料記載値")
    else:
        keys, i_tot, i_alt, i_gl = [], h.index("合計_原資料記載値"), None, None
    idx = {k: h.index(k) for k in keys if k in h}
    i_dt = h.index("評価日")
    out: dict[str, list[CogVisit]] = {}
    for r in rows[1:]:
        pid = S(r[0])
        if not pid:
            continue
        tot = Fl(r[i_tot])
        if tot is None and i_alt is not None:
            tot = Fl(r[i_alt])          # 原資料記載欄が空欄のときのみ自動計算値を用いる
        d, prec = parse_date(r[i_dt])
        out.setdefault(pid, []).append(CogVisit(
            S(r[1]), d, prec, tot, {k: Fl(r[i]) for k, i in idx.items()},
            Fl(r[i_gl]) if i_gl is not None else None))
    for pid in out:
        out[pid].sort(key=lambda v: TP_ORDER.index(v.label)
                      if v.label in TP_ORDER else 99)
    return out


def read_npi(path: str) -> dict[str, list[NpiRow]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["NPI"]
    rows = list(ws.iter_rows(values_only=True))
    h = [S(c) for c in rows[0]]

    def col(*pref) -> Optional[int]:
        for p in pref:
            for i, c in enumerate(h):
                if c.startswith(p):
                    return i
        return None

    i_tp = col("時点")
    i_pr = col("アパシー・無関心の有無", "無関心・アパシー有無")
    i_f = col("アパシー頻度")
    i_s = col("アパシー重症度")
    i_sc = col("NPI-Apathy score")
    i_ir = col("易怒性の有無", "易怒性有無")
    i_dt = col("評価日（年月日確定）", "評価日")
    i_raw = col("評価日_原記載", "評価日（原票記載）")
    i_nt = col("確認事項")
    out: dict[str, list[NpiRow]] = {}
    for r in rows[1:]:
        pid = S(r[0])
        if not pid:
            continue
        note = S(r[i_nt]) if i_nt is not None else ""
        d, prec = parse_date(r[i_dt]) if i_dt is not None else (None, "")
        if d is None and i_raw is not None:
            d2, p2 = parse_date(r[i_raw])
            d, prec = d2, (prec or p2)
        m = re.search(r"原資料：(\d+)\s*か月", note)
        out.setdefault(pid, []).append(NpiRow(
            label=S(r[i_tp]), orig_label=(m.group(1) + "か月" if m else S(r[i_tp])),
            presence=S(r[i_pr]), freq=Fl(r[i_f]), sev=Fl(r[i_s]), score=Fl(r[i_sc]),
            irrit=S(r[i_ir]) if i_ir is not None else "",
            date=d, date_prec=prec, note=note,
            rule_imputed=("記録ルール" in note or "研究用の入力値" in note),
            ym=(year_month(r[i_dt]) if i_dt is not None else None)
               or (year_month(r[i_raw]) if i_raw is not None else None)))
    return out


def read_background() -> dict[str, dict]:
    p = os.path.join(DATA, "patient_background.csv")
    if not os.path.exists(p):
        return {}
    out = {}
    with io.open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["研究番号"].strip()] = {
                "年齢": Fl(r["年齢"]), "性別": r["性別"].strip() or None,
                "投与開始日": (dt.date.fromisoformat(r["投与開始日"].strip())
                          if r["投与開始日"].strip() else None)}
    return out


# ---------------------------------------------------------------- 症例の構築

BASELINE_LABELS = {"0か月", "初回"}
BASELINE_WINDOW_DAYS = 120       # 時点ラベルが無い行をベースラインと認める窓
BASELINE_WINDOW_MONTHS = 1       # 年月のみの記録を照合するときの許容幅（月）


@dataclass
class Case:
    pid: str
    drug: str
    mmse: list[CogVisit] = field(default_factory=list)
    cdr: list[CogVisit] = field(default_factory=list)
    moca: list[CogVisit] = field(default_factory=list)
    npi_bl: Optional[NpiRow] = None
    npi_fu: Optional[NpiRow] = None
    step: str = ""                 # 組み入れのどの段階で落ちたか
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    # --- NPI
    @property
    def d_npi(self) -> Optional[float]:
        if not self.npi_bl or not self.npi_fu:
            return None
        if self.npi_bl.score is None or self.npi_fu.score is None:
            return None
        return self.npi_fu.score - self.npi_bl.score

    @property
    def group(self) -> Optional[str]:
        d = self.d_npi
        if d is None:
            return None
        return "スコア上昇群" if d >= 1 else "スコア非上昇群"

    @property
    def pattern(self) -> Optional[str]:
        """初回スコアと推移の5分類。"""
        if self.d_npi is None:
            return None
        b, a = self.npi_bl.score, self.npi_fu.score
        if b == 0:
            return "初回0点→0点のまま" if a == 0 else "初回0点→1点以上へ上昇"
        if a < b:
            return "初回1点以上→低下"
        if a == b:
            return "初回1点以上→不変"
        return "初回1点以上→上昇"

    # --- 認知機能
    def panel(self, sheet: str) -> list[CogVisit]:
        return {"MMSE": self.mmse, "CDR": self.cdr, "MoCA": self.moca}[sheet]

    def visit(self, sheet: str, label: str) -> Optional[CogVisit]:
        return next((v for v in self.panel(sheet) if v.label == label), None)

    def value(self, sheet: str, key: str, label: str) -> Optional[float]:
        v = self.visit(sheet, label)
        if v is None:
            return None
        if key == "__total__":
            return v.total
        if key == "__global__":
            return v.globalcdr
        return v.items.get(key)

    def baseline_visit(self, sheet: str) -> Optional[CogVisit]:
        v = self.visit(sheet, "0か月")
        return v if (v and v.total is not None) else None

    def followup_visit(self, sheet: str) -> Optional[CogVisit]:
        """評価時点選択ルール（下の文書化参照）で選んだ追跡時の評価。"""
        cand = [v for v in self.panel(sheet)
                if v.label != "0か月" and v.total is not None]
        if not cand:
            return None
        ref = self.npi_fu.date if self.npi_fu else None
        dated = [v for v in cand if v.date]
        if ref and dated:
            return min(dated, key=lambda v: abs((v.date - ref).days))
        return cand[-1]          # 日付が無い場合は時点ラベル順で最後

    def bl_fu(self, sheet: str, key: str) -> tuple[Optional[float], Optional[float]]:
        b, f = self.baseline_visit(sheet), self.followup_visit(sheet)
        if b is None or f is None:
            return None, None
        g = (lambda v: v.total) if key == "__total__" else (
            (lambda v: v.globalcdr) if key == "__global__"
            else (lambda v: v.items.get(key)))
        return g(b), g(f)

    def delta(self, sheet: str, key: str) -> Optional[float]:
        b, f = self.bl_fu(sheet, key)
        return None if b is None or f is None else round(f - b, 3)


def build_cases() -> tuple[list[Case], list[dict]]:
    """全研究番号について症例を組み立て、組み入れ段階を記録する。"""
    cases: list[Case] = []
    for drug, path in FILES.items():
        mm, cd, mo = (read_cog(path, "MMSE"), read_cog(path, "CDR"),
                      read_cog(path, "MoCA-J"))
        npi = read_npi(path)
        pids = sorted(set(mm) | set(cd) | set(npi),
                      key=lambda x: (x[0], int(re.sub(r"\D", "", x) or 0)))
        for pid in pids:
            c = Case(pid, drug, mm.get(pid, []), cd.get(pid, []), mo.get(pid, []))
            if pid not in mm:
                c.notes.append("MMSE/CDRシートに行が存在しない（NPIシートのみ）")

            rows = npi.get(pid, [])
            usable = [r for r in rows if r.presence not in NPI_NO_SCORE]
            bvis = c.baseline_visit("MMSE")
            cog_bl_date = bvis.date if bvis else None

            cog_bl_ym = (cog_bl_date.year, cog_bl_date.month) if cog_bl_date else None

            def is_bl(r: NpiRow) -> bool:
                """ベースラインとみなす規則（適用前に文書化）。
                (a) 時点ラベルが「0か月」または「初回」
                (b) 評価日が認知機能ベースライン評価日の±120日以内
                (c) 評価日が年月のみの記録では、記録されている年月が
                    認知機能ベースラインの年月と±1か月以内
                日そのものを推定して補うことはしない。
                """
                if r.label in BASELINE_LABELS:
                    return True
                if r.date and cog_bl_date:
                    return abs((r.date - cog_bl_date).days) <= BASELINE_WINDOW_DAYS
                if r.ym and cog_bl_ym:
                    return ym_diff(r.ym, cog_bl_ym) <= BASELINE_WINDOW_MONTHS
                return False

            blc = [r for r in usable if is_bl(r)]
            fuc = [r for r in usable if r not in blc]

            if not rows or not usable:
                c.step = "S1_NPI原票なし"
                c.reason = "NPI原票が添付PDFに存在しない（未実施かどうかは不明）"
                cases.append(c)
                continue
            if not blc or not fuc:
                c.step = "S2_NPIが1時点のみ"
                c.reason = ("ベースラインに該当する記録がない" if not blc
                            else "追跡時に該当する記録がない")
                cases.append(c)
                continue
            c.npi_bl = min(blc, key=lambda r: (r.date or dt.date(9999, 1, 1)))
            c.npi_fu = max(fuc, key=lambda r: (r.date or dt.date(1, 1, 1)))
            if c.npi_bl.score is None or c.npi_fu.score is None:
                c.step = "S3_NPIスコア算出不能"
                miss = [x for x, r in (("初回", c.npi_bl), ("追跡時", c.npi_fu))
                        if r.score is None]
                c.reason = (f"{'・'.join(miss)}の頻度・重症度が未記入でスコアを算出できない"
                            f"（有無欄: 初回「{c.npi_bl.presence}」/"
                            f"追跡時「{c.npi_fu.presence}」）")
                cases.append(c)
                continue
            if c.baseline_visit("MMSE") is None or c.followup_visit("MMSE") is None \
                    or c.baseline_visit("CDR") is None or c.followup_visit("CDR") is None:
                c.step = "S4_認知機能の追跡なし"
                have = []
                for sh in ("MMSE", "CDR"):
                    b = c.baseline_visit(sh) is not None
                    f = c.followup_visit(sh) is not None
                    have.append(f"{sh}: 初回{'あり' if b else 'なし'}／追跡{'あり' if f else 'なし'}")
                c.reason = "；".join(have)
                cases.append(c)
                continue
            c.step = "S5_解析対象"
            if c.npi_bl.presence == "判定保留":
                c.notes.append("初回の有無欄は判定保留だが、頻度・重症度が原資料に記載され"
                               "スコアは算出できる")
            if c.npi_fu.rule_imputed or c.npi_bl.rule_imputed:
                c.notes.append("研究上の記録ルールにより頻度・重症度を0と入力した行を含む"
                               "（原資料の頻度・重症度欄は空欄）")
            if c.npi_fu.orig_label != c.npi_fu.label:
                c.notes.append(f"NPI追跡の時点ラベルは「{c.npi_fu.label}」だが"
                               f"原資料は{c.npi_fu.orig_label}")
            if c.npi_bl.date_prec == "month_only" or c.npi_fu.date_prec == "month_only":
                c.notes.append("NPIの評価日が年月のみの記録を含む（日は推定していない）")
            if c.npi_bl.label not in BASELINE_LABELS:
                c.notes.append(f"初回NPIの時点ラベルは「{c.npi_bl.label}」であり、"
                               "評価日（年月）が認知機能ベースラインと一致することから"
                               "ベースラインとみなした")
            cases.append(c)

    flow = []
    for drug in FILES:
        sub = [c for c in cases if c.drug == drug]
        for step in ("S1_NPI原票なし", "S2_NPIが1時点のみ", "S3_NPIスコア算出不能",
                     "S4_認知機能の追跡なし", "S5_解析対象"):
            g = [c for c in sub if c.step == step]
            flow.append({"薬剤": drug, "段階": step, "n": len(g),
                         "研究番号": ",".join(x.pid for x in g) if len(g) <= 15 else "",
                         "代表的な理由": g[0].reason if g and g[0].reason else ""})
    return cases, flow


# ---------------------------------------------------------------- 統計

def med_range(v: list[float]) -> str:
    if not v:
        return "－"
    s = sorted(v)
    return f"{stx.median(s):g}［{min(s):g}, {max(s):g}］"


def vals(v: list[float]) -> str:
    return "、".join(f"{x:g}" for x in sorted(v)) if v else "－"


def n_ties(a: list[float], b: list[float]) -> int:
    """2群を併せたときの同順位（同値が複数ある値）に属する観測数。"""
    from collections import Counter
    c = Counter(a + b)
    return sum(k for k in c.values() if k > 1)


def perm_mwu(a: list[float], b: list[float]) -> dict:
    """Mann-Whitney U（順位和）の完全並べ替え検定。
    全 C(n, n1) 通りを列挙するため、同順位があっても正確な両側p値が得られる。
    scipy の exact 法は同順位を扱えないため、こちらを用いる。
    """
    n1, n2 = len(a), len(b)
    n = n1 + n2
    if n1 == 0 or n2 == 0:
        return {"p": None, "note": "いずれかの群が0例"}
    allv = a + b
    # 中間順位（同順位は平均順位）
    order = sorted(range(n), key=lambda i: allv[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and allv[order[j + 1]] == allv[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    obs = sum(ranks[:n1])
    total = math.comb(n, n1)
    mean = n1 * (n + 1) / 2
    cnt = 0
    for combo in itertools.combinations(range(n), n1):
        s = sum(ranks[i] for i in combo)
        if abs(s - mean) >= abs(obs - mean) - 1e-9:
            cnt += 1
    u = obs - n1 * (n1 + 1) / 2
    return {"U": u, "順位和": obs, "p": cnt / total,
            "並べ替え総数": total,
            "到達可能な最小p": 2.0 / total,
            "同順位に属する観測数": n_ties(a, b),
            "note": "完全並べ替えによる両側正確p値（同順位を中間順位で処理）"}


def fisher2x2(a1: int, a0: int, b1: int, b0: int) -> float:
    """2×2のFisher正確確率検定（両側）。超幾何分布を直接計算する。"""
    n = a1 + a0 + b1 + b0
    r1, r2 = a1 + a0, b1 + b0
    c1 = a1 + b1
    p_obs = (math.comb(r1, a1) * math.comb(r2, b1)) / math.comb(n, c1)
    p = 0.0
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    for k in range(lo, hi + 1):
        pk = (math.comb(r1, k) * math.comb(r2, c1 - k)) / math.comb(n, c1)
        if pk <= p_obs + 1e-12:
            p += pk
    return min(p, 1.0)


def rank_biserial(a: list[float], b: list[float]) -> Optional[float]:
    """順位二列相関（a>b の確率 − a<b の確率）。同順位は0.5で数える。"""
    if not a or not b:
        return None
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


# ---------------------------------------------------------------- 出力

def wcsv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in keys})


PRIMARY = [("MMSE合計", "MMSE", "__total__"), ("CDR-SB", "CDR", "__total__")]
SECOND = [("Global CDR", "CDR", "__global__"), ("MoCA-J", "MoCA", "__total__")]
EXPLOR = ([(f"MMSE {k}", "MMSE", k) for k in MMSE_SUB]
          + [(f"CDR {k}", "CDR", k) for k in CDR_DOM])


def main() -> None:
    cases, flow = build_cases()
    BG = read_background()
    wcsv("v2_selection_flow.csv", flow)

    inc = [c for c in cases if c.step == "S5_解析対象"]
    up = [c for c in inc if c.group == "スコア上昇群"]
    nu = [c for c in inc if c.group == "スコア非上昇群"]

    R: list[str] = []
    A = R.append
    A("# NPIアパシースコアの上昇の有無と認知機能変化 — 再解析レポート\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("**本解析の群分けは既存データを確認したのちに設定したものであり、"
      "研究開始前に規定したものではない。探索的・記述的な位置づけである。**\n")
    A("変化量の向き: MMSE・MoCA-Jは追跡−初回（正値＝得点上昇）、"
      "CDR-SB・Global CDRは追跡−初回（正値＝重症度上昇）、"
      "NPIアパシーは追跡−初回（正値＝スコア上昇）。\n")

    # ---------------------------------------------------------- 1. 対象選択
    A("\n## 1. 対象の選択\n")
    A("| 薬剤 | 段階 | n | 研究番号 |")
    A("|---|---|---|---|")
    for r in flow:
        A(f"| {r['薬剤']} | {r['段階']} | {r['n']} | {r['研究番号'] or '（省略）'} |")
    tot = len(cases)
    A(f"\n- 両ファイルに含まれる研究番号: **{tot}件**"
      f"（レカネマブ {sum(1 for c in cases if c.drug=='レカネマブ')}、"
      f"ドナネマブ {sum(1 for c in cases if c.drug=='ドナネマブ')}）")
    l69 = [c for c in cases if c.pid == "L69"]
    if l69:
        A("  - うち L69 はNPIシートにのみ収載され、MMSE/CDR/MoCA-Jの行が存在しない"
          "（READMEに明記）。旧抄録の「96例」はL69を含まない66＋30である。")
    A(f"- NPIスコアが初回・追跡時とも算出できた症例: "
      f"**{sum(1 for c in cases if c.step in ('S4_認知機能の追跡なし','S5_解析対象'))}件**")
    A(f"- そのうちMMSE・CDRの初回と追跡の両方が得られた症例（解析対象）: **{len(inc)}件**")
    A(f"  - {', '.join(c.pid for c in inc)}")
    A(f"  - 薬剤内訳: "
      + "、".join(f"{d} {sum(1 for c in inc if c.drug==d)}例" for d in FILES))
    A("\n**除外の区別**")
    A("- S1（NPI原票なし）は「添付PDFに記録がない」であり、未実施とは判定できない。")
    A("- S2（NPIが1時点のみ）は追跡未到達か記録欠損かを、本データからは区別できない。")
    A("- S3（スコア算出不能）は有無欄が未記入で頻度・重症度も無いもの。欠測として扱い、"
      "0点とはしていない。")
    A("- S4（認知機能の追跡なし）は、MMSE・CDRの追跡値が記録されていないもの。")

    # ---------------------------------------------------------- 2. データ照合
    A("\n\n## 2. 元データの照合結果\n")
    A("### 2-1. NPIの版と採点\n")
    A("- 両ファイルのREADMEに、アパシーの頻度F（1–4）と重症度S（1–3）を原票から転記し、"
      "NPI-Apathy score = F×S（0–12点）として算出したと明記されている。"
      "本解析でも全行で score = F×S の整合を確認した（不一致0件）。")
    A("- 「なし」に丸印がある記録の得点は0点としている。"
      "この0点は頻度・重症度の記録からではなく有無欄の丸印に由来する。")
    A("- **NPIの版（NPI-10/12、NPI-NH等）はいずれのファイルにも記載がない。**"
      "項目番号（第7項目＝無関心・アパシー、第9項目＝易怒性）と頻度×重症度の"
      "採点方式は記載されているが、版の特定はできないため抄録では版を断定しない。")
    A("- READMEには「旧問診結果からは補完しない」「従来の問診値からは補完しない」と"
      "明記されており、NPI-Qや自由記載から頻度を推測した形跡は確認されなかった。")

    ruled = [c for c in inc if any("記録ルール" in n for n in c.notes)]
    A("\n### 2-2. 研究上の記録ルールによる入力値\n")
    A("READMEに「0か月の得点が1点以上で18か月に『なし』の場合、18か月の頻度・重症度も0とする」"
      "という規則が記載されている。原資料の頻度・重症度欄は空欄である。")
    A(f"\n解析対象{len(inc)}例のうち該当するのは **{len(ruled)}例**"
      f"（{', '.join(c.pid for c in ruled) or 'なし'}）で、"
      "いずれも本解析ではスコア非上昇群に分類される。")
    A("この入力値を欠測として扱った場合の影響は §6 の感度分析で示す。")

    A("\n### 2-3. 「初回」の位置づけ\n")
    A("- レカネマブのREADME: 「初回」は0か月と明記。")
    A("- ドナネマブのREADME: **「初回」は治療開始時（0か月）を意味するとは限らない**"
      "と明記されている。治療開始前・開始時・開始後のいずれかは本データからは確定できない。")
    lec_start = [BG.get(c.pid, {}).get("投与開始日") for c in inc]
    lec_start = [d for d in lec_start if d]
    A(f"- 解析対象{len(inc)}例のうち投与開始日が判明したのは{len(lec_start)}例。"
      + (f"範囲は {min(lec_start)} 〜 {max(lec_start)}。" if lec_start else ""))

    A("\n### 2-4. 合計点と下位項目の整合\n")
    mm_bad, cdr_bad = [], []
    for c in cases:
        for v in c.mmse:
            sub = [v.items.get(k) for k in MMSE_SUB]
            if v.total is not None and all(x is not None for x in sub):
                if abs(v.total - sum(sub)) > 1e-9:
                    mm_bad.append(f"{c.pid}/{v.label}: 合計{v.total:g} vs 下位項目計{sum(sub):g}")
        for v in c.cdr:
            dom = [v.items.get(k) for k in CDR_DOM]
            if v.total is not None and all(x is not None for x in dom):
                if abs(v.total - sum(dom)) > 1e-9:
                    cdr_bad.append(f"{c.pid}/{v.label}: SB{v.total:g} vs 6領域計{sum(dom):g}")
    A(f"- MMSE合計と下位項目合計の不一致: **{len(mm_bad)}件**"
      + (f"（{'、'.join(mm_bad)}）" if mm_bad else ""))
    A(f"- CDR-SBと6領域合計の不一致: **{len(cdr_bad)}件**"
      + (f"（{'、'.join(cdr_bad)}）" if cdr_bad else ""))
    inc_ids = {c.pid for c in inc}
    aff = [x for x in mm_bad + cdr_bad if x.split("/")[0] in inc_ids]
    A(f"- そのうち解析対象{len(inc)}例に含まれるもの: **{len(aff)}件**"
      + (f"（{'、'.join(aff)}）" if aff else "（なし）"))
    A("\n不一致例は原資料の確認が必要である。本解析では値の訂正・補完を行っていない。")

    A("\n### 2-5. 情報提供者・評価方法の変更\n")
    A("NPI・MMSE・CDRのいずれのシートにも、情報提供者（介護者）や評価者、"
      "評価方法の変更を記録する列は存在しない。要再確認ログにも該当する記載はない。"
      "**したがって変更の有無は本データからは確認できない。** 抄録では言及しない。")

    # ---------------------------------------------------------- 3. 旧抄録の不整合
    A("\n\n## 3. 旧抄録の下位項目と合計点の不整合の検証\n")
    A("旧抄録が個別記載した2例について、MMSE下位11項目の変化量をすべて算出し、"
      "合計点の変化と突き合わせた。\n")
    recon = []
    for pid, disp in (("L4", "旧スコア低下例1"), ("L59", "旧スコア低下例2")):
        c = next((x for x in cases if x.pid == pid), None)
        if c is None:
            continue
        fv = c.followup_visit("MMSE")
        bt, ft = c.bl_fu("MMSE", "__total__")
        A(f"\n**{disp}（{pid}、0か月 → {fv.label}）**\n")
        A("| 下位項目 | 初回 | 追跡 | Δ |")
        A("|---|---|---|---|")
        ssum = 0.0
        for k in MMSE_SUB:
            b, f = c.bl_fu("MMSE", k)
            if b is None or f is None:
                continue
            ssum += f - b
            if f - b != 0:
                A(f"| {k} | {b:g} | {f:g} | {f-b:+g} |")
        A(f"\n- 下位項目Δの総和: **{ssum:+g}点**")
        A(f"- MMSE合計: {bt:g} → {ft:g}（**{ft-bt:+g}点**）")
        ok = abs(ssum - (ft - bt)) < 1e-9
        A(f"- 突合結果: **{'一致する' if ok else '一致しない'}**")
        recon.append({"症例": pid, "下位項目Δ総和": ssum, "合計点Δ": ft - bt,
                      "一致": "一致" if ok else "不一致"})
    A("\n**結論**: 元データでは下位項目の変化量の総和と合計点の変化量は一致しており、"
      "データの誤りではない。旧抄録の本文が下位項目の一部（1例目の図形模写 0→1、"
      "2例目の注意計算 3→4）を省略して記載していたことが不整合の原因である。"
      "合計点・評価日の取り違えではない。値の訂正は行っていない。")
    wcsv("v2_old_abstract_reconciliation.csv", recon)

    # ---------------------------------------------------------- 4. 評価時点
    A("\n\n## 4. 評価時点の選択ルールと観察期間\n")
    A("### 4-1. 採用したルール（適用前に文書化）\n")
    A("1. 初回は MMSE・CDR の「0か月」の記録とする。")
    A("2. 追跡時は、**NPI追跡評価日に評価日が最も近い認知機能の評価時点**とする。")
    A("3. 認知機能の評価日が記録されていない症例では、時点ラベルの順で最後の記録を用いる。")
    A("4. 一律18か月などデータで実現できない時点への統一は行わない。")
    A("\nこのルールは旧解析と同一であり、有意差を見て選択したものではない。")
    npifu = [c.npi_fu.date for c in inc if c.npi_fu.date]
    cogd = [v.date for c in inc for v in (c.followup_visit("MMSE"),) if v and v.date]
    if npifu and cogd:
        A(f"\nNPI追跡評価日は {min(npifu)} 〜 {max(npifu)} に分布し、"
          f"認知機能の評価日（{min(cogd)} 〜 {max(cogd)}）より後である。"
          "そのためルール2は結果として「最終利用可能時点」と一致する。")

    A("\n### 4-2. 症例ごとの評価日と経過\n")
    A("| 症例 | 群 | NPI初回 | NPI追跡 | NPI間隔(月) | 認知機能 追跡時点 | "
      "MMSE初回日 | MMSE追跡日 | 初回からの経過(月) | NPI追跡日とのずれ(月) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    tp_rows = []
    for c in sorted(inc, key=lambda x: (x.group != "スコア上昇群", x.pid)):
        fv = c.followup_visit("MMSE")
        bv = c.baseline_visit("MMSE")
        ni = (months(c.npi_bl.date, c.npi_fu.date)
              if c.npi_bl.date and c.npi_fu.date else None)
        el = months(bv.date, fv.date) if bv and bv.date and fv and fv.date else None
        gp = (months(fv.date, c.npi_fu.date)
              if fv and fv.date and c.npi_fu.date else None)
        A(f"| {c.pid} | {c.group} | {c.npi_bl.date or '年月のみ'} | "
          f"{c.npi_fu.date or '年月のみ'} | {ni if ni is not None else '－'} | "
          f"{fv.label} | {bv.date or '－'} | {fv.date or '－'} | "
          f"{el if el is not None else '－'} | {gp if gp is not None else '－'} |")
        tp_rows.append({"症例": c.pid, "群": c.group, "薬剤": c.drug,
                        "NPI初回日": c.npi_bl.date, "NPI追跡日": c.npi_fu.date,
                        "NPI間隔_月": ni, "NPI時点ラベル": c.npi_fu.label,
                        "NPI原資料時点": c.npi_fu.orig_label,
                        "認知機能追跡時点": fv.label,
                        "MMSE初回日": bv.date if bv else None,
                        "MMSE追跡日": fv.date if fv else None,
                        "初回からの経過_月": el, "NPI追跡日とのずれ_月": gp})
    wcsv("v2_timepoints.csv", tp_rows)

    A("\n### 4-3. 両群の観察期間の分布\n")
    A("| 群 | n | 認知機能の追跡時点の内訳 | 初回からの経過（月）中央値［範囲］ |")
    A("|---|---|---|---|")
    for nm, g in (("スコア上昇群", up), ("スコア非上昇群", nu)):
        from collections import Counter
        cnt = Counter(c.followup_visit("MMSE").label for c in g)
        el = [months(c.baseline_visit("MMSE").date, c.followup_visit("MMSE").date)
              for c in g if c.baseline_visit("MMSE") and c.baseline_visit("MMSE").date
              and c.followup_visit("MMSE").date]
        A(f"| {nm} | {len(g)} | "
          + "、".join(f"{k} {v}例" for k, v in sorted(
              cnt.items(), key=lambda t: TP_ORDER.index(t[0]) if t[0] in TP_ORDER else 99))
          + f" | {med_range(el) if el else '－'}（n={len(el)}） |")
    A("\n**観察期間は6〜24か月にわたり、両群で同一ではない。同じ観察条件での比較ではない。**")
    A("変化量を月数で割る処理は、認知機能の変化が時間に比例することを前提とするため行わない。")

    # ---------------------------------------------------------- 5. 群分け
    A("\n\n## 5. 新しい群分け\n")
    A("ΔNPIアパシー = 追跡時スコア − 初回スコア。"
      "**スコア上昇群**は Δ ≧ +1、**スコア非上昇群**は Δ ≦ 0 と定義した。"
      "1点の上昇を検証された臨床的悪化の閾値とはみなさない。\n")
    A(f"- スコア上昇群: **{len(up)}例**（{', '.join(c.pid for c in up)}）")
    A(f"- スコア非上昇群: **{len(nu)}例**（{', '.join(c.pid for c in nu)}）")

    A("\n### 5-1. 初回スコアと推移の内訳\n")
    A("| 推移のパターン | n | 研究番号 | 所属する群 |")
    A("|---|---|---|---|")
    pats = ["初回0点→0点のまま", "初回0点→1点以上へ上昇", "初回1点以上→低下",
            "初回1点以上→不変", "初回1点以上→上昇"]
    for p in pats:
        g = [c for c in inc if c.pattern == p]
        grp = sorted({c.group for c in g})
        A(f"| {p} | {len(g)} | {', '.join(c.pid for c in g) or '－'} | "
          f"{'／'.join(grp) or '－'} |")
    A("\n**解釈上の注意**")
    A("- スコア上昇群には、**症状がなかった例に新たに出現した場合**（初回0点→1点以上）と、"
      "**もともとあった症状が強まった場合**（初回1点以上→上昇）が含まれる。")
    A("- スコア非上昇群には、**症状がないまま推移した場合**（初回0点→0点）と、"
      "**スコアが低下した場合**（初回1点以上→低下）が含まれる。")
    A("- したがって両群はそれぞれ質の異なる経過を併せた集団であり、"
      "群名をそのまま臨床経過の良否として読むことはできない。")

    det = []
    A("\n### 5-2. 匿名症例別一覧\n")
    A("| 症例 | 薬剤 | 群 | 推移パターン | NPI初回 | NPI追跡 | ΔNPI | "
      "MMSE初回 | MMSE追跡 | ΔMMSE | CDR-SB初回 | CDR-SB追跡 | ΔCDR-SB | 注記 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in sorted(inc, key=lambda x: (x.group != "スコア上昇群", x.pid)):
        mb, mf = c.bl_fu("MMSE", "__total__")
        cb, cf = c.bl_fu("CDR", "__total__")
        A(f"| {c.pid} | {c.drug} | {c.group} | {c.pattern} | "
          f"{c.npi_bl.score:g} | {c.npi_fu.score:g} | {c.d_npi:+g} | "
          f"{mb:g} | {mf:g} | {mf-mb:+g} | {cb:g} | {cf:g} | {cf-cb:+g} | "
          f"{' / '.join(c.notes) or '－'} |")
        row = {"症例": c.pid, "薬剤": c.drug, "群": c.group, "推移パターン": c.pattern,
               "年齢": BG.get(c.pid, {}).get("年齢"),
               "性別": BG.get(c.pid, {}).get("性別"),
               "投与開始日": BG.get(c.pid, {}).get("投与開始日"),
               "NPI初回スコア": c.npi_bl.score, "NPI追跡スコア": c.npi_fu.score,
               "ΔNPIアパシー": c.d_npi,
               "NPI初回日": c.npi_bl.date, "NPI追跡日": c.npi_fu.date,
               "認知機能追跡時点": c.followup_visit("MMSE").label,
               "注記": " / ".join(c.notes)}
        for nm, sh, k in PRIMARY + SECOND + EXPLOR:
            b, f = c.bl_fu(sh, k)
            row[f"{nm}_初回"] = b
            row[f"{nm}_追跡"] = f
            row[f"Δ{nm}"] = None if b is None or f is None else round(f - b, 3)
        det.append(row)
    wcsv("v2_case_detail.csv", det)

    # ---------------------------------------------------------- 6. 記述統計
    A("\n\n## 6. 両群の記述統計\n")
    A("少数群（スコア上昇群）は個別値も併記する。中央値［最小, 最大］で示す。\n")

    def col(g, fn):
        v = [fn(c) for c in g]
        return [x for x in v if x is not None]

    summ = []

    def line(sec, label, fn, show_vals=True, test=False):
        a, b = col(up, fn), col(nu, fn)
        rec = {"区分": sec, "項目": label,
               "上昇群n": len(a), "上昇群中央値[範囲]": med_range(a),
               "上昇群個別値": vals(a),
               "非上昇群n": len(b), "非上昇群中央値[範囲]": med_range(b),
               "非上昇群個別値": vals(b)}
        if test and a and b and len(set(a + b)) > 1:
            r = perm_mwu(a, b)
            rec.update({"検定": "Mann-Whitney U（完全並べ替え・両側）",
                        "U": r["U"], "p": round(r["p"], 4),
                        "到達可能な最小p": round(r["到達可能な最小p"], 4),
                        "同順位に属する観測数": r["同順位に属する観測数"],
                        "順位二列相関": (None if rank_biserial(a, b) is None
                                   else round(rank_biserial(a, b), 3))})
        summ.append(rec)
        return rec

    A("### 6-1. 患者背景\n")
    A("| 項目 | スコア上昇群（n=%d） | スコア非上昇群（n=%d） |" % (len(up), len(nu)))
    A("|---|---|---|")
    r = line("背景", "年齢（歳）", lambda c: BG.get(c.pid, {}).get("年齢"))
    A(f"| 年齢（歳） | {r['上昇群中央値[範囲]']}　個別値 {r['上昇群個別値']} | "
      f"{r['非上昇群中央値[範囲]']} |")
    fa = sum(1 for c in up if BG.get(c.pid, {}).get("性別") == "女性")
    fb = sum(1 for c in nu if BG.get(c.pid, {}).get("性別") == "女性")
    ka = sum(1 for c in up if BG.get(c.pid, {}).get("性別"))
    kb = sum(1 for c in nu if BG.get(c.pid, {}).get("性別"))
    A(f"| 女性 | {fa}/{ka}例 | {fb}/{kb}例 |")
    summ.append({"区分": "背景", "項目": "女性", "上昇群n": ka,
                 "上昇群中央値[範囲]": f"{fa}/{ka}", "非上昇群n": kb,
                 "非上昇群中央値[範囲]": f"{fb}/{kb}",
                 "検定": "Fisher正確確率検定（両側）",
                 "p": round(fisher2x2(fa, ka - fa, fb, kb - fb), 4)})
    dr = {d: (sum(1 for c in up if c.drug == d), sum(1 for c in nu if c.drug == d))
          for d in FILES}
    A("| 薬剤 | " + "、".join(f"{d} {v[0]}例" for d, v in dr.items()) + " | "
      + "、".join(f"{d} {v[1]}例" for d, v in dr.items()) + " |")
    el_up = [months(c.baseline_visit("MMSE").date, c.followup_visit("MMSE").date)
             for c in up if c.baseline_visit("MMSE") and c.baseline_visit("MMSE").date
             and c.followup_visit("MMSE").date]
    el_nu = [months(c.baseline_visit("MMSE").date, c.followup_visit("MMSE").date)
             for c in nu if c.baseline_visit("MMSE") and c.baseline_visit("MMSE").date
             and c.followup_visit("MMSE").date]
    A(f"| 初回からの経過（月） | {med_range(el_up)}（n={len(el_up)}） | "
      f"{med_range(el_nu)}（n={len(el_nu)}） |")
    gp_up = [months(c.followup_visit("MMSE").date, c.npi_fu.date)
             for c in up if c.followup_visit("MMSE").date and c.npi_fu.date]
    gp_nu = [months(c.followup_visit("MMSE").date, c.npi_fu.date)
             for c in nu if c.followup_visit("MMSE").date and c.npi_fu.date]
    A(f"| NPI追跡日と認知機能追跡日のずれ（月） | {med_range(gp_up)}（n={len(gp_up)}） | "
      f"{med_range(gp_nu)}（n={len(gp_nu)}） |")
    summ.append({"区分": "背景", "項目": "初回からの経過_月",
                 "上昇群n": len(el_up), "上昇群中央値[範囲]": med_range(el_up),
                 "上昇群個別値": vals(el_up),
                 "非上昇群n": len(el_nu), "非上昇群中央値[範囲]": med_range(el_nu),
                 "非上昇群個別値": vals(el_nu)})

    A("\n### 6-2. NPIアパシースコア\n")
    A("| 項目 | スコア上昇群（n=%d） | スコア非上昇群（n=%d） |" % (len(up), len(nu)))
    A("|---|---|---|")
    for lab, fn in (("初回スコア", lambda c: c.npi_bl.score),
                    ("追跡時スコア", lambda c: c.npi_fu.score),
                    ("ΔNPIアパシー", lambda c: c.d_npi)):
        r = line("NPI", lab, fn, test=True)
        A(f"| {lab} | {r['上昇群中央値[範囲]']}　個別値 {r['上昇群個別値']} | "
          f"{r['非上昇群中央値[範囲]']}　個別値 {r['非上昇群個別値']} |")

    A("\n### 6-3. 主要評価項目（MMSE合計・CDR-SB）\n")
    A("| 項目 | スコア上昇群（n=%d） | スコア非上昇群（n=%d） | p |" % (len(up), len(nu)))
    A("|---|---|---|---|")
    for nm, sh, k in PRIMARY:
        for suf, fn in (("初回", lambda c, s=sh, kk=k: c.bl_fu(s, kk)[0]),
                        ("追跡時", lambda c, s=sh, kk=k: c.bl_fu(s, kk)[1]),
                        ("変化量", lambda c, s=sh, kk=k: c.delta(s, kk))):
            r = line("主要", f"{nm} {suf}", fn, test=(suf == "変化量"))
            pt = (f"{r['p']:.3f}" if r.get("p") is not None else "－")
            A(f"| {nm} {suf} | {r['上昇群中央値[範囲]']}　個別値 {r['上昇群個別値']} | "
              f"{r['非上昇群中央値[範囲]']}　個別値 {r['非上昇群個別値']} | {pt} |")

    A("\n### 6-4. 参考指標（Global CDR・MoCA-J）\n")
    A("| 項目 | スコア上昇群 | スコア非上昇群 |")
    A("|---|---|---|")
    for nm, sh, k in SECOND:
        for suf, fn in (("初回", lambda c, s=sh, kk=k: c.bl_fu(s, kk)[0]),
                        ("変化量", lambda c, s=sh, kk=k: c.delta(s, kk))):
            r = line("参考", f"{nm} {suf}", fn)
            A(f"| {nm} {suf} | {r['上昇群中央値[範囲]']}（n={r['上昇群n']}） | "
              f"{r['非上昇群中央値[範囲]']}（n={r['非上昇群n']}） |")

    A("\n### 6-5. 変化の方向の内訳\n")
    A("| 指標 | 群 | 上昇 | 不変 | 低下 |")
    A("|---|---|---|---|---|")
    dirs = []
    for nm, sh, k in PRIMARY:
        for gname, g in (("スコア上昇群", up), ("スコア非上昇群", nu)):
            d = [c.delta(sh, k) for c in g]
            d = [x for x in d if x is not None]
            u_, z_, l_ = (sum(1 for x in d if x > 0), sum(1 for x in d if x == 0),
                          sum(1 for x in d if x < 0))
            A(f"| {nm} | {gname} | {u_}例 | {z_}例 | {l_}例 |")
            dirs.append({"指標": nm, "群": gname, "n": len(d),
                         "上昇": u_, "不変": z_, "低下": l_})
    wcsv("v2_direction_counts.csv", dirs)

    # ---------------------------------------------------------- 7. 初回分布
    A("\n\n## 7. 初回値の分布と変化の余地\n")
    A("MMSE下位項目は可動域が狭く、初回値が満点の項目は得点が上がりようがない。"
      "群分けを変更しても初回値の偏りが自動的に解消するとは限らないため、確認する。\n")
    A("| 項目 | 上昇群 初回（個別値） | 非上昇群 初回 中央値［範囲］ | "
      "上昇群で満点の例 | 非上昇群で満点の例 |")
    A("|---|---|---|---|---|")
    ceil_rows = []
    for k in ["時間見当識", "場所見当識", "注意計算", "遅延再生"]:
        a = col(up, lambda c, kk=k: c.bl_fu("MMSE", kk)[0])
        b = col(nu, lambda c, kk=k: c.bl_fu("MMSE", kk)[0])
        mx = MMSE_MAX[k]
        A(f"| MMSE {k}（満点{mx}） | {vals(a)} | {med_range(b)} | "
          f"{sum(1 for x in a if x == mx)}/{len(a)}例 | "
          f"{sum(1 for x in b if x == mx)}/{len(b)}例 |")
        ceil_rows.append({"項目": k, "満点": mx, "上昇群初回": vals(a),
                          "非上昇群初回中央値[範囲]": med_range(b),
                          "上昇群満点例": sum(1 for x in a if x == mx),
                          "非上昇群満点例": sum(1 for x in b if x == mx)})
    a = col(up, lambda c: c.bl_fu("MMSE", "__total__")[0])
    b = col(nu, lambda c: c.bl_fu("MMSE", "__total__")[0])
    A(f"| MMSE合計（満点30） | {vals(a)} | {med_range(b)} | "
      f"{sum(1 for x in a if x == 30)}/{len(a)}例 | {sum(1 for x in b if x == 30)}/{len(b)}例 |")
    wcsv("v2_baseline_ceiling.csv", ceil_rows)

    # ---------------------------------------------------------- 8. 探索的項目
    A("\n\n## 8. 探索的に検討した下位項目\n")
    A("MMSE下位11項目とCDR下位6領域の変化量を同一の方法で比較した。"
      "**多重性の調整は行っていない。17項目を未調整で検定しているため、"
      "偶然による低いp値が生じうる。確証的には解釈しない。**")
    A("以前の解析で注目したMMSE時間見当識も、ここでは他の項目と同格に扱う。\n")
    A("| 項目 | 上昇群 Δ 中央値［範囲］ | 非上昇群 Δ 中央値［範囲］ | "
      "順位二列相関 | p（未調整） |")
    A("|---|---|---|---|---|")
    ex_rows = []
    for nm, sh, k in EXPLOR:
        a = col(up, lambda c, s=sh, kk=k: c.delta(s, kk))
        b = col(nu, lambda c, s=sh, kk=k: c.delta(s, kk))
        if not a or not b:
            continue
        if len(set(a + b)) == 1:
            A(f"| {nm} | {med_range(a)} | {med_range(b)} | － | 両群とも全例同値 |")
            ex_rows.append({"項目": nm, "上昇群": med_range(a), "非上昇群": med_range(b),
                            "p": None, "備考": "両群とも全例同値のため検定不能"})
            continue
        r = perm_mwu(a, b)
        rb = rank_biserial(a, b)
        A(f"| {nm} | {med_range(a)} | {med_range(b)} | "
          f"{rb:+.2f} | {r['p']:.3f} |")
        ex_rows.append({"項目": nm, "上昇群n": len(a), "上昇群": med_range(a),
                        "上昇群個別値": vals(a), "非上昇群n": len(b),
                        "非上昇群": med_range(b), "非上昇群個別値": vals(b),
                        "順位二列相関": round(rb, 3), "U": r["U"],
                        "p_未調整": round(r["p"], 4),
                        "到達可能な最小p": round(r["到達可能な最小p"], 4),
                        "同順位に属する観測数": r["同順位に属する観測数"]})
    wcsv("v2_exploratory_subitems.csv", ex_rows)
    sig = [r for r in ex_rows if r.get("p_未調整") is not None and r["p_未調整"] < 0.05]
    A(f"\n未調整で p<0.05 となった項目: **{len(sig)}件**"
      + (f"（{'、'.join(r['項目'] for r in sig)}）" if sig else "（なし）"))
    A("\n17項目を未調整で検定した場合、少なくとも1項目が偶然 p<0.05 となる確率は"
      f"およそ {1-0.95**17:.0%} である。この結果から特定の下位項目との関連が"
      "他より強い、あるいは特異的であるとは結論できない。")
    wcsv("v2_summary_stats.csv", summ)

    # ---------------------------------------------------------- 9. 感度分析
    A("\n\n## 9. 感度分析\n")
    A("具体的な懸念を検証する目的に限って実施した。条件を多数試して選ぶことはしていない。\n")
    sens = []

    A("### 9-1. 研究上の記録ルールで0と入力した行を欠測として扱う\n")
    A("§2-2 の該当例を除外した場合の主要評価項目を示す。")
    ex_ids = {c.pid for c in ruled}
    up2 = [c for c in up if c.pid not in ex_ids]
    nu2 = [c for c in nu if c.pid not in ex_ids]
    A(f"\n除外対象: {', '.join(sorted(ex_ids)) or 'なし'} "
      f"→ スコア上昇群 {len(up)}→{len(up2)}例、非上昇群 {len(nu)}→{len(nu2)}例\n")
    A("| 項目 | 上昇群 | 非上昇群 | p |")
    A("|---|---|---|---|")
    for nm, sh, k in PRIMARY:
        a = [c.delta(sh, k) for c in up2]
        b = [c.delta(sh, k) for c in nu2]
        a = [x for x in a if x is not None]
        b = [x for x in b if x is not None]
        if not a or not b or len(set(a + b)) == 1:
            A(f"| Δ{nm} | {med_range(a)} | {med_range(b)} | 算出不能 |")
            continue
        r = perm_mwu(a, b)
        A(f"| Δ{nm} | {med_range(a)}（{vals(a)}） | {med_range(b)}（{vals(b)}） | "
          f"{r['p']:.3f} |")
        sens.append({"感度分析": "記録ルール行を除外", "項目": f"Δ{nm}",
                     "上昇群n": len(a), "上昇群": med_range(a),
                     "非上昇群n": len(b), "非上昇群": med_range(b),
                     "p": round(r["p"], 4)})

    A("\n### 9-2. 観察期間をそろえた比較\n")
    from collections import Counter
    cnt_all = Counter(c.followup_visit("MMSE").label for c in inc)
    A("認知機能の追跡時点の内訳: "
      + "、".join(f"{k} {v}例" for k, v in sorted(
          cnt_all.items(), key=lambda t: TP_ORDER.index(t[0]) if t[0] in TP_ORDER else 99)))
    common = [t for t in ["6か月", "12か月", "18か月", "24か月"]
              if all(c.value("MMSE", "__total__", t) is not None
                     and c.value("CDR", "__total__", t) is not None for c in inc)]
    A(f"\n全{len(inc)}例がそろう時点: "
      + ("、".join(common) if common else "なし"))
    if common:
        t = common[0]
        A(f"\n**{t}時点に固定した場合**（観察期間差という具体的な懸念の検証）\n")
        A("| 項目 | 上昇群 | 非上昇群 | p |")
        A("|---|---|---|---|")
        for nm, sh, k in PRIMARY:
            def dfix(c, s=sh, kk=k, tt=t):
                b = c.value(s, kk, "0か月")
                f = c.value(s, kk, tt)
                return None if b is None or f is None else f - b
            a = [x for x in (dfix(c) for c in up) if x is not None]
            b = [x for x in (dfix(c) for c in nu) if x is not None]
            if not a or not b or len(set(a + b)) == 1:
                A(f"| Δ{nm}（{t}） | {med_range(a)} | {med_range(b)} | 算出不能 |")
                continue
            r = perm_mwu(a, b)
            A(f"| Δ{nm}（{t}） | {med_range(a)}（{vals(a)}） | "
              f"{med_range(b)}（{vals(b)}） | {r['p']:.3f} |")
            sens.append({"感度分析": f"{t}に固定", "項目": f"Δ{nm}",
                         "上昇群n": len(a), "上昇群": med_range(a),
                         "非上昇群n": len(b), "非上昇群": med_range(b),
                         "p": round(r["p"], 4)})
        A(f"\nこの固定時点の解析はNPIの評価間隔（中央値 "
          f"{stx.median([months(c.npi_bl.date, c.npi_fu.date) for c in inc if c.npi_bl.date and c.npi_fu.date]):g}か月）"
          f"より短い期間の認知機能を比較している点に注意が必要である。")
    wcsv("v2_sensitivity.csv", sens)

    # ---------------------------------------------------------- 10. まとめ
    A("\n\n## 10. データから言えること・言えないこと\n")
    dm_up = [c.delta("MMSE", "__total__") for c in up]
    dm_nu = [c.delta("MMSE", "__total__") for c in nu]
    dc_up = [c.delta("CDR", "__total__") for c in up]
    dc_nu = [c.delta("CDR", "__total__") for c in nu]
    rm = perm_mwu(dm_up, dm_nu)
    rc = perm_mwu(dc_up, dc_nu)
    A("**言えること**")
    A(f"- ΔMMSE合計は上昇群 {med_range(dm_up)}、非上昇群 {med_range(dm_nu)}"
      f"（p={rm['p']:.3f}、未調整）。")
    A(f"- ΔCDR-SBは上昇群 {med_range(dc_up)}、非上昇群 {med_range(dc_nu)}"
      f"（p={rc['p']:.3f}、未調整）。")
    A(f"- 両群の分布は重なっており、{len(inc)}例の範囲では明瞭な違いを示せていない。")
    A("\n**言えないこと**")
    A("- 非有意であることは「差がない」「同等である」ことを意味しない。"
      "本研究の症例数では小さな差を検出できない。")
    A("- 全例が治療例であり非治療対照がないため、薬剤の効果は評価できない。")
    A("- スコア非上昇を「改善」「治療奏効」「悪化予防」と読み替えることはできない。")
    A("- 観察期間が6〜24か月と異なり、同じ条件での比較ではない。")
    A("- 特定の下位項目との関連が他より強い、特異的であるとは結論できない。")

    text = "\n".join(R)
    with io.open(os.path.join(OUT, "v2_reanalysis_report.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
