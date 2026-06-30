"""
深掘りステップ8: MMSE下位項目は意欲低下(単独)とベースライン/Δで有意差があるか(H-G)

背景: 693検定の総当たり探索(`ALL_PAIRS_SCAN.md` Phase C/D)では、MMSE11下位項目を含む
21変数のベースライン値・Δ(0→18か月)を、精神症状の有無(易怒性・意欲低下を「いずれかあり」
として1群に統合したグループ)とMann-Whitney U検定で比較したが、1件も未補正p<0.05に
達しなかった。しかし`PSYCH_PUBLICATION_CANDIDATE.md` §1で既に指摘した通り、この統合
グループ化は「易怒性・意欲低下のいずれかあり」を1群とするため、**意欲低下に固有の
シグナルが希釈されていた可能性**がある。

別途、`explore_psych_mmse_subitem_specificity.py`(H-E)では、MMSE11下位項目について
0/6/12/18か月パネルを使った混合効果モデルで「time×意欲低下」交互作用(=傾きの違い)を
検定し、すべて非有意だった。本解析(H-G)はそれとは異なる統計的な問い、すなわち
ALL_PAIRS_SCANと同じ「意欲低下の有無で、ベースライン値・18か月時点までのΔが
有意に異なるか」を、意欲低下(単独、易怒性を含まない)群分けで再検定する。
易怒性はN=3で検出力不足のため、2-B・H-D・H-E・H-Fと同じ判断で本解析の対象外とする。

H-G(MMSE11下位項目 × {ベースライン, Δ} × 意欲低下単独、22検定、1ファミリーとして
BH-FDR補正): Mann-Whitney U検定。ALL_PAIRS_SCANと同じ低分散注意フラグ(非モーダル数<5)を
付与し、頑健な新規所見の候補からは低分散注意のつく項目を除外する。FDR補正後に有意かつ
低分散注意のない検定については、leave-one-out感度分析(1症例ずつ除外して再検定)と
置換検定(意欲低下ラベルをシャッフルしB=1000回再検定)で頑健性を確認する。
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
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


MMSE_ITEMS = [
    "時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
    "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写",
]
MEMORY_RELATED = {"記銘", "遅延再生"}

apathy_df = psych.set_index("研究番号")["意欲低下"].astype(float)
apathy_group = apathy_df.apply(lambda v: "あり" if v == 1 else ("なし" if v == 0 else np.nan))
apathy_group = apathy_group.reindex(STUDY_IDS).dropna()


def get_series(col, timepoint):
    d = mmse[mmse["時点"] == timepoint].set_index("研究番号")[col]
    d = pd.to_numeric(d, errors="coerce").dropna()
    return d[d.index.isin(STUDY_IDS)]


baseline = {}
delta = {}
for item in MMSE_ITEMS:
    s0 = get_series(item, "0か月")
    s18 = get_series(item, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    baseline[item] = s0
    delta[item] = (s18.loc[common] - s0.loc[common]).reindex(common)


def n_nonmodal(s):
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


baseline_nonmodal = {a: n_nonmodal(baseline[a]) for a in MMSE_ITEMS}
delta_nonmodal = {a: n_nonmodal(delta[a]) for a in MMSE_ITEMS}


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
    g1 = yv[g == cats[0]]
    g2 = yv[g == cats[1]]
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
        g = group_labels.loc[keep]
        yv = y.loc[keep]
        cats = sorted(g.unique())
        if len(cats) != 2:
            rows.append({"検定": label, "除外症例": sid, "除外後p値": np.nan, "除外後効果量r": np.nan})
            continue
        g1 = yv[g == cats[0]]
        g2 = yv[g == cats[1]]
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
    perm_rs = []
    n_failed = 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(g_vals)
        cats = sorted(set(shuffled))
        g1 = yv[shuffled == cats[0]]
        g2 = yv[shuffled == cats[1]]
        try:
            u, _ = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            r = 1 - (2 * u) / (len(g1) * len(g2))
            perm_rs.append(r)
        except Exception:
            n_failed += 1
            continue
    perm_rs = np.array(perm_rs)
    p_perm = float(np.mean(np.abs(perm_rs) >= np.abs(observed_r))) if len(perm_rs) > 0 else np.nan
    return {"検定": label, "観測効果量r": observed_r, "置換検定p値": p_perm, "n_perm": n_perm, "n_failed": n_failed}


# ===========================================================================
# H-G: MMSE11下位項目 ×{ベースライン,Δ}× 意欲低下(単独群分け) 計22検定
# ===========================================================================
rows = []
for item in MMSE_ITEMS:
    n, u, p, r, glabel = mannwhitney_safe(apathy_group, baseline[item])
    rows.append({
        "検定種別": "ベースライン", "MMSE下位項目": item, "記憶関連項目(事前分類)": item in MEMORY_RELATED,
        "群構成": glabel, "N": n, "統計量(U)": u, "効果量r": r, "p値": p,
        "低分散注意": baseline_nonmodal[item] < FRAGILE_THRESHOLD,
        "非モーダル数": baseline_nonmodal[item],
    })
for item in MMSE_ITEMS:
    n, u, p, r, glabel = mannwhitney_safe(apathy_group, delta[item])
    rows.append({
        "検定種別": "Δ(0→18か月)", "MMSE下位項目": item, "記憶関連項目(事前分類)": item in MEMORY_RELATED,
        "群構成": glabel, "N": n, "統計量(U)": u, "効果量r": r, "p値": p,
        "低分散注意": delta_nonmodal[item] < FRAGILE_THRESHOLD,
        "非モーダル数": delta_nonmodal[item],
    })
hg_df = pd.DataFrame(rows)
valid_hg = hg_df["p値"].notna()
q_hg = pd.Series(np.nan, index=hg_df.index)
if valid_hg.sum() > 0:
    _, qvals, _, _ = multipletests(hg_df.loc[valid_hg, "p値"], method="fdr_bh")
    q_hg.loc[valid_hg] = qvals
hg_df["q値(BH-FDR)"] = q_hg
hg_df.to_csv(f"{OUT}/150_psych_mmse_subitem_apathy_specific.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証: FDR補正後有意 かつ 低分散注意のない検定についてLOO・置換検定
# ===========================================================================
loo_frames = []
perm_rows = []
sig_hg = hg_df[(hg_df["q値(BH-FDR)"] < 0.05) & (~hg_df["低分散注意"])]
for _, r in sig_hg.iterrows():
    item = r["MMSE下位項目"]
    kind = r["検定種別"]
    y = baseline[item] if kind == "ベースライン" else delta[item]
    label = f"{item}({kind}) × 意欲低下"
    loo_frames.append(loo_mannwhitney(apathy_group, y, label))
    perm_rows.append(permutation_mannwhitney(apathy_group, y, r["効果量r"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/151_psych_mmse_subitem_apathy_specific_loo.csv", index=False, encoding="utf-8-sig")

perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/152_psych_mmse_subitem_apathy_specific_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/153_psych_mmse_subitem_apathy_specific_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "hg_n_tests": len(hg_df), "hg_n_tested": int(valid_hg.sum()),
        "n_apathy": int((apathy_group == "あり").sum()), "n_no_apathy": int((apathy_group == "なし").sum()),
        "n_perm": N_PERM, "n_loo_runs": len(loo_df), "n_perm_runs": len(perm_df),
        "fragile_threshold": FRAGILE_THRESHOLD,
        "background": "ALL_PAIRS_SCAN Phase C/D used combined irritability+apathy grouping (42 tests, "
                       "all non-significant); explore_psych_mmse_subitem_specificity.py (H-E) tested "
                       "longitudinal slope interaction (also all non-significant). H-G tests apathy-only "
                       "grouping on baseline/Δ as the remaining untested combination.",
    }, f, ensure_ascii=False, indent=2)

print("=== H-G: MMSE11下位項目 ×{ベースライン,Δ}× 意欲低下(単独群分け) ===")
print(hg_df.to_string(index=False))
if len(loo_df):
    print("\n=== Leave-one-out感度分析(FDR補正後有意・低分散注意なしの検定について) ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")
