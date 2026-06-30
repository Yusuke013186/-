"""
深掘りステップ3-C: 既存の頑健な所見をさらに深掘り(確からしさを高める追加検証)

これまでの解析で頑健性が確認されている3つの所見について、それぞれ異なる
独立した手法で追加検証する。いずれも新規の発見を狙うものではなく、
既存の結論を別の角度から再確認するための補強解析である。

(1) 2-D 軌跡クラスタリング: クラスタリングはどんなデータからも機械的に
    群を作り出せてしまう(本当の二峰性がなくても、k-meansやWard法は必ず
    k個の群を返す)。2-Dはシルエットスコアのpermutation検定とブートストラップ
    ARIで頑健性を示したが、これらは「群分けの再現性」を見ているにすぎず、
    「データの分布が本当に二峰性(bimodal)か」を直接検定してはいない。
    本解析ではHartigan's dip test(単峰性を帰無仮説とする統計検定)を、
    クラスタリングに用いた2つの入力変数(MMSE合計の傾き・CDR-SBの傾き)
    それぞれに適用する。

(2) 2-F 偏相関ネットワーク: Graphical Lassoは1つの推定手法にすぎない。
    Meinshausen-Bühlmannの近傍選択法(変数ごとにLasso回帰を行い、非ゼロ係数を
    持つ変数を「隣接」とみなす)という、数理的に異なるアプローチで同じ
    安定エッジが再現されるかを確認する(収束的妥当性, convergent validity)。

(3) 2-B MMSE合計×ベースライン重症度の交互作用: この所見はベースラインMMSE
    合計自体を予測変数に使っているため、平均への回帰(regression to the mean)や
    MMSEスケールの天井効果による統計的アーティファクトの可能性を排除できない
    (EFFECT_MODIFICATION_ANALYSIS.md §6で明記済みの限界)。本解析では、MMSE
    スケールを一切使わない独立した重症度指標(ベースラインCDR-SBおよび
    ベースラインMoCA-J合計)をmoderatorとして同じ交互作用モデルを再実行し、
    同じ方向の所見が独立した instrument でも再現されるかを確認する。
    (2-B本来のFamily1ではこの2変数を全outcomeのmoderatorとして使っていたが、
    本解析はMMSE合計をoutcomeとする検定に限定し、循環性の懸念に直接対処する。)

3つとも独立した検定ファミリーとして扱い、ファミリー内でのみBH-FDR補正する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
import diptest
import statsmodels.formula.api as smf
from scipy import stats
from sklearn.linear_model import LassoCV, Lasso
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_BOOT = 500
N_PERM = 1000

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")
moca = sheet_to_df("MoCA-J")

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
    out = {}
    for sid, g in panel.groupby("subject"):
        if len(g) < min_points:
            continue
        slope, intercept, *_ = stats.linregress(g["time"], g["score"])
        out[sid] = slope
    return out


# ===========================================================================
# (1) 2-D 軌跡クラスタリングの入力変数に対するHartigan's dip test(二峰性検定)
# ===========================================================================
panel_mmse = build_panel(mmse, "下位項目合計_自動計算")
panel_cdr = build_panel(cdr, "CDR-SB_自動計算")
slopes_mmse = per_subject_slope(panel_mmse)
slopes_cdr = per_subject_slope(panel_cdr)
common_subjects = sort_ids(set(slopes_mmse) & set(slopes_cdr))

mmse_slope_arr = np.array([slopes_mmse[s] for s in common_subjects])
cdr_slope_arr = np.array([slopes_cdr[s] for s in common_subjects])

dip_rows = []
for label, arr in [("MMSE合計の傾き", mmse_slope_arr), ("CDR-SBの傾き", cdr_slope_arr)]:
    dip_stat, p_dip = diptest.diptest(arr, boot_pval=True, n_boot=N_BOOT, seed=20260630)
    dip_rows.append({"変数": label, "N": len(arr), "dip統計量": dip_stat, "p値(ブートストラップ)": p_dip})
dip_df = pd.DataFrame(dip_rows)
valid_dip = dip_df["p値(ブートストラップ)"].notna()
q_dip = pd.Series(np.nan, index=dip_df.index)
if valid_dip.sum() > 0:
    _, qvals, _, _ = multipletests(dip_df.loc[valid_dip, "p値(ブートストラップ)"], method="fdr_bh")
    q_dip.loc[valid_dip] = qvals
dip_df["q値(BH-FDR)"] = q_dip
dip_df.to_csv(f"{OUT}/95_dip_test_trajectory_clusters.csv", index=False, encoding="utf-8-sig")

# 頑健性検証: FDR補正後に有意だった変数についてLOO感度分析(1症例ずつ除外して再検定)
dip_loo_rows = []
sig_dip = dip_df[dip_df["q値(BH-FDR)"] < 0.05]
arr_by_label = {"MMSE合計の傾き": mmse_slope_arr, "CDR-SBの傾き": cdr_slope_arr}
for _, r in sig_dip.iterrows():
    label = r["変数"]
    arr = arr_by_label[label]
    for k in range(len(arr)):
        arr_loo = np.delete(arr, k)
        sid = common_subjects[k]
        d_stat, d_p = diptest.diptest(arr_loo, boot_pval=True, n_boot=N_BOOT, seed=20260630)
        dip_loo_rows.append({"変数": label, "除外症例": sid, "除外後dip統計量": d_stat, "除外後p値": d_p})
dip_loo_df = pd.DataFrame(dip_loo_rows)
if len(dip_loo_df):
    dip_loo_df.to_csv(f"{OUT}/95b_dip_test_loo.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# (2) 2-F 偏相関ネットワークのMeinshausen-Bühlmann近傍選択による再検証
# ===========================================================================
def get_paired_delta(df, col):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    ids = sort_ids([
        sid for sid in STUDY_IDS
        if sid in d0.index and sid in d18.index and pd.notna(d0.loc[sid]) and pd.notna(d18.loc[sid])
    ])
    delta = pd.Series(d18.loc[ids].astype(float).values - d0.loc[ids].astype(float).values, index=ids)
    return delta


NETWORK_VARS = [
    ("CDR-SB", cdr, "CDR-SB_自動計算", False),
    ("Global CDR", cdr, "Global CDR_原資料記載値", False),
    ("CDR:見当識", cdr, "見当識", False),
    ("CDR:判断力・問題解決", cdr, "判断力・問題解決", False),
    ("CDR:地域社会の活動", cdr, "地域社会の活動", False),
    ("MMSE合計", mmse, "下位項目合計_自動計算", True),
    ("MMSE:時間見当識", mmse, "時間見当識", True),
    ("MMSE:場所見当識", mmse, "場所見当識", True),
    ("MoCA-J合計", moca, "合計_原資料記載値", True),
]

deltas = {}
for name, df, col, flip in NETWORK_VARS:
    d = get_paired_delta(df, col)
    deltas[name] = -d if flip else d

names = [v[0] for v in NETWORK_VARS]
common = sort_ids(set.intersection(*[set(deltas[n].index) for n in names]))
mat = pd.DataFrame({n: deltas[n].loc[common].values for n in names}, index=common)
n, p = mat.shape

scaler = StandardScaler()
X = scaler.fit_transform(mat.values)


def mb_neighborhoods(X, alphas=None, cv=5):
    """変数ごとにLassoCVで他の全変数から回帰し、非ゼロ係数を持つ変数を近傍とする"""
    p = X.shape[1]
    neighbors = [set() for _ in range(p)]
    alpha_used = np.zeros(p)
    for j in range(p):
        y = X[:, j]
        Xo = np.delete(X, j, axis=1)
        other_idx = [k for k in range(p) if k != j]
        model = LassoCV(cv=cv, max_iter=5000, alphas=50)
        model.fit(Xo, y)
        alpha_used[j] = model.alpha_
        for local_k, global_k in enumerate(other_idx):
            if abs(model.coef_[local_k]) > 1e-8:
                neighbors[j].add(global_k)
    return neighbors, alpha_used


def mb_edge_matrix(neighbors, p, rule="or"):
    mat_edge = np.zeros((p, p), dtype=bool)
    for i in range(p):
        for j in neighbors[i]:
            if rule == "or":
                mat_edge[i, j] = True
                mat_edge[j, i] = True
            else:  # and
                if i in neighbors[j]:
                    mat_edge[i, j] = True
                    mat_edge[j, i] = True
    return mat_edge


neighbors_full, alpha_full = mb_neighborhoods(X, cv=min(5, n))
edge_or_full = mb_edge_matrix(neighbors_full, p, rule="or")
edge_and_full = mb_edge_matrix(neighbors_full, p, rule="and")

# 既存(Graphical Lasso)の安定エッジと比較
glasso_edges = pd.read_csv(f"{OUT}/51_partial_correlation_edges.csv")

mb_rows = []
for i in range(p):
    for j in range(i + 1, p):
        glasso_row = glasso_edges[
            ((glasso_edges["変数A"] == names[i]) & (glasso_edges["変数B"] == names[j])) |
            ((glasso_edges["変数A"] == names[j]) & (glasso_edges["変数B"] == names[i]))
        ]
        glasso_pcorr = float(glasso_row["偏相関係数"].iloc[0]) if len(glasso_row) else np.nan
        glasso_stab = float(glasso_row["ブートストラップ安定性(エッジ出現率)"].iloc[0]) if len(glasso_row) else np.nan
        mb_rows.append({
            "変数A": names[i], "変数B": names[j],
            "GraphicalLasso偏相関係数": glasso_pcorr,
            "GraphicalLassoブートストラップ安定性": glasso_stab,
            "MB近傍選択_OR規則(全データ)": bool(edge_or_full[i, j]),
            "MB近傍選択_AND規則(全データ)": bool(edge_and_full[i, j]),
        })
mb_df = pd.DataFrame(mb_rows)

# ブートストラップによるMB-OR規則エッジの安定性(GraphicalLassoと同じ手続き)
edge_presence_or = np.zeros((N_BOOT, p, p))
idx_all = np.arange(n)
n_failed_mb = 0
for b in range(N_BOOT):
    boot_idx = RNG.choice(idx_all, size=n, replace=True)
    Xb = X[boot_idx]
    if np.any(Xb.std(axis=0) < 1e-8):
        n_failed_mb += 1
        continue
    try:
        neigh_b = []
        for j in range(p):
            y = Xb[:, j]
            Xo = np.delete(Xb, j, axis=1)
            other_idx = [k for k in range(p) if k != j]
            model = Lasso(alpha=alpha_full[j], max_iter=5000)
            model.fit(Xo, y)
            nb = {other_idx[local_k] for local_k in range(len(other_idx)) if abs(model.coef_[local_k]) > 1e-8}
            neigh_b.append(nb)
        edge_b = mb_edge_matrix(neigh_b, p, rule="or")
        edge_presence_or[b] = edge_b.astype(float)
    except Exception:
        n_failed_mb += 1
        continue

mb_stability = edge_presence_or.mean(axis=0)
mb_df["MB近傍選択ブートストラップ安定性(OR規則)"] = mb_df.apply(
    lambda r: mb_stability[names.index(r["変数A"]), names.index(r["変数B"])], axis=1)

STABLE_THRESHOLD = 0.7
EDGE_THRESHOLD = 0.05
mb_df["GraphicalLasso安定エッジ"] = (
    (mb_df["GraphicalLasso偏相関係数"].abs() > EDGE_THRESHOLD) &
    (mb_df["GraphicalLassoブートストラップ安定性"] >= STABLE_THRESHOLD)
)
mb_df["MB安定エッジ(OR規則)"] = mb_df["MB近傍選択ブートストラップ安定性(OR規則)"] >= STABLE_THRESHOLD
mb_df["両手法で安定エッジ一致"] = mb_df["GraphicalLasso安定エッジ"] & mb_df["MB安定エッジ(OR規則)"]
mb_df = mb_df.sort_values("GraphicalLassoブートストラップ安定性", ascending=False)
mb_df.to_csv(f"{OUT}/96_mb_neighborhood_selection_edges.csv", index=False, encoding="utf-8-sig")

n_glasso_stable = int(mb_df["GraphicalLasso安定エッジ"].sum())
n_mb_stable = int(mb_df["MB安定エッジ(OR規則)"].sum())
n_both_stable = int(mb_df["両手法で安定エッジ一致"].sum())

with open(f"{OUT}/97_mb_neighborhood_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_subjects": n, "n_variables": p, "n_bootstrap": N_BOOT, "n_bootstrap_failed": n_failed_mb,
        "n_glasso_stable_edges": n_glasso_stable, "n_mb_stable_edges_or_rule": n_mb_stable,
        "n_both_methods_stable": n_both_stable,
        "concordance_rate_among_glasso_stable": (n_both_stable / n_glasso_stable) if n_glasso_stable else None,
    }, f, ensure_ascii=False, indent=2)

# ===========================================================================
# (3) 2-B MMSE合計×重症度交互作用の独立moderatorによる再検定
# ===========================================================================
cdr_base_all = cdr[cdr["時点"] == "0か月"].set_index("研究番号")["CDR-SB_自動計算"].astype(float)
moca_base_all = moca[moca["時点"] == "0か月"].set_index("研究番号")["合計_原資料記載値"].astype(float)

INDEPENDENT_MODERATORS = [
    ("ベースラインCDR-SB", cdr_base_all),
    ("ベースラインMoCA-J合計", moca_base_all),
]


def fit_interaction_model(panel, moderator_series, center=True):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    mod = moderator_series.reindex(panel["subject"].values).values.astype(float)
    panel["mod"] = mod - np.nanmean(mod) if center else mod
    panel = panel.dropna(subset=["mod"])
    n_obs = len(panel)
    n_subj = panel["subject"].nunique()
    try:
        md = smf.mixedlm("score ~ time_c * mod", data=panel, groups=panel["subject"])
        mdf = md.fit(reml=True)
        coef_int = mdf.params.get("time_c:mod", np.nan)
        p_int = mdf.pvalues.get("time_c:mod", np.nan)
        converged = bool(mdf.converged)
    except Exception:
        coef_int = p_int = np.nan
        converged = False
    return n_obs, n_subj, coef_int, p_int, converged


def loo_interaction_sensitivity(panel, moderator_series, label):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    mod = moderator_series.reindex(panel["subject"].values).values.astype(float)
    panel["mod"] = mod - np.nanmean(mod)
    panel = panel.dropna(subset=["mod"])
    subjects = sort_ids(panel["subject"].unique())
    rows = []
    for sid in subjects:
        sub_panel = panel[panel["subject"] != sid]
        try:
            md = smf.mixedlm("score ~ time_c * mod", data=sub_panel, groups=sub_panel["subject"])
            mdf = md.fit(reml=True)
            p_int = mdf.pvalues.get("time_c:mod", np.nan)
            coef_int = mdf.params.get("time_c:mod", np.nan)
        except Exception:
            p_int = coef_int = np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後交互作用係数": coef_int, "除外後p値": p_int})
    return pd.DataFrame(rows)


def permutation_interaction_test(panel, moderator_series, observed_coef, label, n_perm=N_PERM):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    subjects = sort_ids(panel["subject"].unique())
    mod_vals = moderator_series.reindex(subjects).values.astype(float)
    valid_mask = ~np.isnan(mod_vals)
    subjects_valid = [s for s, v in zip(subjects, valid_mask) if v]
    mod_valid = mod_vals[valid_mask]
    panel = panel[panel["subject"].isin(subjects_valid)].copy()
    perm_coefs = []
    n_failed = 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(mod_valid)
        mod_map = dict(zip(subjects_valid, shuffled))
        m = panel["subject"].map(mod_map).values.astype(float)
        panel["mod"] = m - np.nanmean(m)
        try:
            md = smf.mixedlm("score ~ time_c * mod", data=panel, groups=panel["subject"])
            mdf = md.fit(reml=True)
            perm_coefs.append(mdf.params.get("time_c:mod", np.nan))
        except Exception:
            n_failed += 1
            continue
    perm_coefs = np.array([c for c in perm_coefs if not np.isnan(c)])
    p_perm = float(np.mean(np.abs(perm_coefs) >= np.abs(observed_coef))) if len(perm_coefs) > 0 else np.nan
    return {"検定": label, "観測交互作用係数": observed_coef, "置換検定p値": p_perm, "n_perm": n_perm, "n_failed": n_failed}


panel_mmse_full = build_panel(mmse, "下位項目合計_自動計算")
rows3 = []
for mod_name, mod_series in INDEPENDENT_MODERATORS:
    n_obs, n_subj, coef_int, p_int, conv = fit_interaction_model(panel_mmse_full, mod_series)
    rows3.append({
        "結果変数": "MMSE合計", "moderator": mod_name, "N(観測数)": n_obs, "N(症例数)": n_subj,
        "交互作用項係数(time×moderator)": coef_int, "p値": p_int, "収束": conv,
    })
family3_df = pd.DataFrame(rows3)
valid3 = family3_df["p値"].notna()
q3 = pd.Series(np.nan, index=family3_df.index)
if valid3.sum() > 0:
    _, qvals, _, _ = multipletests(family3_df.loc[valid3, "p値"], method="fdr_bh")
    q3.loc[valid3] = qvals
family3_df["q値(BH-FDR)"] = q3
family3_df.to_csv(f"{OUT}/98_mmse_severity_independent_moderator_retest.csv", index=False, encoding="utf-8-sig")

loo_frames3 = []
perm_rows3 = []
sig3 = family3_df[family3_df["q値(BH-FDR)"] < 0.05]
for _, r in sig3.iterrows():
    mod_name = r["moderator"]
    mod_series = dict(INDEPENDENT_MODERATORS)[mod_name]
    label = f"MMSE合計 × {mod_name}"
    loo_frames3.append(loo_interaction_sensitivity(panel_mmse_full, mod_series, label))
    perm_rows3.append(permutation_interaction_test(panel_mmse_full, mod_series, r["交互作用項係数(time×moderator)"], label))

loo_df3 = pd.concat(loo_frames3, ignore_index=True) if loo_frames3 else pd.DataFrame()
if len(loo_df3):
    loo_df3.to_csv(f"{OUT}/99_mmse_moderator_retest_loo.csv", index=False, encoding="utf-8-sig")
perm_df3 = pd.DataFrame(perm_rows3) if perm_rows3 else pd.DataFrame()
if len(perm_df3):
    perm_df3.to_csv(f"{OUT}/100_mmse_moderator_retest_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/101_robustness_deepdive_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "dip_test_n_subjects": len(common_subjects),
        "mb_n_subjects": n, "mb_n_variables": p,
        "mmse_retest_n_tests": len(family3_df),
    }, f, ensure_ascii=False, indent=2)

print("=== (1) Hartigan's dip test: 軌跡クラスタの入力変数は本当に二峰性か ===")
print(dip_df.to_string(index=False))
if len(dip_loo_df):
    print("\n--- LOO感度分析(FDR補正後有意だった変数について) ---")
    print(dip_loo_df.to_string(index=False))

print(f"\n=== (2) Meinshausen-Bühlmann近傍選択 vs Graphical Lasso: 安定エッジの一致 ===")
print(f"GraphicalLasso安定エッジ数={n_glasso_stable}, MB安定エッジ数(OR規則)={n_mb_stable}, 両方一致={n_both_stable}")
print(mb_df[["変数A", "変数B", "GraphicalLasso安定エッジ", "MB安定エッジ(OR規則)", "両手法で安定エッジ一致"]].to_string(index=False))

print("\n=== (3) MMSE合計×重症度交互作用: 独立moderator(CDR-SB・MoCA-J)による再検定 ===")
print(family3_df.to_string(index=False))
if len(loo_df3):
    print("\n--- LOO感度分析 ---")
    print(loo_df3.to_string(index=False))
    print("\n--- 置換検定 ---")
    print(perm_df3.to_string(index=False))
else:
    print("\n*** FDR補正後に有意な交互作用はなかったため、LOO・置換検定は実施対象なし ***")
