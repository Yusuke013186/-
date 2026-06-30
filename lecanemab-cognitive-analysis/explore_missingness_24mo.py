"""
深掘りステップ3-B: 24か月時点での欠測パターン再検証(2-Gの高検出力版)

2-G(`explore_missingness.py`)は18か月時点の欠測(MMSE合計2例・CDR-SB7例など、
きわめて少数)を対象にMNAR(Missing Not At Random)の可能性を検定したが、
欠測群のNが小さすぎて検出力が本質的に不足していた。

データには24か月時点の追跡データも存在し、欠測数は18か月時点よりはるかに
多い(MMSE合計: 33例中17例が欠測 / CDR-SB: 33例中19例が欠測)。本解析は
2-Gと全く同じ検定枠組み(欠測有無 × ベースライン重症度・精神症状)を24か月
時点に適用し、より高い検出力でMNARの可能性を再検証する。

MoCA-J合計は24か月時点でほぼ全例欠測(33例中1例のみ観測)のため、欠測群と
観測群の比較が事実上不可能であり、形式的検定は実施せず参考記録にとどめる。

18か月時点の解析(2-G)とは独立した検定ファミリーとしてBH-FDR補正する
(同じ問いを異なる時点で繰り返しているため、2-Gの結果とプールはしない)。
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


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


# ===========================================================================
# (1) 24か月時点の欠測有無 × ベースライン重症度・精神症状の関連
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


def missing_at_24mo(df, col):
    d24 = df[df["時点"] == "24か月"].set_index("研究番号")[col]
    d24 = pd.to_numeric(d24, errors="coerce")
    has24 = d24.reindex(STUDY_IDS).notna()
    return ~has24  # True = 24か月時点で欠測


missing_flags = {
    "MMSE合計": missing_at_24mo(mmse, "下位項目合計_自動計算"),
    "CDR-SB": missing_at_24mo(cdr, "CDR-SB_自動計算"),
    "Global CDR": missing_at_24mo(cdr, "Global CDR_原資料記載値"),
}
# MoCA-Jは24か月時点でほぼ全例欠測(N観測=1)のため形式検定の対象から除外し、参考記録のみ残す
moca_missing_24 = missing_at_24mo(moca, "合計_原資料記載値")

assoc_rows = []
for sheet_name, miss in missing_flags.items():
    n_missing = int(miss.sum())
    n_present = int((~miss).sum())
    for var_name, series in baseline_vars.items():
        vals = series.reindex(STUDY_IDS)
        g_missing = vals[miss.values].dropna()
        g_present = vals[~miss.values].dropna()
        if len(g_missing) >= 2 and len(g_present) >= 2:
            stat, p = stats.mannwhitneyu(g_missing, g_present, alternative="two-sided")
            assoc_rows.append({
                "24ヶ月欠測対象シート": sheet_name, "ベースライン変数": var_name,
                "N(欠測群)": len(g_missing), "N(観測群)": len(g_present),
                "中央値(欠測群)": g_missing.median(), "中央値(観測群)": g_present.median(),
                "p値(Mann-Whitney U)": p,
            })
        else:
            assoc_rows.append({
                "24ヶ月欠測対象シート": sheet_name, "ベースライン変数": var_name,
                "N(欠測群)": len(g_missing), "N(観測群)": len(g_present),
                "p値(Mann-Whitney U)": np.nan,
            })
    for psych_name, pseries in [("易怒性あり", psych_irritable), ("意欲低下あり", psych_apathy)]:
        pvals = pseries.reindex(STUDY_IDS)
        ct = pd.crosstab(miss.reindex(STUDY_IDS), pvals.reindex(STUDY_IDS))
        if ct.shape == (2, 2):
            odds, p = stats.fisher_exact(ct.values)
            assoc_rows.append({
                "24ヶ月欠測対象シート": sheet_name, "ベースライン変数": psych_name,
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
assoc_df.to_csv(f"{OUT}/90_missingness24_vs_baseline_severity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# (2) 「将来24か月で欠測になる症例」は、それ以前(0→18か月)ですでに悪化が
#     速かったか(=脱落直前の軌跡をMNARの傍証として確認、18か月までの全データを使用)
# ===========================================================================
def early_delta(df, col, t_to=18):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    dT = df[df["時点"] == f"{t_to}か月"].set_index("研究番号")[col]
    d0 = pd.to_numeric(d0, errors="coerce")
    dT = pd.to_numeric(dT, errors="coerce")
    return (dT - d0).reindex(STUDY_IDS)


early_rows = []
for sheet_name, col, df in [
    ("MMSE合計", "下位項目合計_自動計算", mmse),
    ("CDR-SB", "CDR-SB_自動計算", cdr),
    ("Global CDR", "Global CDR_原資料記載値", cdr),
]:
    miss = missing_flags[sheet_name]
    ed = early_delta(df, col, t_to=18)
    g_missing = ed[miss.values].dropna()
    g_present = ed[~miss.values].dropna()
    row = {
        "指標": sheet_name, "N(将来24ヶ月欠測群)": len(g_missing), "N(24ヶ月観測群)": len(g_present),
        "0→18ヶ月Δ中央値(将来欠測群)": g_missing.median() if len(g_missing) else np.nan,
        "0→18ヶ月Δ中央値(24ヶ月観測群)": g_present.median() if len(g_present) else np.nan,
    }
    if len(g_missing) >= 2 and len(g_present) >= 2:
        stat, p = stats.mannwhitneyu(g_missing, g_present, alternative="two-sided")
        row["p値(Mann-Whitney U)"] = p
    else:
        row["p値(Mann-Whitney U)"] = np.nan
        row["備考"] = "欠測群のN<2のため形式的検定は実施せず記述統計のみ"
    early_rows.append(row)
early_df = pd.DataFrame(early_rows)
valid_e = early_df["p値(Mann-Whitney U)"].notna()
q_e = pd.Series(np.nan, index=early_df.index)
if valid_e.sum() > 0:
    _, qvals, _, _ = multipletests(early_df.loc[valid_e, "p値(Mann-Whitney U)"], method="fdr_bh")
    q_e.loc[valid_e] = qvals
early_df["q値(BH-FDR)"] = q_e
early_df.to_csv(f"{OUT}/91_early_trajectory_before_24mo_dropout.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/92_missingness24_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_missing_at_24mo": {k: int(v.sum()) for k, v in missing_flags.items()},
        "n_total_subjects": len(STUDY_IDS),
        "moca_n_observed_at_24mo": int((~moca_missing_24).sum()),
        "note_moca": "MoCA-J合計は24か月時点で観測群N=1のため形式検定対象外(参考記録のみ)",
    }, f, ensure_ascii=False, indent=2)

print("=== 24か月時点欠測の症例数 ===")
for k, v in missing_flags.items():
    print(f"  {k}: 欠測{int(v.sum())}例 / 観測{int((~v).sum())}例 (全{len(STUDY_IDS)}例)")
print(f"  MoCA-J合計: 欠測{int(moca_missing_24.sum())}例 / 観測{int((~moca_missing_24).sum())}例 (形式検定対象外)")

print("\n=== 24か月欠測 × ベースライン重症度・精神症状の関連(2-Gより高検出力) ===")
print(assoc_df.to_string(index=False))

print("\n=== 将来24か月で欠測になる症例は、それ以前(0→18か月)ですでに悪化が速かったか ===")
print(early_df.to_string(index=False))
