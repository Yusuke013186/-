"""
深掘りステップ11: 尺度合計スコア×意欲低下(単独)のベースライン・Δ比較(H-J)

背景: これまでの精神症状関連解析の棚卸し:
  - ALL_PAIRS_SCAN Phase C/D: 尺度合計含む21変数×精神症状(易怒性・意欲低下「いずれかあり」
    統合)を Mann-Whitney で比較 → 42検定すべて未補正p<0.05に届かず
  - 2-B(effect modification): MMSE合計/CDR-SB/GlobalCDR×意欲低下の時間交互作用 →
    CDR-SBのみ有意(q=0.0084, LOO・置換検定で頑健)
  - H-D: CDR6下位領域×意欲低下(単独)のΔ比較 → 記憶がFDR有意だが置換検定非有意(不採用)
  - H-G: MMSE11下位項目×意欲低下(単独)のベースライン・Δ比較 → 全件非有意

未検定の組み合わせ: 「尺度合計スコア(CDR-SB・MMSE合計・GlobalCDR・MoCA-J合計)×
意欲低下(単独群分け)のベースライン値・Δ」を Mann-Whitney U で比較する H-J。
Phase C/D は統合群、H-D・H-G は下位項目、H-J は尺度合計×意欲低下単独という、
論理的に埋まっていなかった組み合わせである。

H-J(8検定、1ファミリーとしてBH-FDR補正):
  4尺度(CDR-SB・MMSE合計・GlobalCDR・MoCA-J合計) × 2比較(ベースライン、Δ0→18か月)。
  易怒性はN=3で検出力不足のため除外(H-D・H-E・H-F・H-G・H-Iと同じ判断)。
  低分散注意フラグ(非モーダル数<5)を付与し、FDR補正後有意かつ低分散注意なしの検定に
  ついてLeave-one-out感度分析と置換検定(B=1000)で頑健性を確認する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_PERM = 1000
FRAGILE_THRESHOLD = 5

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    return pd.DataFrame(rows[1:], columns=rows[0])


mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")
moca = sheet_to_df("MoCA-J")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


apathy_df = psych.set_index("研究番号")["意欲低下"].astype(float)
apathy_group = apathy_df.apply(lambda v: "あり" if v == 1 else ("なし" if v == 0 else np.nan))
apathy_group = apathy_group.reindex(STUDY_IDS).dropna()

n_apathy = int((apathy_group == "あり").sum())
n_no_apathy = int((apathy_group == "なし").sum())

SCALES = [
    ("CDR",  "CDR-SB_自動計算",        "CDR-SB"),
    ("CDR",  "Global CDR_原資料記載値", "GlobalCDR"),
    ("MMSE", "合計_原資料記載値",       "MMSE合計"),
    ("MoCA-J", "合計_原資料記載値",    "MoCA-J合計"),
]

SHEET_MAP = {"CDR": cdr, "MMSE": mmse, "MoCA-J": moca}


def get_series(sheet_name, col, timepoint):
    df = SHEET_MAP[sheet_name]
    d = df[df["時点"] == timepoint].set_index("研究番号")[col]
    d = pd.to_numeric(d, errors="coerce").dropna()
    return d[d.index.isin(STUDY_IDS)]


def n_nonmodal(s):
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


def mannwhitney_safe(group_labels, y):
    common = sort_ids(set(group_labels.index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan, np.nan, np.nan
    g = group_labels.loc[common]
    yv = y.loc[common]
    cats = sorted(g.unique())
    if len(cats) != 2:
        return n, np.nan, np.nan, np.nan, np.nan
    g1, g2 = yv[g == cats[0]], yv[g == cats[1]]
    if len(g1) < 2 or len(g2) < 2:
        return n, np.nan, np.nan, np.nan, np.nan
    if np.unique(yv.values).size == 1:
        return n, np.nan, np.nan, np.nan, np.nan
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    r = 1 - (2 * u) / (len(g1) * len(g2))
    return n, u, p, r, f"{cats[0]}(N={len(g1)}) vs {cats[1]}(N={len(g2)})"


def loo_mannwhitney(group_labels, y, label):
    common = sort_ids(set(group_labels.index) & set(y.index))
    rows = []
    for sid in common:
        keep = [s for s in common if s != sid]
        g, yv = group_labels.loc[keep], y.loc[keep]
        cats = sorted(g.unique())
        if len(cats) != 2:
            rows.append({"検定": label, "除外症例": sid, "除外後p値": np.nan, "除外後効果量r": np.nan})
            continue
        g1, g2 = yv[g == cats[0]], yv[g == cats[1]]
        try:
            u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            r = 1 - (2 * u) / (len(g1) * len(g2))
        except Exception:
            p = r = np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後p値": p, "除外後効果量r": r})
    return pd.DataFrame(rows)


def permutation_mannwhitney(group_labels, y, observed_r, label, n_perm=N_PERM):
    common = sort_ids(set(group_labels.index) & set(y.index))
    g_vals = group_labels.loc[common].values
    yv = y.loc[common].values
    perm_rs, n_failed = [], 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(g_vals)
        cats = sorted(set(shuffled))
        g1, g2 = yv[shuffled == cats[0]], yv[shuffled == cats[1]]
        try:
            u, _ = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            perm_rs.append(1 - (2 * u) / (len(g1) * len(g2)))
        except Exception:
            n_failed += 1
    perm_rs = np.array(perm_rs)
    p_perm = float(np.mean(np.abs(perm_rs) >= np.abs(observed_r))) if len(perm_rs) > 0 else np.nan
    return {"検定": label, "観測効果量r": observed_r, "置換検定p値": p_perm,
            "n_perm": n_perm, "n_failed": n_failed}


# ===========================================================================
# H-J: 尺度合計 × 意欲低下(単独) ベースライン・Δ 8検定
# ===========================================================================
rows = []
for sheet, col, label in SCALES:
    s0 = get_series(sheet, col, "0か月")
    s18 = get_series(sheet, col, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    delta = (s18.loc[common] - s0.loc[common]).reindex(common)

    for kind, y, nm_key in [
        ("ベースライン", s0, n_nonmodal(s0)),
        ("Δ(0→18か月)", delta, n_nonmodal(delta)),
    ]:
        n, u, p, r, glabel = mannwhitney_safe(apathy_group, y)
        rows.append({
            "尺度": label, "比較種別": kind, "群構成": glabel, "N": n,
            "統計量(U)": u, "効果量r": r, "p値": p,
            "低分散注意": nm_key < FRAGILE_THRESHOLD, "非モーダル数": nm_key,
        })

hj_df = pd.DataFrame(rows)
valid = hj_df["p値"].notna()
q = pd.Series(np.nan, index=hj_df.index)
if valid.sum() > 0:
    _, qvals, _, _ = multipletests(hj_df.loc[valid, "p値"], method="fdr_bh")
    q.loc[valid] = qvals
hj_df["q値(BH-FDR)"] = q
hj_df.to_csv(f"{OUT}/180_psych_scale_totals_apathy.csv", index=False, encoding="utf-8-sig")

print(f"=== H-J: 尺度合計×意欲低下(単独) {len(hj_df)}検定、BH-FDR補正 ===")
print(f"意欲低下あり: N={n_apathy}、なし: N={n_no_apathy}")
print()
print(hj_df.to_string(index=False))

# ===========================================================================
# 頑健性検証: FDR補正後有意 かつ 低分散注意のない検定
# ===========================================================================
loo_frames, perm_rows = [], []
sig = hj_df[(hj_df["q値(BH-FDR)"] < 0.05) & (~hj_df["低分散注意"])]
for _, r in sig.iterrows():
    sheet_name = "CDR" if "CDR" in r["尺度"] or "Global" in r["尺度"] else (
        "MoCA-J" if "MoCA" in r["尺度"] else "MMSE")
    col_map = {"CDR-SB": "CDR-SB_自動計算", "GlobalCDR": "Global CDR_原資料記載値",
               "MMSE合計": "合計_原資料記載値", "MoCA-J合計": "合計_原資料記載値"}
    col = col_map[r["尺度"]]
    s0 = get_series(sheet_name, col, "0か月")
    s18 = get_series(sheet_name, col, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    delta = (s18.loc[common] - s0.loc[common]).reindex(common)
    y = s0 if r["比較種別"] == "ベースライン" else delta
    label = f"{r['尺度']}({r['比較種別']}) × 意欲低下"
    loo_frames.append(loo_mannwhitney(apathy_group, y, label))
    perm_rows.append(permutation_mannwhitney(apathy_group, y, r["効果量r"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/181_psych_scale_totals_apathy_loo.csv", index=False, encoding="utf-8-sig")
if len(perm_df):
    perm_df.to_csv(f"{OUT}/182_psych_scale_totals_apathy_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/183_psych_scale_totals_apathy_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_tests": len(hj_df), "n_tested": int(valid.sum()),
        "n_apathy": n_apathy, "n_no_apathy": n_no_apathy,
        "n_perm": N_PERM, "n_loo_runs": len(loo_df), "n_perm_runs": len(perm_df),
        "background": "Phase C/D: combined psych group, all non-significant. "
                      "2-B: CDR-SB time×apathy interaction significant. "
                      "H-D: CDR subdomains Δ × apathy — 記憶 FDR-sig but permutation failed. "
                      "H-G: MMSE subitems baseline/Δ × apathy — all non-significant. "
                      "H-J fills the gap: scale totals × apathy-only, baseline+Δ Mann-Whitney.",
    }, f, ensure_ascii=False, indent=2)

if len(loo_df):
    print("\n=== Leave-one-out感度分析 ===")
    print(loo_df.to_string(index=False))
    n_sig = (loo_df["除外後p値"] < 0.05).sum()
    n_total = len(loo_df)
    print(f"\n→ {n_sig}/{n_total}回でp<0.05を維持")
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")
