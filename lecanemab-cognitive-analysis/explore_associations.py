"""
追加の探索的解析（事後にユーザーから依頼された仮説生成的な関連性の検討）

問1: 精神症状（易怒性 or 意欲低下）の併存の有無と、MMSE「注意計算」の
     0→18か月の変化に関連はあるか。
問2: MMSE「注意計算」の変化と、CDR下位領域「家庭・趣味」の変化に関連はあるか。

注意:
- これは事前に規定した主要解析（REPORT.md）とは別の、事後的な探索的解析である。
- 精神症状データは時点情報がなく「全体」評価のため、0か月時点の状態を必ずしも
  表していない。時間的前後関係は確認できず、関連の有無のみを検討する。
- サンプルサイズが小さい（最大27〜31例、症状サブグループはさらに小さい）ため、
  統計的に有意であっても臨床的解釈は慎重に行うべき仮説生成的所見である。
- 主要解析の21検定ファミリーには含めず、別ファミリーとして扱う（多重比較補正なし、
  検定数が少なく対象も主要解析と異なるため）。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats

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
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def get_paired(df, col):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    paired = [
        sid for sid in STUDY_IDS
        if sid in d0.index and sid in d18.index and pd.notna(d0.loc[sid]) and pd.notna(d18.loc[sid])
    ]
    return pd.Series(d0.loc[paired].astype(float).values, index=paired), \
           pd.Series(d18.loc[paired].astype(float).values, index=paired)


calc0, calc18 = get_paired(mmse, "注意計算")
home0, home18 = get_paired(cdr, "家庭・趣味")

calc_diff = (calc18 - calc0).rename("Δ注意計算")
home_diff = (home18 - home0).rename("Δ家庭・趣味")

psych_df = psych.set_index("研究番号")
psych_group = psych_df.apply(
    lambda r: "あり(易怒性 or 意欲低下)" if r["両方なし"] == 0 else "なし(両方なし)", axis=1
).rename("精神症状")

# ===========================================================================
# 問1: 精神症状の有無 × Δ注意計算（独立2群、Mann-Whitney U検定）
# ===========================================================================
df1 = pd.concat([calc0.rename("0か月_注意計算"), calc18.rename("18か月_注意計算"), calc_diff, psych_group], axis=1).dropna()
group_yes = df1[df1["精神症状"] == "あり(易怒性 or 意欲低下)"]
group_no = df1[df1["精神症状"] == "なし(両方なし)"]

u_stat, u_p = stats.mannwhitneyu(group_yes["Δ注意計算"], group_no["Δ注意計算"], alternative="two-sided")
n1, n2 = len(group_yes), len(group_no)
rb_effect = 1 - (2 * u_stat) / (n1 * n2)  # rank-biserial effect size for Mann-Whitney

# 内訳（易怒性のみ／意欲低下のみ／両方なし）も参考として記述
breakdown = []
for cat in ["易怒性", "意欲低下", "両方なし"]:
    sub = df1[psych_df.loc[df1.index, cat] == 1]
    if len(sub):
        q1, q3 = np.percentile(sub["Δ注意計算"], [25, 75])
        breakdown.append({
            "精神症状カテゴリ": cat, "N": len(sub),
            "Δ注意計算_中央値": np.median(sub["Δ注意計算"]),
            "Δ注意計算_IQR": f"{q1:.2f}-{q3:.2f}",
        })
breakdown_df = pd.DataFrame(breakdown)

q1y, q3y = np.percentile(group_yes["Δ注意計算"], [25, 75])
q1n, q3n = np.percentile(group_no["Δ注意計算"], [25, 75])
result1 = pd.DataFrame([
    {
        "比較": "精神症状あり vs なし（Δ注意計算）",
        "N(あり)": n1, "N(なし)": n2,
        "中央値Δ(あり)": np.median(group_yes["Δ注意計算"]), "IQR(あり)": f"{q1y:.2f}-{q3y:.2f}",
        "中央値Δ(なし)": np.median(group_no["Δ注意計算"]), "IQR(なし)": f"{q1n:.2f}-{q3n:.2f}",
        "検定": "Mann-Whitney U", "U統計量": u_stat, "p値": u_p,
        "効果量(rank-biserial r)": rb_effect,
    }
])

# ベースライン(0か月)時点で両群が同等かの参考チェック（交絡確認）
u_b, p_b = stats.mannwhitneyu(group_yes["0か月_注意計算"], group_no["0か月_注意計算"], alternative="two-sided")
baseline_check = pd.DataFrame([
    {"比較": "精神症状あり vs なし（0か月時点の注意計算、交絡確認用）",
     "N(あり)": n1, "N(なし)": n2,
     "中央値(あり)": np.median(group_yes["0か月_注意計算"]),
     "中央値(なし)": np.median(group_no["0か月_注意計算"]),
     "検定": "Mann-Whitney U", "U統計量": u_b, "p値": p_b}
])

# ===========================================================================
# 問2: Δ注意計算 と Δ家庭・趣味 の関連（Spearman相関 + 2x2クロス集計）
# ===========================================================================
df2 = pd.concat([calc_diff, home_diff], axis=1).dropna()
rho, rho_p = stats.spearmanr(df2["Δ注意計算"], df2["Δ家庭・趣味"])

calc_worse = df2["Δ注意計算"] < 0       # 注意計算が低下
home_worse = df2["Δ家庭・趣味"] > 0      # 家庭・趣味が悪化（CDRはスコア増加が悪化）

cross_tab = pd.crosstab(
    calc_worse.map({True: "注意計算 低下", False: "注意計算 維持/改善"}),
    home_worse.map({True: "家庭・趣味 悪化", False: "家庭・趣味 維持/改善"}),
)
fisher_odds, fisher_p = stats.fisher_exact(cross_tab.values)

result2_corr = pd.DataFrame([
    {"比較": "Δ注意計算 と Δ家庭・趣味（Spearman相関）", "N": len(df2),
     "Spearman rho": rho, "p値": rho_p}
])

# ===========================================================================
# 出力
# ===========================================================================
result1.to_csv(f"{OUT}/07_assoc_psych_vs_calc.csv", index=False, encoding="utf-8-sig")
breakdown_df.to_csv(f"{OUT}/07b_assoc_psych_vs_calc_breakdown.csv", index=False, encoding="utf-8-sig")
baseline_check.to_csv(f"{OUT}/07c_assoc_psych_vs_calc_baseline_check.csv", index=False, encoding="utf-8-sig")
result2_corr.to_csv(f"{OUT}/08_assoc_calc_vs_home.csv", index=False, encoding="utf-8-sig")
cross_tab.to_csv(f"{OUT}/08b_assoc_calc_vs_home_crosstab.csv", encoding="utf-8-sig")

with open(f"{OUT}/08c_assoc_calc_vs_home_fisher.json", "w", encoding="utf-8") as f:
    json.dump({"odds_ratio": fisher_odds, "p_value": fisher_p, "n": len(df2)}, f, ensure_ascii=False, indent=2)

print("=== 問1: 精神症状の有無 × Δ注意計算 ===")
print(result1.to_string(index=False))
print("\n--- 内訳(参考) ---")
print(breakdown_df.to_string(index=False))
print("\n--- ベースライン交絡確認 ---")
print(baseline_check.to_string(index=False))

print("\n=== 問2: Δ注意計算 と Δ家庭・趣味 ===")
print(result2_corr.to_string(index=False))
print("\nクロス集計:")
print(cross_tab)
print(f"\nFisher's exact test: odds ratio={fisher_odds:.3f}, p={fisher_p:.4f}, N={len(df2)}")
