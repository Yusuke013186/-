"""
ステップ2-D: 患者の軌跡クラスタリング

これまでの全解析(REPORT.md以降)は33症例を単一の集団として扱い、
「平均的にどう変化するか」を検定してきた。しかし実際には「急速に悪化する
患者群」と「ほぼ横ばいの患者群」のような異質なサブグループが混在している
可能性があり、平均値だけではこれを検出できない。

本解析では、症例ごとにMMSE合計・CDR-SBの時間的変化の傾き(slope)を
個別に推定し、その2次元空間でクラスタリングすることで、患者タイプの違いが
存在するかを探索する。2-C(explore_nonlinear.py)で使った0/6/12/18か月の
繰り返し測定パネルを再利用する。

頑健性の検証として:
  (1) 階層的クラスタリング(Ward法)とk-meansという2つの異なる手法で
      同様のクラスタ構造が得られるか(Adjusted Rand Index)
  (2) ブートストラップ再標本化でクラスタ所属がどれだけ安定しているか
      (Adjusted Rand Index)
を確認し、いずれかが低ければ「データに支持されたクラスタではなく、
アルゴリズムが機械的に分割しただけ」と判断する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score, adjusted_rand_score
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)

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


def build_panel(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


def per_subject_slope(panel, min_points=3):
    """各症例について、最小二乗法でscore ~ timeの傾きを個別推定する。
    時点数が min_points 未満の症例は信頼できる傾き推定ができないため除外。"""
    out = {}
    for sid, g in panel.groupby("subject"):
        if len(g) < min_points:
            continue
        slope, intercept, *_ = stats.linregress(g["time"], g["score"])
        out[sid] = {"slope": slope, "intercept": intercept, "n_points": len(g)}
    return out


panel_mmse = build_panel(mmse, "下位項目合計_自動計算")
panel_cdr = build_panel(cdr, "CDR-SB_自動計算")

slopes_mmse = per_subject_slope(panel_mmse)
slopes_cdr = per_subject_slope(panel_cdr)

common_subjects = sort_ids(set(slopes_mmse) & set(slopes_cdr))
n_subjects = len(common_subjects)

feat = pd.DataFrame({
    "subject": common_subjects,
    "mmse_slope": [slopes_mmse[s]["slope"] for s in common_subjects],
    "cdr_slope": [slopes_cdr[s]["slope"] for s in common_subjects],
    "mmse_n_points": [slopes_mmse[s]["n_points"] for s in common_subjects],
    "cdr_n_points": [slopes_cdr[s]["n_points"] for s in common_subjects],
})

# 標準化(2変数のスケールが大きく異なるため、クラスタリング前にz化)
X = feat[["mmse_slope", "cdr_slope"]].values
X_z = (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)

# ===========================================================================
# クラスタ数の選定: k=2,3,4についてシルエットスコアで比較
# ===========================================================================
sil_rows = []
for k in [2, 3, 4]:
    if n_subjects <= k:
        continue
    labels_h = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X_z)
    sil = silhouette_score(X_z, labels_h)
    sil_rows.append({"k": k, "シルエットスコア(Ward)": sil})
sil_df = pd.DataFrame(sil_rows)
sil_df.to_csv(f"{OUT}/30_cluster_k_selection.csv", index=False, encoding="utf-8-sig")

best_k = int(sil_df.loc[sil_df["シルエットスコア(Ward)"].idxmax(), "k"])

hclust = AgglomerativeClustering(n_clusters=best_k, linkage="ward")
labels_ward = hclust.fit_predict(X_z)
kmeans = KMeans(n_clusters=best_k, n_init=20, random_state=0)
labels_kmeans = kmeans.fit_predict(X_z)

ari_methods = adjusted_rand_score(labels_ward, labels_kmeans)

feat["cluster_ward"] = labels_ward
feat["cluster_kmeans"] = labels_kmeans

# ===========================================================================
# 頑健性検証(1): ブートストラップによるクラスタ所属の安定性
# ===========================================================================
N_BOOT = 1000
ari_boot = []
idx_all = np.arange(n_subjects)
for _ in range(N_BOOT):
    boot_idx = RNG.choice(idx_all, size=n_subjects, replace=True)
    X_boot = X_z[boot_idx]
    try:
        labels_boot = AgglomerativeClustering(n_clusters=best_k, linkage="ward").fit_predict(X_boot)
        ari_boot.append(adjusted_rand_score(labels_ward[boot_idx], labels_boot))
    except Exception:
        continue
ari_boot = np.array(ari_boot)
ari_boot_mean = float(np.mean(ari_boot))
ari_boot_ci = (float(np.percentile(ari_boot, 2.5)), float(np.percentile(ari_boot, 97.5)))

# ===========================================================================
# 頑健性検証(2): permutationによる「クラスタ構造が偶然以上か」の検定
# MMSE傾きとCDR傾きを互いに無関係にシャッフルしたデータでもこれだけの
# シルエットスコアが出るか(=本物のクラスタ構造かランダムな分割か)を確認
# ===========================================================================
observed_sil = silhouette_score(X_z, labels_ward)
perm_sils = []
for _ in range(N_BOOT):
    perm = RNG.permutation(n_subjects)
    X_perm = np.column_stack([X_z[:, 0], X_z[perm, 1]])
    labels_perm = AgglomerativeClustering(n_clusters=best_k, linkage="ward").fit_predict(X_perm)
    perm_sils.append(silhouette_score(X_perm, labels_perm))
perm_sils = np.array(perm_sils)
perm_p = float((np.sum(perm_sils >= observed_sil) + 1) / (N_BOOT + 1))

# ===========================================================================
# クラスタの特徴づけ: ベースライン重症度指標で群間差を検定(探索的な副次解析)
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

char_rows = []
groups_for_test = sorted(feat["cluster_ward"].unique())
for var_name, series in baseline_vars.items():
    vals = series.reindex(common_subjects)
    sub = feat.copy()
    sub["v"] = vals.values
    sub = sub.dropna(subset=["v"])
    if len(groups_for_test) == 2:
        g0 = sub.loc[sub["cluster_ward"] == groups_for_test[0], "v"]
        g1 = sub.loc[sub["cluster_ward"] == groups_for_test[1], "v"]
        if len(g0) >= 3 and len(g1) >= 3:
            stat, p = stats.mannwhitneyu(g0, g1, alternative="two-sided")
            char_rows.append({
                "変数": var_name, "N": len(sub),
                f"クラスタ{groups_for_test[0]}_中央値": g0.median(), f"クラスタ{groups_for_test[0]}_N": len(g0),
                f"クラスタ{groups_for_test[1]}_中央値": g1.median(), f"クラスタ{groups_for_test[1]}_N": len(g1),
                "p値(Mann-Whitney U)": p,
            })
        else:
            char_rows.append({"変数": var_name, "N": len(sub), "p値(Mann-Whitney U)": np.nan})
    else:
        groups_vals = [sub.loc[sub["cluster_ward"] == g, "v"] for g in groups_for_test]
        if all(len(gv) >= 3 for gv in groups_vals):
            stat, p = stats.kruskal(*groups_vals)
            char_rows.append({"変数": var_name, "N": len(sub), "p値(Kruskal-Wallis)": p})
        else:
            char_rows.append({"変数": var_name, "N": len(sub), "p値(Kruskal-Wallis)": np.nan})

char_df = pd.DataFrame(char_rows)
pcol = "p値(Mann-Whitney U)" if "p値(Mann-Whitney U)" in char_df.columns else "p値(Kruskal-Wallis)"
valid_c = char_df[pcol].notna()
qc = pd.Series(np.nan, index=char_df.index)
if valid_c.sum() > 0:
    _, qvals, _, _ = multipletests(char_df.loc[valid_c, pcol], method="fdr_bh")
    qc.loc[valid_c] = qvals
char_df["q値(BH-FDR)"] = qc

# explore_all_pairs.py と同じ基準: 値の大半が単一値に集中する変数(低分散)は
# 見かけ上の有意差が少数例の偏りで生じやすいため、非モーダル数でフラグを立てる
FRAGILE_THRESHOLD = 5


def n_nonmodal(s):
    s = s.dropna()
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


fragile_flags = []
for var_name, series in baseline_vars.items():
    vals = series.reindex(common_subjects)
    nm = n_nonmodal(vals)
    fragile_flags.append(nm)
char_df["非モーダル数"] = fragile_flags
char_df["低分散注意"] = char_df["非モーダル数"].apply(
    lambda nm: f"低分散注意(非モーダル数={nm}<{FRAGILE_THRESHOLD})" if nm < FRAGILE_THRESHOLD else ""
)

# 精神症状(カテゴリ変数)はFisher正確検定で別途
psych_rows = []
for var_name, series in [("易怒性あり", psych_irritable), ("意欲低下あり", psych_apathy)]:
    vals = series.reindex(common_subjects)
    sub = feat.copy()
    sub["v"] = vals.values
    sub = sub.dropna(subset=["v"])
    if len(groups_for_test) == 2 and sub["v"].nunique() <= 2:
        ct = pd.crosstab(sub["cluster_ward"], sub["v"])
        if ct.shape == (2, 2):
            odds, p = stats.fisher_exact(ct.values)
            psych_rows.append({"変数": var_name, "N": len(sub), "p値(Fisher正確検定)": p})

# ===========================================================================
# 外的妥当性の検証: クラスタ形成に使っていない独立指標(Global CDR・MoCA-J)の
# 傾きでも同じ群分けが分離するか(=2変数だけのアーティファクトでないことの確認)
# ===========================================================================
def slope_for_subject(df, col, sid, min_points):
    sub = df[(df["研究番号"] == sid) & (df["時点"].isin(TIME_MAP))].copy()
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    if len(sub) < min_points:
        return np.nan
    s, *_ = stats.linregress(sub["time"], sub["score"])
    return s


feat["gcdr_slope_independent"] = feat["subject"].apply(
    lambda s: slope_for_subject(cdr, "Global CDR_原資料記載値", s, min_points=3))
feat["moca_slope_independent"] = feat["subject"].apply(
    lambda s: slope_for_subject(moca, "合計_原資料記載値", s, min_points=2))

validation_rows = []
for col, label, min_n in [
    ("gcdr_slope_independent", "Global CDR傾き(クラスタ形成に未使用)", 3),
    ("moca_slope_independent", "MoCA-J合計傾き(クラスタ形成に未使用、時点数が乏しいため参考)", 3),
]:
    sub = feat.dropna(subset=[col])
    g0 = sub.loc[sub["cluster_ward"] == 0, col]
    g1 = sub.loc[sub["cluster_ward"] == 1, col]
    if len(g0) >= min_n and len(g1) >= min_n:
        u, p = stats.mannwhitneyu(g0, g1, alternative="two-sided")
        validation_rows.append({
            "指標": label, "N(クラスタ0)": len(g0), "N(クラスタ1)": len(g1),
            "中央値(クラスタ0)": g0.median(), "中央値(クラスタ1)": g1.median(),
            "p値(Mann-Whitney U)": p,
        })
    else:
        validation_rows.append({"指標": label, "N(クラスタ0)": len(g0), "N(クラスタ1)": len(g1), "p値(Mann-Whitney U)": np.nan})
validation_df = pd.DataFrame(validation_rows)
validv = validation_df["p値(Mann-Whitney U)"].notna()
qv = pd.Series(np.nan, index=validation_df.index)
if validv.sum() > 0:
    _, qvals, _, _ = multipletests(validation_df.loc[validv, "p値(Mann-Whitney U)"], method="fdr_bh")
    qv.loc[validv] = qvals
validation_df["q値(BH-FDR)"] = qv
validation_df.to_csv(f"{OUT}/34_cluster_external_validation.csv", index=False, encoding="utf-8-sig")

feat.to_csv(f"{OUT}/31_trajectory_cluster_assignment.csv", index=False, encoding="utf-8-sig")
char_df.to_csv(f"{OUT}/32_cluster_baseline_characterization.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(psych_rows).to_csv(f"{OUT}/32b_cluster_psych_characterization.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/33_trajectory_cluster_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_subjects_with_both_slopes": n_subjects,
        "best_k": best_k,
        "silhouette_by_k": sil_rows,
        "ari_ward_vs_kmeans": float(ari_methods),
        "bootstrap_ari_mean": ari_boot_mean,
        "bootstrap_ari_95ci": ari_boot_ci,
        "observed_silhouette": float(observed_sil),
        "permutation_p_value": perm_p,
        "n_bootstrap": N_BOOT,
    }, f, ensure_ascii=False, indent=2)

print(f"=== 症例数(両指標で傾き推定可能): {n_subjects} ===\n")
print("=== クラスタ数選定(シルエットスコア) ===")
print(sil_df.to_string(index=False))
print(f"\n採用k = {best_k}")

print(f"\n=== クラスタ手法間の一致度(Ward vs k-means): ARI = {ari_methods:.3f} ===")
print(f"=== ブートストラップ安定性: 平均ARI = {ari_boot_mean:.3f} (95%CI {ari_boot_ci[0]:.3f}〜{ari_boot_ci[1]:.3f}, B={N_BOOT}) ===")
print(f"=== Permutation検定: 観測シルエット={observed_sil:.3f}, p={perm_p:.4f} (B={N_BOOT}) ===")

print("\n=== クラスタ別の傾き(平均) ===")
print(feat.groupby("cluster_ward")[["mmse_slope", "cdr_slope"]].agg(["mean", "std", "count"]).to_string())

print("\n=== クラスタとベースライン重症度の関連(探索的副次解析) ===")
print(char_df.to_string(index=False))
fragile_hits = char_df[(char_df["q値(BH-FDR)"] < 0.05) & (char_df["非モーダル数"] < FRAGILE_THRESHOLD)]
if len(fragile_hits):
    print("\n*** 注意: 以下はFDR補正後有意だが低分散(少数例依存)のため頑健な所見ではない可能性 ***")
    print(fragile_hits[["変数", "非モーダル数", "q値(BH-FDR)"]].to_string(index=False))
if psych_rows:
    print("\n=== クラスタと精神症状の関連 ===")
    print(pd.DataFrame(psych_rows).to_string(index=False))

print("\n=== 外的妥当性検証(クラスタ形成に使っていない独立指標との関連) ===")
print(validation_df.to_string(index=False))
