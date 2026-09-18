# -*- coding: utf-8 -*-
"""
抗アミロイドβ抗体療法 後方視的観察研究
NPI 第7項目（アパシー・無関心）／第9項目（易怒性）の推移と
MMSE・CDR-SB の変化量との関連解析

入力:
  data_local/lecanemab_L1-66_NPI.xlsx
  data_local/donanemab_D1-D30_NPI.xlsx
出力:
  output/*.csv, output/analysis_report.md

実行: python3 analysis/npi_analysis.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

import openpyxl
from scipy.stats import mannwhitneyu, fisher_exact

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data_local")
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

FILES = {
    "レカネマブ": os.path.join(DATA, "lecanemab_L1-66_NPI.xlsx"),
    "ドナネマブ": os.path.join(DATA, "donanemab_D1-D30_NPI.xlsx"),
}

# ---------------------------------------------------------------- 値の正規化

# NPI の有無欄の取りうる値の分類
NPI_PRESENT = {"あり"}
NPI_ABSENT = {"なし"}
# 判定不能だが原票は存在する（確認事項に手がかりがあれば参考値として採用しうる）
NPI_INDETERMINATE = {"未記入", "判定保留", "不明"}
# 原票そのものが無い＝解析対象外
NPI_NO_SOURCE = {"資料未提供", "原票なし", "記載なし", ""}

MONTH_LABELS = ["0か月", "6か月", "12か月", "18か月", "24か月"]


def s(v) -> str:
    """セル値を文字列に正規化（改行・全角空白を除去）"""
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).replace("\n", "").replace("　", " ").strip()


def to_float(v) -> Optional[float]:
    t = s(v)
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        return None


DATE_RE = re.compile(r"(\d{4})[-/\.年](\d{1,2})[-/\.月](\d{1,2})")
YM_RE = re.compile(r"(\d{4})[-/\.年](\d{1,2})")


def parse_date(v) -> tuple[Optional[dt.date], str]:
    """日付セルを (date, 精度) に変換。
    精度: 'day'（年月日確定） / 'month'（年月のみ→当月15日で近似） / ''（不明）
    'MMSE/CDR: 2024-08-29; MoCA-J: ...' のような複合文字列にも対応する。
    """
    if v is None:
        return None, ""
    if isinstance(v, dt.datetime):
        return v.date(), "day"
    if isinstance(v, dt.date):
        return v, "day"
    t = s(v)
    if not t:
        return None, ""
    # 複合表記は MMSE/CDR 側の日付を優先して拾う
    m = re.search(r"MMSE/CDR\s*[:：]\s*(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "day"
    m = DATE_RE.search(t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "day"
        except ValueError:
            pass
    m = YM_RE.search(t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), 15), "month"
        except ValueError:
            pass
    return None, ""


def months_between(a: dt.date, b: dt.date) -> float:
    return round((b - a).days / 30.4375, 1)


# ---------------------------------------------------------------- 読み込み

@dataclass
class CogPoint:
    """MMSE または CDR の1時点"""
    label: str
    value: Optional[float]
    value_source: str          # '原資料記載値' / '自動計算'
    date: Optional[dt.date]
    date_precision: str
    globalcdr: Optional[float] = None


@dataclass
class NpiPoint:
    label: str                 # シート上の時点ラベル
    orig_label: str            # 確認事項の「原資料：Xか月」から復元した元ラベル
    apathy_raw: str
    irrit_raw: str
    date: Optional[dt.date]
    date_precision: str
    note: str                  # 確認事項


def read_cog(path: str, sheet: str) -> dict[str, list[CogPoint]]:
    """MMSE / CDR シートを 研究番号 -> [CogPoint] で返す（時点順）"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [s(c) for c in rows[0]]
    out: dict[str, list[CogPoint]] = {}
    for r in rows[1:]:
        pid = s(r[0])
        if not pid:
            continue
        label = s(r[1])
        d, prec = parse_date(r[hdr.index("評価日")])
        if sheet == "MMSE":
            v = to_float(r[hdr.index("合計_原資料記載値")])
            src = "原資料記載値"
            if v is None:
                v = to_float(r[hdr.index("下位項目合計_自動計算")])
                src = "下位項目合計_自動計算" if v is not None else ""
            gl = None
        else:
            v = to_float(r[hdr.index("CDR-SB_原資料記載値")])
            src = "原資料記載値"
            if v is None:
                v = to_float(r[hdr.index("CDR-SB_自動計算")])
                src = "CDR-SB_自動計算" if v is not None else ""
            gl = to_float(r[hdr.index("Global CDR_原資料記載値")])
        out.setdefault(pid, []).append(
            CogPoint(label, v, src, d, prec, gl))
    for pid in out:
        out[pid].sort(key=lambda p: MONTH_LABELS.index(p.label)
                      if p.label in MONTH_LABELS else 99)
    return out


