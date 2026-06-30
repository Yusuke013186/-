"""
ステップ2-C: 非線形性・閾値効果の検討

ユーザーが優先指定した深掘り解析。既存3解析(REPORT.md / EXPLORATORY_ASSOCIATIONS.md /
explore_all_pairs.py)はいずれも「0か月→18か月の単調な差分(Δ)」のみを扱っており、
Spearman順位相関は単調関係しか捉えられない。ここでは棚卸し(inventory_all_variables.py)
で新たに見つかった6か月・12か月時点のデータを活用し、以下3つの観点で非線形性・閾値効果を
検討する。いずれも「事前に仮説を列挙してから検定する」という方針に基づき、検定対象を
無制限に広げず、明確に定義した3つの検定ファミリーに限定する。

Family 1（10検定）: 経過自体の非線形性
  0/6/12/18か月の繰り返し測定を使い、混合効果モデルで時間の2次項(time^2)が
  有意かを検定する。「悪化のペースが時間とともに加速/減速していないか」を問う。
  対象: 主要3項目(MMSE合計・CDR-SB・Global CDR; MoCA-Jは中間時点の欠測が
  激しく繰り返し測定として不適なため除外)＋CDR下位6領域(探索的階層)。

Family 2（9検定）: 既知の頑健な関連(ALL_PAIRS_SCAN.md 3節の9件)に隠れた曲率
  Spearman相関は単調性しか見ないため、それぞれのペアについてOLSで
  y ~ x + x^2 を当てはめ、x^2項が有意に効くか(=単調な直線関係を超えた
  曲率があるか)を検定する。

Family 3（9検定）: 同じ9件について、ベースライン重症度による効果修飾(交互作用)
  ベースラインのMMSE合計(全体的な重症度の指標)で対象を中央値分割し、
  y ~ x * group の交互作用項が有意かを検定する。部分集団ごとに別々の
  p値を出すのではなく、交互作用項そのものの有意性で判定する(指定方針通り)。

各ファミリーごとに個別にBH-FDR補正する(ファミリーをまたいで都合よく
未補正p値を引用しない)。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests
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

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


# ===========================================================================
# Family 1: 経過自体の非線形性(混合効果モデル, time + time^2)
# ===========================================================================
NONLIN_VARS = [
    ("MMSE合計", mmse, "下位項目合計_自動計算", "主要"),
    ("CDR-SB", cdr, "CDR-SB_自動計算", "主要"),
    ("Global CDR", cdr, "Global CDR_原資料記載値", "主要"),
]
for item in ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]:
    NONLIN_VARS.append((f"CDR:{item}", cdr, item, "CDR下位(探索的階層)"))


def build_panel(df, col, include_24mo=False):
    tmap = dict(TIME_MAP)
    if include_24mo:
        tmap["24か月"] = 24
    sub = df[df["時点"].isin(tmap)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(tmap)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


def fit_quadratic_time_model(panel):
    mean_t = panel["time"].mean()
    panel = panel.copy()
    panel["time_c"] = panel["time"] - mean_t
    panel["time_c2"] = panel["time_c"] ** 2
    n_obs = len(panel)
    n_subj = panel["subject"].nunique()
    try:
        md = smf.mixedlm("score ~ time_c + time_c2", data=panel, groups=panel["subject"])
        mdf = md.fit(reml=True)
        coef_lin = mdf.params.get("time_c", np.nan)
        coef_quad = mdf.params.get("time_c2", np.nan)
        p_quad = mdf.pvalues.get("time_c2", np.nan)
        converged = bool(mdf.converged)
    except Exception:
        coef_lin = coef_quad = p_quad = np.nan
        converged = False
    return n_obs, n_subj, coef_lin, coef_quad, p_quad, converged


rows1 = []
for name, df, col, tier in NONLIN_VARS:
    panel_main = build_panel(df, col, include_24mo=False)
    n_obs, n_subj, coef_lin, coef_quad, p_quad, conv = fit_quadratic_time_model(panel_main)
    panel_sens = build_panel(df, col, include_24mo=True)
    n_obs_s, n_subj_s, coef_lin_s, coef_quad_s, p_quad_s, conv_s = fit_quadratic_time_model(panel_sens)
    rows1.append({
        "項目": name, "階層": tier,
        "N(観測数,0-18ヶ月)": n_obs, "N(症例数)": n_subj,
        "時間1次項係数": coef_lin, "時間2次項係数": coef_quad, "p値(2次項)": p_quad, "収束": conv,
        "感度分析_N(観測数,0-24ヶ月)": n_obs_s, "感度分析_2次項係数": coef_quad_s,
        "感度分析_p値(2次項)": p_quad_s, "感度分析_収束": conv_s,
    })
family1_df = pd.DataFrame(rows1)
valid1 = family1_df["p値(2次項)"].notna()
q1 = pd.Series(np.nan, index=family1_df.index)
if valid1.sum() > 0:
    _, qvals, _, _ = multipletests(family1_df.loc[valid1, "p値(2次項)"], method="fdr_bh")
    q1.loc[valid1] = qvals
family1_df["q値(BH-FDR)"] = q1
family1_df.to_csv(f"{OUT}/21_nonlinear_time_trend.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# Family 2 & 3 の準備: ALL_PAIRS_SCAN.md 3節で頑健とされた9件のΔ×Δペア
# ===========================================================================
ROBUST_PAIRS = [
    ("CDR:判断力・問題解決", "CDR:地域社会の活動", cdr, "判断力・問題解決", cdr, "地域社会の活動"),
    ("CDR-SB", "MMSE:時間見当識", cdr, "CDR-SB_自動計算", mmse, "時間見当識"),
    ("MMSE:時間見当識", "CDR:見当識", mmse, "時間見当識", cdr, "見当識"),
    ("MMSE合計", "CDR-SB", mmse, "下位項目合計_自動計算", cdr, "CDR-SB_自動計算"),
    ("CDR-SB", "Global CDR", cdr, "CDR-SB_自動計算", cdr, "Global CDR_原資料記載値"),
    ("MMSE合計", "CDR:見当識", mmse, "下位項目合計_自動計算", cdr, "見当識"),
    ("MMSE合計", "MoCA-J合計", mmse, "下位項目合計_自動計算", None, None),
    ("MoCA-J合計", "MMSE:時間見当識", None, None, mmse, "時間見当識"),
    ("MMSE:場所見当識", "CDR:判断力・問題解決", mmse, "場所見当識", cdr, "判断力・問題解決"),
]
moca = sheet_to_df("MoCA-J")


def get_paired_delta(df, col):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    ids = sort_ids([
        sid for sid in STUDY_IDS
        if sid in d0.index and sid in d18.index and pd.notna(d0.loc[sid]) and pd.notna(d18.loc[sid])
    ])
    delta = pd.Series(d18.loc[ids].astype(float).values - d0.loc[ids].astype(float).values, index=ids)
    base = pd.Series(d0.loc[ids].astype(float).values, index=ids)
    return delta, base


def resolve_delta_baseline(name, df, col):
    if name == "MoCA-J合計":
        return get_paired_delta(moca, "合計_原資料記載値")
    return get_paired_delta(df, col)


# 各9ペアのΔ・ベースラインを取得
pair_data = []
for a, b, dfa, cola, dfb, colb in ROBUST_PAIRS:
    delta_a, base_a = resolve_delta_baseline(a, dfa, cola)
    delta_b, base_b = resolve_delta_baseline(b, dfb, colb)
    common = sort_ids(set(delta_a.index) & set(delta_b.index))
    pair_data.append({
        "a": a, "b": b,
        "delta_a": delta_a.loc[common], "delta_b": delta_b.loc[common],
        "common": common,
    })

# 全体的な重症度指標: ベースラインMMSE合計(N=33、欠測なし)
mmse_base_all = mmse[mmse["時点"] == "0か月"].set_index("研究番号")["下位項目合計_自動計算"].astype(float)

# ===========================================================================
# Family 2: 曲率検定(y ~ x + x^2 で x^2項の有意性)
# ===========================================================================
rows2 = []
for pd_ in pair_data:
    x = pd_["delta_a"].values.astype(float)
    y = pd_["delta_b"].values.astype(float)
    n = len(x)
    label = f"{pd_['a']}(Δ) × {pd_['b']}(Δ)"
    if n < 8 or np.unique(x).size < 4:
        rows2.append({"組み合わせ": label, "N": n, "x^2項係数": np.nan, "p値(曲率)": np.nan, "備考": "N不足/分散不足のため検定不能"})
        continue
    d = pd.DataFrame({"x": x, "y": y})
    d["x2"] = d["x"] ** 2
    try:
        import statsmodels.api as sm
        X = sm.add_constant(d[["x", "x2"]])
        ols = sm.OLS(d["y"], X).fit()
        coef_x2 = ols.params["x2"]
        p_x2 = ols.pvalues["x2"]
        note = ""
    except Exception as e:
        coef_x2 = p_x2 = np.nan
        note = f"検定不能({e})"
    rows2.append({"組み合わせ": label, "N": n, "x^2項係数": coef_x2, "p値(曲率)": p_x2, "備考": note})
family2_df = pd.DataFrame(rows2)
valid2 = family2_df["p値(曲率)"].notna()
q2 = pd.Series(np.nan, index=family2_df.index)
if valid2.sum() > 0:
    _, qvals, _, _ = multipletests(family2_df.loc[valid2, "p値(曲率)"], method="fdr_bh")
    q2.loc[valid2] = qvals
family2_df["q値(BH-FDR)"] = q2
family2_df.to_csv(f"{OUT}/22_curvature_test_robust9.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# 頑健性検証: Family 2でq<0.05に達したペアについてleave-one-out感度分析
# (1〜2例の外れ値による見かけ上の曲率でないかを確認する)
# ---------------------------------------------------------------------------
import statsmodels.api as sm

loo_rows = []
sig2 = family2_df[family2_df["q値(BH-FDR)"] < 0.05]
for _, r in sig2.iterrows():
    match = next(pd_ for pd_ in pair_data if f"{pd_['a']}(Δ) × {pd_['b']}(Δ)" == r["組み合わせ"])
    x = match["delta_a"].values.astype(float)
    y = match["delta_b"].values.astype(float)
    n = len(x)
    for i in range(n):
        xi, yi = np.delete(x, i), np.delete(y, i)
        Xi = sm.add_constant(pd.DataFrame({"x": xi, "x2": xi ** 2}))
        mi = sm.OLS(yi, Xi).fit()
        loo_rows.append({
            "組み合わせ": r["組み合わせ"], "除外症例": match["common"][i],
            "除外症例のx値": x[i], "除外後x^2項係数": mi.params["x2"], "除外後p値": mi.pvalues["x2"],
        })
loo_df = pd.DataFrame(loo_rows)
if len(loo_df):
    loo_df.to_csv(f"{OUT}/25_curvature_loo_sensitivity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# Family 3: ベースライン重症度による効果修飾(交互作用項の検定)
# ===========================================================================
median_base = mmse_base_all.loc[[i for i in mmse_base_all.index if i in STUDY_IDS]].median()

rows3 = []
for pd_ in pair_data:
    common = pd_["common"]
    sev = mmse_base_all.reindex(common)
    valid_common = [sid for sid in common if pd.notna(sev.loc[sid])]
    x = pd_["delta_a"].loc[valid_common].values.astype(float)
    y = pd_["delta_b"].loc[valid_common].values.astype(float)
    sev_v = sev.loc[valid_common].values.astype(float)
    n = len(valid_common)
    label = f"{pd_['a']}(Δ) × {pd_['b']}(Δ)"
    group = (sev_v <= median_base).astype(int)  # 1=ベースラインMMSE合計が中央値以下(重症側)
    n_g1, n_g0 = (group == 1).sum(), (group == 0).sum()
    if n < 8 or n_g1 < 4 or n_g0 < 4:
        rows3.append({"組み合わせ": label, "N": n, "N(重症側)": n_g1, "N(軽症側)": n_g0,
                       "交互作用項係数": np.nan, "p値(交互作用)": np.nan, "備考": "部分集団が小さく検定不能"})
        continue
    d = pd.DataFrame({"x": x, "y": y, "g": group})
    try:
        import statsmodels.api as sm
        import statsmodels.formula.api as smf2
        ols = smf2.ols("y ~ x * g", data=d).fit()
        coef_int = ols.params.get("x:g", np.nan)
        p_int = ols.pvalues.get("x:g", np.nan)
        note = ""
    except Exception as e:
        coef_int = p_int = np.nan
        note = f"検定不能({e})"
    rows3.append({"組み合わせ": label, "N": n, "N(重症側)": n_g1, "N(軽症側)": n_g0,
                   "交互作用項係数": coef_int, "p値(交互作用)": p_int, "備考": note})
family3_df = pd.DataFrame(rows3)
valid3 = family3_df["p値(交互作用)"].notna()
q3 = pd.Series(np.nan, index=family3_df.index)
if valid3.sum() > 0:
    _, qvals, _, _ = multipletests(family3_df.loc[valid3, "p値(交互作用)"], method="fdr_bh")
    q3.loc[valid3] = qvals
family3_df["q値(BH-FDR)"] = q3
family3_df.to_csv(f"{OUT}/23_baseline_severity_interaction_robust9.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 出力
# ===========================================================================
print("=== Family 1: 経過自体の非線形性(時間の2次項検定, n=9) ===")
print(family1_df[["項目", "階層", "N(観測数,0-18ヶ月)", "N(症例数)", "時間2次項係数", "p値(2次項)", "q値(BH-FDR)", "収束"]].to_string(index=False))

print("\n=== Family 2: 既知の頑健な9ペアの曲率検定 ===")
print(family2_df.to_string(index=False))
if len(loo_df):
    print("\n--- Family 2でq<0.05だったペアのLeave-one-out感度分析 ---")
    print(loo_df.sort_values("除外後p値", ascending=False).to_string(index=False))

print("\n=== Family 3: ベースライン重症度による効果修飾(交互作用)検定 ===")
print(family3_df.to_string(index=False))

with open(f"{OUT}/24_nonlinear_scan_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "family1_n_tests": len(family1_df), "family1_n_tested": int(valid1.sum()),
        "family2_n_tests": len(family2_df), "family2_n_tested": int(valid2.sum()),
        "family3_n_tests": len(family3_df), "family3_n_tested": int(valid3.sum()),
        "severity_median_mmse_baseline": float(median_base),
    }, f, ensure_ascii=False, indent=2)
