# -*- coding: utf-8 -*-
"""共通のデータ読み込み・群定義・作図設定"""
import pandas as pd, numpy as np, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

XLSX = "レカネマブ研究_L1-66_白青交互配色_修正版_v19.xlsx"
OUT = pathlib.Path("output"); OUT.mkdir(exist_ok=True)
FIG = OUT / "figures"; FIG.mkdir(exist_ok=True)

# --- 日本語フォント（IPAGothic） ---
for cand in ["/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
             "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]:
    if pathlib.Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        break
JP = "IPAGothic"

# --- 結果1/結果5と統一するデザイン設定（装飾なし・白背景） ---
plt.rcParams.update({
    "font.family": JP,
    "font.size": 12,
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "axes.edgecolor": "#888888",
    "axes.linewidth": 1.0,
    "axes.grid": True,
    "grid.color": "#E1E0D9",
    "grid.linestyle": "--",
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": "#000000",
    "ytick.color": "#000000",
    "axes.labelcolor": "#000000",
    "text.color": "#000000",
    "legend.frameon": False,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
})

# 指示書タスク②-1の指定：訴えあり＝赤 / 訴えなし＝青
C_ARI  = "#C00000"   # 赤：改善訴えあり (n=9)
C_NASI = "#2E75B6"   # 青：改善訴えなし (n=20)

TP_LABELS = ["0か月", "6か月", "12か月", "18か月"]
TP_MONTHS = [0, 6, 12, 18]

MMSE_SUBITEMS = ["時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
                 "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写"]
MMSE_SUB_MAX  = {"時間見当識": 5, "場所見当識": 5, "物品呼称": 2, "記銘": 3, "注意計算": 5,
                 "遅延再生": 3, "復唱": 1, "読字理解": 1, "3段階命令": 3, "書字": 1, "図形模写": 1}
CDR_DOMAINS = ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]

CLAIM_COL = "レカネマブ投与後に何らかの症状改善の訴えあり"


def load_all():
    mmse = pd.read_excel(XLSX, sheet_name="MMSE")
    cdr  = pd.read_excel(XLSX, sheet_name="CDR")
    moca = pd.read_excel(XLSX, sheet_name="MoCA-J")
    psy  = pd.read_excel(XLSX, sheet_name="精神症状")
    return mmse, cdr, moca, psy


def define_groups(mmse, psy):
    """指示書の定義：18か月MMSE実測値あり × 訴えフラグ → n=9 / n=20"""
    m18 = mmse[(mmse["時点"] == "18か月") & (mmse["合計_原資料記載値"].notna())]
    ids18 = set(m18["研究番号"])
    p = psy.set_index("研究番号")
    key = lambda s: int(str(s)[1:])
    ari  = sorted([i for i in ids18 if p.loc[i, CLAIM_COL] == "あり"], key=key)
    nasi = sorted([i for i in ids18 if p.loc[i, CLAIM_COL] == "記載なし"], key=key)
    assert len(ari) == 9 and len(nasi) == 20, f"群定義が再現しません: {len(ari)}/{len(nasi)}"
    grp = {i: "訴えあり" for i in ari}
    grp.update({i: "訴えなし" for i in nasi})
    return ari, nasi, grp


def wide_scores(df, value_col, ids):
    """縦型 → 研究番号 × 時点 のワイド表"""
    d = df[df["研究番号"].isin(ids) & df["時点"].isin(TP_LABELS)]
    w = d.pivot_table(index="研究番号", columns="時点", values=value_col, aggfunc="first")
    return w.reindex(index=ids, columns=TP_LABELS)


def mean_ci(vals, conf=0.95):
    """平均値と95%CI半幅（t分布）。n<2 は CI を NaN。"""
    from scipy import stats
    v = np.asarray([x for x in vals if pd.notna(x)], dtype=float)
    n = len(v)
    if n == 0:
        return np.nan, np.nan, 0
    m = v.mean()
    if n < 2:
        return m, np.nan, n
    se = v.std(ddof=1) / np.sqrt(n)
    h = se * stats.t.ppf(0.5 + conf / 2, n - 1)
    return m, h, n
