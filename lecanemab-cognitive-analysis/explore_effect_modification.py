"""
ステップ2-B: 効果修飾(effect modification)/交互作用分析

これまでの解析は「悪化のペースは一定」という前提のもと、群を分けずに全症例まとめて
傾向を見てきた。本解析は、悪化のペース(時間あたりの変化率)そのものが、患者の特性に
よって異なるかどうかを、事前に規定した2つの仮説として検定する。

2-C(`explore_nonlinear.py`)のFamily3は「9つの既知ペアについて、関連の強さが
ベースライン重症度で変わるか」という横断的な効果修飾だった。本解析はそれと異なり、
「時間経過に伴う認知機能の変化率(傾き)自体が、ベースライン重症度や精神症状の有無で
異なるか」という縦断的な効果修飾を、0/6/12/18か月の繰り返し測定パネル(2-C Family1で
構築したものと同じ)を使った混合効果モデルの交互作用項(time × moderator)で検定する。

事前に2つの検定ファミリーを規定し、各ファミリー内でのみBH-FDR補正する。

Family 1（3検定）: 時間 × ベースライン重症度(連続値, ベースラインMMSE合計)の交互作用
  対象: MMSE合計・CDR-SB・Global CDRの主要3項目。
  注意: MMSE合計を結果変数とする検定は、ベースラインMMSE合計を予測変数にも使うため、
  回帰への平均回帰(regression to the mean)の影響を受けうる。2-C Family3も同じ
  ベースラインMMSE合計を全ペア共通の重症度指標として使っており、本解析もその先例に
  倣うが、この限界は結果の解釈時に明記する。

Family 2（6検定）: 時間 × 精神症状(易怒性・意欲低下)の交互作用
  対象: 同じ主要3項目 × 精神症状2種類。
  易怒性ありは33例中3例のみと極端に少なく、検出力はきわめて低い点に注意。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_PERM = 1000

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
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}


def build_panel(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


OUTCOME_VARS = [
    ("MMSE合計", mmse, "下位項目合計_自動計算"),
    ("CDR-SB", cdr, "CDR-SB_自動計算"),
    ("Global CDR", cdr, "Global CDR_原資料記載値"),
]

mmse_base_all = mmse[mmse["時点"] == "0か月"].set_index("研究番号")["下位項目合計_自動計算"].astype(float)
psych_irritable = psych.set_index("研究番号")["易怒性"].astype(float)
psych_apathy = psych.set_index("研究番号")["意欲低下"].astype(float)


def fit_interaction_model(panel, moderator_series, moderator_name, center=True):
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
        term = "time_c:mod"
        coef_int = mdf.params.get(term, np.nan)
        p_int = mdf.pvalues.get(term, np.nan)
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
    subjects = sorted(panel["subject"].unique(), key=lambda x: int(x[1:]))
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


def permutation_interaction_test(panel, moderator_series, observed_coef, label, n_perm=N_PERM, center=True):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    subjects = sorted(panel["subject"].unique(), key=lambda x: int(x[1:]))
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
        panel["mod"] = m - np.nanmean(m) if center else m
        try:
            md = smf.mixedlm("score ~ time_c * mod", data=panel, groups=panel["subject"])
            mdf = md.fit(reml=True)
            perm_coefs.append(mdf.params.get("time_c:mod", np.nan))
        except Exception:
            n_failed += 1
            continue
    perm_coefs = np.array([c for c in perm_coefs if not np.isnan(c)])
    p_perm = float(np.mean(np.abs(perm_coefs) >= np.abs(observed_coef))) if len(perm_coefs) > 0 else np.nan
    return {
        "検定": label, "観測交互作用係数": observed_coef, "置換検定p値": p_perm,
        "n_perm": n_perm, "n_failed": n_failed,
    }


# ===========================================================================
# Family 1: 時間 × ベースライン重症度(連続値)の交互作用
# ===========================================================================
rows1 = []
for name, df, col in OUTCOME_VARS:
    panel = build_panel(df, col)
    n_obs, n_subj, coef_int, p_int, conv = fit_interaction_model(panel, mmse_base_all, "ベースラインMMSE合計")
    rows1.append({
        "結果変数": name, "N(観測数)": n_obs, "N(症例数)": n_subj,
        "交互作用項係数(time×ベースライン重症度)": coef_int, "p値": p_int, "収束": conv,
        "備考": "結果変数がMMSE合計の場合、予測変数も同じベースラインMMSE合計のため平均回帰の影響に留意" if name == "MMSE合計" else "",
    })
family1_df = pd.DataFrame(rows1)
valid1 = family1_df["p値"].notna()
q1 = pd.Series(np.nan, index=family1_df.index)
if valid1.sum() > 0:
    _, qvals, _, _ = multipletests(family1_df.loc[valid1, "p値"], method="fdr_bh")
    q1.loc[valid1] = qvals
family1_df["q値(BH-FDR)"] = q1
family1_df.to_csv(f"{OUT}/70_severity_x_time_interaction.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# Family 2: 時間 × 精神症状の交互作用
# ===========================================================================
PSYCH_MODERATORS = [("易怒性", psych_irritable), ("意欲低下", psych_apathy)]

rows2 = []
for name, df, col in OUTCOME_VARS:
    for psych_name, pseries in PSYCH_MODERATORS:
        panel = build_panel(df, col)
        n_obs, n_subj, coef_int, p_int, conv = fit_interaction_model(panel, pseries, psych_name, center=False)
        n_pos = int(pseries.reindex(STUDY_IDS).sum())
        rows2.append({
            "結果変数": name, "精神症状": psych_name, "N(観測数)": n_obs, "N(症例数)": n_subj,
            "N(症状あり症例)": n_pos,
            "交互作用項係数(time×精神症状)": coef_int, "p値": p_int, "収束": conv,
        })
family2_df = pd.DataFrame(rows2)
valid2 = family2_df["p値"].notna()
q2 = pd.Series(np.nan, index=family2_df.index)
if valid2.sum() > 0:
    _, qvals, _, _ = multipletests(family2_df.loc[valid2, "p値"], method="fdr_bh")
    q2.loc[valid2] = qvals
family2_df["q値(BH-FDR)"] = q2
family2_df.to_csv(f"{OUT}/71_psych_x_time_interaction.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証: いずれかのファミリーでq<0.05があればLOO感度分析
# ===========================================================================
loo_frames = []
sig1 = family1_df[family1_df["q値(BH-FDR)"] < 0.05]
for _, r in sig1.iterrows():
    name = r["結果変数"]
    df, col = next((d, c) for n, d, c in OUTCOME_VARS if n == name)
    panel = build_panel(df, col)
    label = f"{name} × ベースライン重症度"
    loo_frames.append(loo_interaction_sensitivity(panel, mmse_base_all, label))

sig2 = family2_df[family2_df["q値(BH-FDR)"] < 0.05]
for _, r in sig2.iterrows():
    name, psych_name = r["結果変数"], r["精神症状"]
    df, col = next((d, c) for n, d, c in OUTCOME_VARS if n == name)
    pseries = dict(PSYCH_MODERATORS)[psych_name]
    panel = build_panel(df, col)
    label = f"{name} × {psych_name}"
    loo_frames.append(loo_interaction_sensitivity(panel, pseries, label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/72_interaction_loo_sensitivity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証2: 置換検定(moderatorを症例間でシャッフルした帰無分布との比較)
# ===========================================================================
perm_rows = []
for _, r in sig1.iterrows():
    name = r["結果変数"]
    df, col = next((d, c) for n, d, c in OUTCOME_VARS if n == name)
    panel = build_panel(df, col)
    label = f"{name} × ベースライン重症度"
    perm_rows.append(permutation_interaction_test(
        panel, mmse_base_all, r["交互作用項係数(time×ベースライン重症度)"], label, center=True))

for _, r in sig2.iterrows():
    name, psych_name = r["結果変数"], r["精神症状"]
    df, col = next((d, c) for n, d, c in OUTCOME_VARS if n == name)
    pseries = dict(PSYCH_MODERATORS)[psych_name]
    panel = build_panel(df, col)
    label = f"{name} × {psych_name}"
    perm_rows.append(permutation_interaction_test(
        panel, pseries, r["交互作用項係数(time×精神症状)"], label, center=False))

perm_df = pd.DataFrame(perm_rows)
if len(perm_df):
    perm_df.to_csv(f"{OUT}/74_interaction_permutation_test.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 解釈補助: 群別の記述統計(個人別OLS傾きの群間比較。新規検定ではなく解釈用)
# ===========================================================================
def per_subject_slope(panel, min_points=3):
    from scipy.stats import linregress
    slopes = {}
    for sid, g in panel.groupby("subject"):
        g = g.sort_values("time")
        if g["time"].nunique() < min_points:
            continue
        res = linregress(g["time"], g["score"])
        slopes[sid] = res.slope
    return pd.Series(slopes)


desc_rows = []
median_sev = mmse_base_all.reindex(STUDY_IDS).median()
for name, df, col in OUTCOME_VARS:
    panel = build_panel(df, col)
    slopes = per_subject_slope(panel)
    sev_group = mmse_base_all.reindex(slopes.index)
    high = slopes[sev_group > median_sev]
    low = slopes[sev_group <= median_sev]
    desc_rows.append({
        "結果変数": name, "比較": "ベースライン重症度(中央値分割)",
        "群1": "軽症側(ベースラインMMSE>中央値)", "N1": len(high), "傾き平均1": high.mean(),
        "群2": "重症側(ベースラインMMSE<=中央値)", "N2": len(low), "傾き平均2": low.mean(),
    })
    apathy_group = psych_apathy.reindex(slopes.index)
    with_a = slopes[apathy_group == 1]
    without_a = slopes[apathy_group == 0]
    desc_rows.append({
        "結果変数": name, "比較": "意欲低下の有無",
        "群1": "意欲低下あり", "N1": len(with_a), "傾き平均1": with_a.mean(),
        "群2": "意欲低下なし", "N2": len(without_a), "傾き平均2": without_a.mean(),
    })
desc_df = pd.DataFrame(desc_rows)
desc_df.to_csv(f"{OUT}/75_interaction_group_slope_descriptive.csv", index=False, encoding="utf-8-sig")
print("\n=== 解釈補助: 群別の個人別傾き平均(記述統計、新規検定ではない) ===")
print(desc_df.to_string(index=False))

with open(f"{OUT}/73_effect_modification_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "family1_n_tests": len(family1_df), "family1_n_tested": int(valid1.sum()),
        "family2_n_tests": len(family2_df), "family2_n_tested": int(valid2.sum()),
        "n_loo_runs": len(loo_df),
        "n_perm": N_PERM, "n_perm_runs": len(perm_df),
        "n_irritable": int(psych_irritable.reindex(STUDY_IDS).sum()),
        "n_apathy": int(psych_apathy.reindex(STUDY_IDS).sum()),
    }, f, ensure_ascii=False, indent=2)

print("=== Family 1: 時間 × ベースライン重症度(連続値)の交互作用 ===")
print(family1_df.to_string(index=False))

print("\n=== Family 2: 時間 × 精神症状の交互作用 ===")
print(family2_df.to_string(index=False))

if len(loo_df):
    print("\n=== Leave-one-out感度分析(q<0.05だった検定について) ===")
    print(loo_df.to_string(index=False))
    print("\n=== 置換検定(moderatorシャッフルによる帰無分布との比較, B={}) ===".format(N_PERM))
    print(perm_df.to_string(index=False))
else:
    print("\n*** FDR補正後に有意な交互作用はなかったため、LOO・置換検定は実施対象なし ***")