ORIG_LABEL_RE = re.compile(r"原資料\s*[:：]\s*(\d+)\s*か月")


def read_npi(path: str, drug: str) -> dict[str, list[NpiPoint]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["NPI"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [s(c) for c in rows[0]]

    def col(*cands) -> int:
        for c in cands:
            if c in hdr:
                return hdr.index(c)
        for i, h in enumerate(hdr):
            for c in cands:
                if c in h:
                    return i
        raise KeyError(cands)

    i_tp = col("時点", "時点（原票）")
    i_ap = col("アパシー・無関心の有無（NPI第7項目）", "無関心・アパシー有無（NPI項目7）",
               "アパシー")
    i_ir = col("易怒性の有無（NPI第9項目）", "易怒性有無（NPI項目9）", "易怒性")
    i_dt = col("評価日（年月日確定）", "評価日")
    i_raw = col("評価日_原記載", "評価日（原票記載）")
    i_note = col("確認事項")

    out: dict[str, list[NpiPoint]] = {}
    for r in rows[1:]:
        pid = s(r[0])
        if not pid:
            continue
        note = s(r[i_note])
        d, prec = parse_date(r[i_dt])
        if d is None:                       # 評価日が空欄なら原記載を参照
            d, prec = parse_date(r[i_raw])
        m = ORIG_LABEL_RE.search(note)
        orig = f"{m.group(1)}か月" if m else ""
        out.setdefault(pid, []).append(
            NpiPoint(s(r[i_tp]), orig, s(r[i_ap]), s(r[i_ir]), d, prec, note))
    return out


# ---------------------------------------------------------------- NPI 判定

# 判定保留／未記入のうち、確認事項に判定の手がかりがあるもの（参考値として採用可）
# 根拠は 確認事項 欄の記載そのもの。手作業のハードコードではなく下の関数で判定する。
def resolve_npi(raw: str, note: str, item: str) -> tuple[Optional[int], str, str]:
    """NPI の有無欄を (1/0/None, 確度, 根拠) に解決する。
    確度: 'definite' / 'reference'（参考値） / 'excluded'
    """
    if raw in NPI_PRESENT:
        return 1, "definite", ""
    if raw in NPI_ABSENT:
        return 0, "definite", ""
    if raw in NPI_INDETERMINATE:
        # 確認事項に得点の手がかりがあるかを探す（例: 「得点=1の記載あり」）
        m = re.search(r"得点\s*[=＝]\s*(\d+)", note)
        if m and item in note:
            v = int(m.group(1))
            return (1 if v >= 1 else 0), "reference", f"確認事項に「得点={v}」の記載あり"
        m2 = re.search(r"[FfSs]\s*[=＝]\s*(\d+)", note)
        if m2 and item in note:
            return 1, "reference", f"確認事項に頻度/重症度の記載あり（{note[:40]}）"
        return None, "excluded", f"判定不能（{raw}）かつ確認事項に手がかりなし"
    return None, "excluded", f"原票なし／資料未提供（{raw}）"


TRANS = {(1, 0): "あり→なし", (0, 0): "なし→なし",
         (1, 1): "あり→あり", (0, 1): "なし→あり"}


# ---------------------------------------------------------------- 症例構築

@dataclass
class Case:
    pid: str
    drug: str
    # NPI
    npi_bl_label: str = ""
    npi_fu_label: str = ""
    npi_fu_orig_label: str = ""
    npi_bl_date: Optional[dt.date] = None
    npi_fu_date: Optional[dt.date] = None
    npi_bl_date_prec: str = ""
    npi_fu_date_prec: str = ""
    npi_interval_m: Optional[float] = None
    ap_bl: Optional[int] = None
    ap_fu: Optional[int] = None
    ap_conf: str = ""
    ir_bl: Optional[int] = None
    ir_fu: Optional[int] = None
    ir_conf: str = ""
    # 認知機能
    mmse_bl: Optional[float] = None
    mmse_fu: Optional[float] = None
    mmse_fu_label: str = ""
    mmse_bl_date: Optional[dt.date] = None
    mmse_fu_date: Optional[dt.date] = None
    mmse_interval_m: Optional[float] = None
    cdr_bl: Optional[float] = None
    cdr_fu: Optional[float] = None
    cdr_fu_label: str = ""
    cdr_bl_date: Optional[dt.date] = None
    cdr_fu_date: Optional[dt.date] = None
    cdr_interval_m: Optional[float] = None
    # 突合
    match_strategy: str = ""
    npi_fu_to_cog_fu_gap_m: Optional[float] = None
    # 採否
    npi_paired: bool = False     # NPI のベースライン・フォローアップが対で存在する
    needs_review: bool = False   # 日付整合性に要確認事項があり感度解析で除外する
    included: bool = False
    exclude_reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def d_mmse(self):
        if self.mmse_bl is None or self.mmse_fu is None:
            return None
        return round(self.mmse_fu - self.mmse_bl, 1)

    @property
    def d_cdr(self):
        if self.cdr_bl is None or self.cdr_fu is None:
            return None
        return round(self.cdr_fu - self.cdr_bl, 1)

    def trans(self, item: str) -> str:
        bl, fu = (self.ap_bl, self.ap_fu) if item == "ap" else (self.ir_bl, self.ir_fu)
        if bl is None or fu is None:
            return "判定不能"
        return TRANS[(bl, fu)]


BASELINE_LABELS = {"0か月", "初回"}
BASELINE_WINDOW_DAYS = 120   # ラベルが無い行を「ベースライン」と認める日付窓


def first_valued(points: list[CogPoint], label: str) -> Optional[CogPoint]:
    for p in points:
        if p.label == label and p.value is not None:
            return p
    return None


def last_valued(points: list[CogPoint]) -> Optional[CogPoint]:
    cand = [p for p in points if p.value is not None]
    return cand[-1] if cand else None


def build_cases(drug: str, path: str) -> list[Case]:
    npi = read_npi(path, drug)
    mmse = read_cog(path, "MMSE")
    cdr = read_cog(path, "CDR")

    cases: list[Case] = []
    for pid in sorted(npi, key=lambda x: (x[0], int(re.sub(r"\D", "", x) or 0))):
        pts = npi[pid]
        c = Case(pid=pid, drug=drug)

        mm = mmse.get(pid, [])
        cc = cdr.get(pid, [])
        mm_bl = first_valued(mm, "0か月")
        cc_bl = first_valued(cc, "0か月")
        cog_bl_date = (mm_bl.date if mm_bl and mm_bl.date else
                       (cc_bl.date if cc_bl and cc_bl.date else None))

        # --- NPI のベースライン行 / フォローアップ行を決める ---
        usable = [p for p in pts if p.apathy_raw not in NPI_NO_SOURCE
                  or p.irrit_raw not in NPI_NO_SOURCE]
        if not usable:
            c.exclude_reasons.append("[NO_NPI_SOURCE] NPI原票なし（資料未提供／原票なし）")
            cases.append(c)
            continue

        def is_baseline(p: NpiPoint) -> bool:
            if p.label in BASELINE_LABELS:
                return True
            if p.date and cog_bl_date and abs((p.date - cog_bl_date).days) <= BASELINE_WINDOW_DAYS:
                return True
            return False

        bl_cand = [p for p in usable if is_baseline(p)]
        # ベースライン以外のうち最も遅い評価日（無ければ時点ラベルが最も後ろのもの）を最終FUとする
        fu_cand = [p for p in usable if p not in bl_cand]

        if not bl_cand:
            c.exclude_reasons.append(
                "[NO_NPI_BASELINE] NPIベースライン（0か月／初回、または認知機能ベースライン±120日）"
                "に該当する原票なし")
        if not fu_cand:
            c.exclude_reasons.append("[NO_NPI_FOLLOWUP] NPIフォローアップ原票なし（ベースラインのみ）")
        if c.exclude_reasons:
            cases.append(c)
            continue

        bl = min(bl_cand, key=lambda p: (p.date or dt.date(9999, 1, 1)))
        fu = max(fu_cand, key=lambda p: (p.date or dt.date(1, 1, 1)))

        c.npi_bl_label, c.npi_fu_label = bl.label, fu.label
        c.npi_fu_orig_label = fu.orig_label
        c.npi_bl_date, c.npi_bl_date_prec = bl.date, bl.date_precision
        c.npi_fu_date, c.npi_fu_date_prec = fu.date, fu.date_precision
        if bl.date and fu.date:
            c.npi_interval_m = months_between(bl.date, fu.date)

        if bl.date_precision == "month" or fu.date_precision == "month":
            c.flags.append("NPI評価日が年月のみ（当月15日で近似）")
        if fu.orig_label and fu.orig_label != fu.label:
            c.flags.append(f"NPI時点ラベルが統一済み（シート:{fu.label} / 原資料:{fu.orig_label}）")
        if fu.label == "記載なし" and not fu.orig_label:
            c.flags.append("NPIフォローアップの時点ラベル記載なし（評価日で対応付け）")
        if cog_bl_date and bl.date and abs((bl.date - cog_bl_date).days) > BASELINE_WINDOW_DAYS:
            c.flags.append(
                f"NPIベースライン日({bl.date})と認知機能ベースライン日({cog_bl_date})が"
                f"{abs((bl.date-cog_bl_date).days)}日乖離（要確認）")

        # --- NPI 判定 ---
        c.ap_bl, ap_bl_conf, ap_bl_why = resolve_npi(bl.apathy_raw, bl.note, "アパシー")
        c.ap_fu, ap_fu_conf, ap_fu_why = resolve_npi(fu.apathy_raw, fu.note, "アパシー")
        c.ir_bl, ir_bl_conf, ir_bl_why = resolve_npi(bl.irrit_raw, bl.note, "易怒")
        c.ir_fu, ir_fu_conf, ir_fu_why = resolve_npi(fu.irrit_raw, fu.note, "易怒")

        def conf(a, b):
            if "excluded" in (a, b):
                return "excluded"
            return "reference" if "reference" in (a, b) else "definite"

        c.ap_conf = conf(ap_bl_conf, ap_fu_conf)
        c.ir_conf = conf(ir_bl_conf, ir_fu_conf)
        for why in (ap_bl_why, ap_fu_why, ir_bl_why, ir_fu_why):
            if why:
                c.flags.append(why)

        # --- 認知機能の突合 ---
        # NPIフォローアップの評価日はいずれも認知機能の最終評価日より後のため、
        # 「評価日が最も近い認知機能」＝「最終利用可能時点」に一致する。
        # 日付が取れない症例でも同じ定義（最終利用可能時点）を用い、方針を統一する。
        def pick_fu(points: list[CogPoint], bl_point: Optional[CogPoint]):
            cand = [p for p in points if p.value is not None and p is not bl_point]
            if not cand:
                return None
            if fu.date and any(p.date for p in cand):
                dated = [p for p in cand if p.date]
                return min(dated, key=lambda p: abs((p.date - fu.date).days))
            return cand[-1]

        mm_fu = pick_fu(mm, mm_bl)
        cc_fu = pick_fu(cc, cc_bl)

        if mm_bl:
            c.mmse_bl, c.mmse_bl_date = mm_bl.value, mm_bl.date
        if mm_fu:
            c.mmse_fu, c.mmse_fu_label, c.mmse_fu_date = mm_fu.value, mm_fu.label, mm_fu.date
            if mm_bl and mm_bl.date and mm_fu.date:
                c.mmse_interval_m = months_between(mm_bl.date, mm_fu.date)
        if cc_bl:
            c.cdr_bl, c.cdr_bl_date = cc_bl.value, cc_bl.date
        if cc_fu:
            c.cdr_fu, c.cdr_fu_label, c.cdr_fu_date = cc_fu.value, cc_fu.label, cc_fu.date
            if cc_bl and cc_bl.date and cc_fu.date:
                c.cdr_interval_m = months_between(cc_bl.date, cc_fu.date)

        anchor = c.mmse_fu_date or c.cdr_fu_date
        if fu.date and anchor:
            c.npi_fu_to_cog_fu_gap_m = months_between(anchor, fu.date)
            c.match_strategy = "評価日最近接（＝最終利用可能時点）"
        else:
            c.match_strategy = "最終利用可能時点（評価日欠測のため時点ラベル順で決定）"

        if c.mmse_fu is None and c.cdr_fu is None:
            c.exclude_reasons.append("[NO_COG_FOLLOWUP] MMSE・CDRともにフォローアップ値なし（ベースラインのみ）")
        if c.mmse_bl is None and c.cdr_bl is None:
            c.exclude_reasons.append("[NO_COG_BASELINE] MMSE・CDRともにベースライン値なし")

        c.npi_paired = True
        c.needs_review = any("要確認" in f for f in c.flags)
        c.included = not c.exclude_reasons
        cases.append(c)
    return cases


# ---------------------------------------------------------------- 統計

def desc(vals: list[float]) -> str:
    if not vals:
        return "n=0"
    v = sorted(vals)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return f"n={n}, 中央値 {med:g} ［{min(v):g}, {max(v):g}］, 個別値 {', '.join(f'{x:g}' for x in v)}"


def median(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def mw(a: list[float], b: list[float]) -> str:
    """Mann-Whitney U 検定。検定が成立しない／到達可能最小p値が0.05を超える場合はその旨を返す。"""
    if len(a) < 1 or len(b) < 1:
        return "検定不能（いずれかの群が0例）"
    if len(a) < 2 and len(b) < 2:
        return "検定不能（両群とも1例）"
    try:
        u, p = mannwhitneyu(a, b, alternative="two-sided", method="exact")
    except Exception as e:                                  # pragma: no cover
        return f"検定不能（{e}）"
    # 到達可能な最小p値（完全分離時）
    import math
    total = math.comb(len(a) + len(b), len(a))
    pmin = 2.0 / total
    note = ""
    if pmin > 0.05:
        note = f"（この症例数では到達可能な最小p値が{pmin:.3f}であり、有意水準5%に到達しえない）"
    return f"U={u:g}, p={p:.3f}{note}"


# ---------------------------------------------------------------- 群分け定義

GROUPINGS = {
    "A": {
        "name": "定義A（主解析）: 改善群＝「あり→なし」／非改善群＝それ以外すべて",
        "fn": lambda bl, fu: "改善群" if (bl == 1 and fu == 0) else "非改善群",
    },
    "B": {
        "name": "定義B（代替）: 最終時点で症状なし群（あり→なし ＋ なし→なし）／最終時点で症状あり群（あり→あり ＋ なし→あり）",
        "fn": lambda bl, fu: "最終時点なし群" if fu == 0 else "最終時点あり群",
    },
    "C": {
        "name": "定義C（参考）: 新規出現群（なし→あり）／それ以外",
        "fn": lambda bl, fu: "新規出現群" if (bl == 0 and fu == 1) else "それ以外",
    },
}

ITEMS = {"ap": ("NPI第7項目（アパシー・無関心）", "ap_bl", "ap_fu", "ap_conf"),
         "ir": ("NPI第9項目（易怒性）", "ir_bl", "ir_fu", "ir_conf")}


def analysis_set(cases: list[Case], item: str, include_reference: bool,
                 require_cog: bool = True, drop_needs_review: bool = False) -> list[Case]:
    """解析対象集合を返す。
    require_cog=True  : ΔMMSE/ΔCDR-SB が計算できる症例のみ（第3節の群間比較用）
    require_cog=False : NPI が対で揃う症例すべて（第2節の2×2分布用）
    drop_needs_review : 日付整合性に要確認事項のある症例を除外（感度解析）
    """
    _, blk, fuk, confk = ITEMS[item]
    out = []
    for c in cases:
        if require_cog and not c.included:
            continue
        if not require_cog and not c.npi_paired:
            continue
        if drop_needs_review and c.needs_review:
            continue
        if getattr(c, blk) is None or getattr(c, fuk) is None:
            continue
        if getattr(c, confk) == "reference" and not include_reference:
            continue
        out.append(c)
    return out


def crosstab(cases: list[Case], item: str) -> dict[str, list[str]]:
    _, blk, fuk, _ = ITEMS[item]
    tab: dict[str, list[str]] = {k: [] for k in
                                 ("あり→なし", "なし→なし", "あり→あり", "なし→あり")}
    for c in cases:
        tab[TRANS[(getattr(c, blk), getattr(c, fuk))]].append(c.pid)
    return tab


# ---------------------------------------------------------------- 出力

def write_case_table(cases: list[Case], path: str) -> None:
    cols = ["研究番号", "薬剤", "採否", "除外理由",
            "NPI-BL時点", "NPI-BL日", "NPI-FU時点", "NPI-FU原資料時点", "NPI-FU日",
            "NPI間隔(月)",
            "NPI7_BL", "NPI7_FU", "NPI7推移", "NPI7確度",
            "NPI9_BL", "NPI9_FU", "NPI9推移", "NPI9確度",
            "MMSE_BL", "MMSE_FU", "MMSE_FU時点", "ΔMMSE", "MMSE間隔(月)",
            "CDRSB_BL", "CDRSB_FU", "CDRSB_FU時点", "ΔCDR-SB", "CDR間隔(月)",
            "突合方法", "NPI-FUと認知機能FUの日付差(月)", "注記"]
    yn = {1: "あり", 0: "なし", None: "－"}
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in cases:
            w.writerow([
                c.pid, c.drug, "採用" if c.included else "除外",
                " / ".join(c.exclude_reasons),
                c.npi_bl_label, c.npi_bl_date or "", c.npi_fu_label,
                c.npi_fu_orig_label, c.npi_fu_date or "", c.npi_interval_m or "",
                yn[c.ap_bl], yn[c.ap_fu], c.trans("ap"), c.ap_conf,
                yn[c.ir_bl], yn[c.ir_fu], c.trans("ir"), c.ir_conf,
                c.mmse_bl if c.mmse_bl is not None else "",
                c.mmse_fu if c.mmse_fu is not None else "",
                c.mmse_fu_label,
                c.d_mmse if c.d_mmse is not None else "",
                c.mmse_interval_m or "",
                c.cdr_bl if c.cdr_bl is not None else "",
                c.cdr_fu if c.cdr_fu is not None else "",
                c.cdr_fu_label,
                c.d_cdr if c.d_cdr is not None else "",
                c.cdr_interval_m or "",
                c.match_strategy,
                c.npi_fu_to_cog_fu_gap_m if c.npi_fu_to_cog_fu_gap_m is not None else "",
                " / ".join(dict.fromkeys(c.flags)),
            ])


def group_rows(cases: list[Case], item: str, gkey: str) -> list[dict]:
    _, blk, fuk, _ = ITEMS[item]
    fn = GROUPINGS[gkey]["fn"]
    buckets: dict[str, list[Case]] = {}
    for c in cases:
        buckets.setdefault(fn(getattr(c, blk), getattr(c, fuk)), []).append(c)
    rows = []
    for g, cs in buckets.items():
        rows.append({
            "群": g,
            "n": len(cs),
            "症例": ",".join(x.pid for x in cs),
            "dmmse": [x.d_mmse for x in cs if x.d_mmse is not None],
            "dcdr": [x.d_cdr for x in cs if x.d_cdr is not None],
        })
    return rows


def main() -> None:
    all_cases: list[Case] = []
    for drug, path in FILES.items():
        all_cases += build_cases(drug, path)

    write_case_table(all_cases, os.path.join(OUT, "case_detail_all.csv"))

    rep: list[str] = []
    A = rep.append
    A("# NPI第7項目（アパシー）／第9項目（易怒性）の推移と認知機能変化の解析結果\n")
    A(f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n")
    A("ΔMMSE = フォローアップ − ベースライン（プラス＝改善）\n")
    A("ΔCDR-SB = フォローアップ − ベースライン（プラス＝悪化）\n")

    # ---- 1. 症例数フロー
    A("\n## 1. 症例の組み入れフロー\n")
    for drug in FILES:
        cs = [c for c in all_cases if c.drug == drug]
        inc = [c for c in cs if c.included]
        A(f"\n### {drug}\n")
        A(f"- NPIシート掲載 研究番号数: {len(cs)}")
        def by(code):
            return [c for c in cs if any(r.startswith(code) for r in c.exclude_reasons)]
        for code, lab in (("[NO_NPI_SOURCE]", "NPI原票なし（資料未提供／原票なし）"),
                          ("[NO_NPI_BASELINE]", "NPIベースライン該当行なし"),
                          ("[NO_NPI_FOLLOWUP]", "NPIフォローアップ原票なし"),
                          ("[NO_COG_BASELINE]", "認知機能ベースライン値なし"),
                          ("[NO_COG_FOLLOWUP]", "NPIは対あるが認知機能フォローアップ値なし")):
            g = by(code)
            ids = ", ".join(c.pid for c in g)
            A(f"- {lab}で除外: {len(g)}例"
              + (f" （{ids}）" if g and len(g) <= 12 else ""))
        A(f"- **解析対象: {len(inc)}例**（{', '.join(c.pid for c in inc) or 'なし'}）")
        if inc:
            iv = [c.mmse_interval_m for c in inc if c.mmse_interval_m is not None]
            if iv:
                A(f"  - MMSEベースライン〜フォローアップ間隔: 中央値 {median(iv):g}か月 "
                  f"［{min(iv):g}, {max(iv):g}］")
            lbl = {}
            for c in inc:
                lbl[c.mmse_fu_label] = lbl.get(c.mmse_fu_label, 0) + 1
            A(f"  - 認知機能フォローアップ時点の内訳: "
              f"{', '.join(f'{k} {v}例' for k, v in sorted(lbl.items()))}")
            gap = [c.npi_fu_to_cog_fu_gap_m for c in inc
                   if c.npi_fu_to_cog_fu_gap_m is not None]
            if gap:
                A(f"  - NPIフォローアップ日と認知機能フォローアップ日の差: "
                  f"中央値 {median(gap):g}か月 ［{min(gap):g}, {max(gap):g}］"
                  f"（NPIの方が後）")

    # ---- 2. 2x2 分布
    A("\n\n## 2. NPI各項目のベースライン→フォローアップ 2×2分布\n")
    A("対象は NPI のベースライン・フォローアップが対で存在する全症例。")
    A("認知機能のフォローアップ値の有無は問わないため、第3節の解析対象より多い。\n")
    for item, (iname, *_rest) in ITEMS.items():
        A(f"\n### {iname}\n")
        for incref in (False, True):
            tag = "参考値を含む" if incref else "確定判定のみ（主解析）"
            A(f"\n**{tag}**\n")
            A("| 薬剤 | あり→なし | なし→なし | あり→あり | なし→あり | 計 |")
            A("|---|---|---|---|---|---|")
            for drug in list(FILES) + ["プール"]:
                pool = all_cases if drug == "プール" else [c for c in all_cases
                                                        if c.drug == drug]
                aset = analysis_set(pool, item, incref, require_cog=False)
                t = crosstab(aset, item)
                A("| " + drug + " | " + " | ".join(
                    f"{len(t[k])}" + (f" ({','.join(t[k])})" if t[k] else "")
                    for k in ("あり→なし", "なし→なし", "あり→あり", "なし→あり"))
                  + f" | {len(aset)} |")

    # ---- 3. 群別比較
    A("\n\n## 3. 群別の ΔMMSE / ΔCDR-SB 比較\n")
    summary_rows = []
    for item, (iname, *_rest) in ITEMS.items():
        A(f"\n### {iname}\n")
        for gkey in ("A", "B", "C"):
            A(f"\n#### {GROUPINGS[gkey]['name']}\n")
            for drug in list(FILES) + ["プール（追跡期間が異なる点に注意）"]:
                pool = (all_cases if drug.startswith("プール")
                        else [c for c in all_cases if c.drug == drug])
                for incref, dnr in ((False, False), (True, False), (False, True)):
                    aset = analysis_set(pool, item, incref, drop_needs_review=dnr)
                    if not aset:
                        continue
                    tag = ("感度解析: 確定判定のみ＋日付要確認症例を除外" if dnr
                           else ("参考値含む" if incref else "確定判定のみ"))
                    rows = group_rows(aset, item, gkey)
                    if len(rows) < 1:
                        continue
                    A(f"\n**{drug}／{tag}**\n")
                    for r in rows:
                        A(f"- {r['群']} (n={r['n']}: {r['症例']})")
                        A(f"    - ΔMMSE: {desc(r['dmmse'])}")
                        A(f"    - ΔCDR-SB: {desc(r['dcdr'])}")
                    if len(rows) == 2:
                        g1, g2 = rows
                        A(f"    - Mann-Whitney U（ΔMMSE, {g1['群']} vs {g2['群']}）: "
                          f"{mw(g1['dmmse'], g2['dmmse'])}")
                        A(f"    - Mann-Whitney U（ΔCDR-SB, {g1['群']} vs {g2['群']}）: "
                          f"{mw(g1['dcdr'], g2['dcdr'])}")
                        for r in rows:
                            summary_rows.append({
                                "項目": iname, "群分け": gkey, "薬剤": drug,
                                "判定": tag, "群": r["群"], "n": r["n"],
                                "症例": r["症例"],
                                "ΔMMSE中央値": median(r["dmmse"]),
                                "ΔMMSE最小": min(r["dmmse"]) if r["dmmse"] else None,
                                "ΔMMSE最大": max(r["dmmse"]) if r["dmmse"] else None,
                                "ΔMMSE個別値": ";".join(f"{x:g}" for x in sorted(r["dmmse"])),
                                "ΔCDRSB中央値": median(r["dcdr"]),
                                "ΔCDRSB最小": min(r["dcdr"]) if r["dcdr"] else None,
                                "ΔCDRSB最大": max(r["dcdr"]) if r["dcdr"] else None,
                                "ΔCDRSB個別値": ";".join(f"{x:g}" for x in sorted(r["dcdr"])),
                                "MW_ΔMMSE": mw(g1["dmmse"], g2["dmmse"]),
                                "MW_ΔCDRSB": mw(g1["dcdr"], g2["dcdr"]),
                            })
                    else:
                        A("    - 群が1つしか形成されず比較不能")

    with io.open(os.path.join(OUT, "group_summary.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        if summary_rows:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader()
            w.writerows(summary_rows)

    # ---- 4. 除外・採用一覧
    A("\n\n## 4. 除外／採用一覧（全研究番号）\n")
    A("| 研究番号 | 薬剤 | 採否 | 理由・注記 |")
    A("|---|---|---|---|")
    for c in all_cases:
        reason = " / ".join(c.exclude_reasons) if c.exclude_reasons else \
            (" / ".join(dict.fromkeys(c.flags)) or "－")
        A(f"| {c.pid} | {c.drug} | {'採用' if c.included else '除外'} | {reason} |")

    # ---- 5. 症例明細
    A("\n\n## 5. 採用症例の明細\n")
    yn = {1: "あり", 0: "なし", None: "－"}
    A("| 研究番号 | 薬剤 | NPI7 BL→FU | NPI9 BL→FU | MMSE BL→FU (時点) | ΔMMSE | "
      "CDR-SB BL→FU (時点) | ΔCDR-SB | MMSE間隔 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for c in all_cases:
        if not c.included:
            continue
        A(f"| {c.pid} | {c.drug} | {yn[c.ap_bl]}→{yn[c.ap_fu]}"
          f"{'*' if c.ap_conf == 'reference' else ''} | "
          f"{yn[c.ir_bl]}→{yn[c.ir_fu]}{'*' if c.ir_conf == 'reference' else ''} | "
          f"{c.mmse_bl:g}→{c.mmse_fu:g} ({c.mmse_fu_label}) | {c.d_mmse:+g} | "
          f"{c.cdr_bl:g}→{c.cdr_fu:g} ({c.cdr_fu_label}) | {c.d_cdr:+g} | "
          f"{c.mmse_interval_m if c.mmse_interval_m is not None else '不明'}か月 |")
    A("\n\\* 確認事項の記載を根拠とした参考値")

    text = "\n".join(rep)
    with io.open(os.path.join(OUT, "analysis_report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
