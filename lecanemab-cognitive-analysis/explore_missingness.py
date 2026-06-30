"""
ステップ2-G: 欠測パターン分析(MNARの可能性チェック)

これまでの全解析(REPORT.md〜explore_partial_corr_network.py)は、0か月・18か月
両方の値がある症例のみを使う「完全ケース解析(complete case analysis)」を
前提としてきた。この前提が成り立つのは、欠測が観測変数と無関係に生じている
場合(MCAR/MAR)に限られる。もし「重症な患者ほど18か月時点で脱落しやすい」
といった構造(MNAR: Missing Not At Random)があれば、完全ケース解析の結果には
偏り(生存者バイアス)が生じている可能性がある。

本解析では、18か月時点で値が欠測している症例が、ベースライン重症度や
精神症状の有無と関連するかを検定する。欠測症例数は数例程度ときわめて
少ないため、検出力は本質的に低く、形式的検定はほぼ「参考」にしかならない
点を明記した上で、記述統計と合わせて報告する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")
moca = sheet_to_df("MoCA-J")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


# ===========================================================================
# (1) 症例ごとの観測時点数の分布(0/6/12/18か月のうち何時点に値があるか)
# ===========================================================================
def n_timepoints_observed(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    counts = sub.groupby("研究番号")["時点"].nunique()
    return counts.reindex(STUDY_IDS).fillna(0).astype(int)


obs_counts = pd.DataFrame({
    "MMSE合計_観測時点数": n_timepoints_observed(mmse, "下位項目合計_自動計算"),
    "CDR-SB_観測時点数": n_timepoints_observed(cdr, "CDR-SB_自動計算"),
    "MoCA-J合計_観測時点数": n_timepoints_observed(moca, "合計_原資料記載値"),
}, index=STUDY_IDS)
obs_counts.index.name = "研究番号"
obs_counts.to_csv(f"{OUT}/60_observed_timepoint_counts_per_subject.csv", encoding="utf-8-sig")

dist_rows = []
for col in obs_counts.columns:
    vc = obs_counts[col].value_counts().sort_index()
    for n_tp, cnt in vc.items():
        dist_rows.append({"指標": col, "観測時点数": n_tp, "症例数": cnt})
dist_df = pd.DataFrame(dist_rows)
dist_df.to_csv(f"{OUT}/61_timepoint_count_distribution.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# (2) 18か月時点の欠測有無 × ベースライン重症度・精神症状の関連
# ===========================================================================
mmse_base = mmse[mmse["時点"] == "0か月"].set_index("研究番号")["下位項目合計_自動計算"].astype(float)
cdr_base = cdr[cdr["時点"] == "0か月"].set_index("研究番号")["CDR-SB_自動計算"].astype(float)
global_cdr_base = cdr[cdr["時点"] == "0か月"].set_index("研究番号")["Global CDR_原資料記載値"].astype(float)
moca_base = moca[moca["時点"] == "0か月"].set_index("研究番号")["合計_原資料記載値"].astype(float)
psych_irritable = psych.set_index("研究番号")["易怒性"]
psych_apathy = psych.set_index("研究番号")["意欲低下"]

baseline_vars = {
    "MMSE合計(ベースライン)": mmse_base,
    "CDR-SB(ベースライン)": cdr_base,
    "Global CDR(ベースライン)": global_cdr_base,
    "MoCA-J合計(ベースライン)": moca_base,
}


def missing_at_18mo(df, col):
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    d18 = pd.to_numeric(d18, errors="coerce")
    has18 = d18.reindex(STUDY_IDS).notna()
    return ~has18  # True = 18か月時点で欠測


missing_flags = {
    "MMSE合計": missing_at_18mo(mmse, "下位項目合計_自動計算"),
    "CDR-SB": missing_at_18mo(cdr, "CDR-SB_自動計算"),
    "MoCA-J合計": missing_at_18mo(moca, "合計_原資料記載値"),
}

assoc_rows = []
for sheet_name, miss in missing_flags.items():
    n_missing = int(miss.sum())
    n_present = int((~miss).sum())
    for var_name, series in baseline_vars.items():
        vals = series.reindex(STUDY_IDS)
        g_missing = vals[miss.values]
        g_present = vals[~miss.values]
        g_missing = g_missing.dropna()
        g_present = g_present.dropna()
        if len(g_missing) >= 2 and len(g_present) >= 2:
            stat, p = stats.mannwhitneyu(g_missing, g_present, alternative="two-sided")
            assoc_rows.append({
                "18ヶ月欠測対象シート": sheet_name, "ベースライン変数": var_name,
                "N(欠測群)": len(g_missing), "N(観測群)": len(g_present),
                "中央値(欠測群)": g_missing.median(), "中央値(観測群)": g_present.median(),
                "p値(Mann-Whitney U)": p,
            })
        else:
            assoc_rows.append({
                "18ヶ月欠測対象シート": sheet_name, "ベースライン変数": var_name,
                "N(欠測群)": len(g_missing), "N(観測群)": len(g_present),
                "p値(Mann-Whitney U)": np.nan,
            })
    for psych_name, pseries in [("易怒性あり", psych_irritable), ("意欲低下あり", psych_apathy)]:
        pvals = pseries.reindex(STUDY_IDS)
        ct = pd.crosstab(miss.reindex(STUDY_IDS), pvals.reindex(STUDY_IDS))
        if ct.shape == (2, 2):
            odds, p = stats.fisher_exact(ct.values)
            assoc_rows.append({
                "18ヶ月欠測対象シート": sheet_name, "ベースライン変数": psych_name,
                "N(欠測群)": n_missing, "N(観測群)": n_present,
                "p値(Fisher正確検定)": p,
            })

assoc_df = pd.DataFrame(assoc_rows)
pcol_mw = "p値(Mann-Whitney U)"
pcol_fe = "p値(Fisher正確検定)"
all_p = assoc_df[pcol_mw].combine_first(assoc_df[pcol_fe]) if pcol_fe in assoc_df.columns else assoc_df[pcol_mw]
valid_p = all_p.notna()
q_all = pd.Series(np.nan, index=assoc_df.index)
if valid_p.sum() > 0:
    _, qvals, _, _ = multipletests(all_p[valid_p], method="fdr_bh")
    q_all.loc[valid_p] = qvals
assoc_df["統合p値"] = all_p
assoc_df["q値(BH-FDR)"] = q_all
assoc_df.to_csv(f"{OUT}/62_missingness_vs_baseline_severity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# (3) 「将来18か月で欠測になる症例」は、それ以前の時点(0→12か月)で
#     すでに悪化が速かったか(=脱落直前の軌跡をMNARの傍証として確認)
# ===========================================================================
def early_delta(df, col, t_to=12):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    dT = df[df["時点"] == f"{t_to}か月"].set_index("研究番号")[col]
    d0 = pd.to_numeric(d0, errors="coerce")
    dT = pd.to_numeric(dT, errors="coerce")
    return (dT - d0).reindex(STUDY_IDS)


early_rows = []
for sheet_name, col, df in [("MMSE合計", "下位項目合計_自動計算", mmse), ("CDR-SB", "CDR-SB_自動計算", cdr)]:
    miss = missing_flags[sheet_name]
    ed = early_delta(df, col, t_to=12)
    g_missing = ed[miss.values].dropna()
    g_present = ed[~miss.values].dropna()
    row = {
        "指標": sheet_name, "N(将来18ヶ月欠測群)": len(g_missing), "N(18ヶ月観測群)": len(g_present),
        "0→12ヶ月Δ中央値(将来欠測群)": g_missing.median() if len(g_missing) else np.nan,
        "0→12ヶ月Δ中央値(18ヶ月観測群)": g_present.median() if len(g_present) else np.nan,
    }
    if len(g_missing) >= 2 and len(g_present) >= 2:
        stat, p = stats.mannwhitneyu(g_missing, g_present, alternative="two-sided")
        row["p値(Mann-Whitney U)"] = p
    else:
        row["p値(Mann-Whitney U)"] = np.nan
        row["備考"] = "欠測群のN<2のため形式的検定は実施せず記述統計のみ"
    early_rows.append(row)
early_df = pd.DataFrame(early_rows)
early_df.to_csv(f"{OUT}/63_early_trajectory_before_dropout.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/64_missingness_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_missing_at_18mo": {k: int(v.sum()) for k, v in missing_flags.items()},
        "n_total_subjects": len(STUDY_IDS),
    }, f, ensure_ascii=False, indent=2)

print("=== 症例ごとの観測時点数の分布 ===")
print(dist_df.to_string(index=False))

print("\n=== 18か月時点欠測の症例数 ===")
for k, v in missing_flags.items():
    print(f"  {k}: 欠測{int(v.sum())}例 / 観測{int((~v).sum())}例 (全{len(STUDY_IDS)}例)")

print("\n=== 18か月欠測 × ベースライン重症度・精神症状の関連(探索的・低検出力) ===")
print(assoc_df.to_string(index=False))

print("\n=== 将来18か月で欠測になる症例は、それ以前(0→12か月)ですでに悪化が速かったか ===")
print(early_df.to_string(index=False))
