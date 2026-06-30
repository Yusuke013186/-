"""
深掘りステップ5: 精神症状(意欲低下)が悪化させるのはCDRのどの下位領域か(ドメイン特異性)

背景: 2-B(`explore_effect_modification.py`)のFamily 2で、時間×精神症状の交互作用を
CDR-SB(6下位領域合計)・MMSE合計・Global CDRの3項目で検定した結果、
CDR-SB×意欲低下のみがFDR補正後に有意だった(係数=0.0692、q=0.0106)。
頑健性検証では、leave-one-out感度分析は33症例全例の除外でp<0.02を維持し完全に頑健
だったが、置換検定はp_perm=0.040とFDR後のq値ほど明確ではないボーダーラインの結果
だった(`EFFECT_MODIFICATION_ANALYSIS.md` §4, §7)。

CDR-SBはCDRの6下位領域(記憶・見当識・判断力問題解決・地域社会の活動・家庭趣味・
身の回りの世話)の合計であり、意欲低下との関連がどの下位領域に由来するかは
未検定である。意欲低下(apathy)は臨床的には動機づけ・自発性の低下であり、
記憶・見当識のような中核的な認知機能そのものよりも、活動への参加を要する
手段的(instrumental)領域(地域社会の活動・家庭趣味・身の回りの世話)を特異的に
悪化させると予想するのが臨床的に自然な仮説である。本解析はこの仮説を事前に
規定し、CDR6下位領域それぞれについて時間×意欲低下の交互作用を検定する
(結果は有意・非有意を問わずすべて報告する)。

H-D(6検定、1ファミリーとしてBH-FDR補正):
  CDR下位領域6つ(記憶・見当識・判断力問題解決・地域社会の活動・家庭趣味・
  身の回りの世話)それぞれについて、混合効果モデル `score ~ time_c * 意欲低下`
  (ランダム切片)で交互作用項を検定する。2-Bと同一の手法・パネル構築(0/6/12/18か月)。
  易怒性はN=3ときわめて少なく2-Bですでに検出力不足と判断されているため、本解析では
  意欲低下(N=12)のみを対象とする。

FDR補正はH-D単独の6検定ファミリーとして実施し、2-Bの結果とはプールしない
(本プロジェクト一貫の方針)。FDR補正後に有意だった検定について、2-Bと同じ枠組みで
leave-one-out感度分析と置換検定を実施する。
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


cdr = sheet_to_df("CDR")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(cdr["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}

psych_apathy = psych.set_index("研究番号")["意欲低下"].astype(float)

CDR_DOMAINS = [
    ("記憶", "認知系"), ("見当識", "認知系"), ("判断力・問題解決", "認知系"),
    ("地域社会の活動", "機能系"), ("家庭・趣味", "機能系"), ("身の回りの世話", "機能系"),
]


def build_panel(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


def fit_interaction_model(panel, moderator_series, center=False):
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


def permutation_interaction_test(panel, moderator_series, observed_coef, label, n_perm=N_PERM):
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
        panel["mod"] = m
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
# H-D: CDR6下位領域 × 意欲低下 の時間交互作用
# ===========================================================================
rows = []
panels = {}
n_apathy = int(psych_apathy.reindex(STUDY_IDS).sum())
for domain, category in CDR_DOMAINS:
    panel = build_panel(cdr, domain)
    panels[domain] = panel
    n_obs, n_subj, coef_int, p_int, conv = fit_interaction_model(panel, psych_apathy)
    rows.append({
        "CDR下位領域": domain, "分類(事前規定)": category,
        "N(観測数)": n_obs, "N(症例数)": n_subj, "N(意欲低下あり症例)": n_apathy,
        "交互作用項係数(time×意欲低下)": coef_int, "p値": p_int, "収束": conv,
    })
hd_df = pd.DataFrame(rows)
valid_hd = hd_df["p値"].notna()
q_hd = pd.Series(np.nan, index=hd_df.index)
if valid_hd.sum() > 0:
    _, qvals, _, _ = multipletests(hd_df.loc[valid_hd, "p値"], method="fdr_bh")
    q_hd.loc[valid_hd] = qvals
hd_df["q値(BH-FDR)"] = q_hd
hd_df.to_csv(f"{OUT}/120_psych_subdomain_specificity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証: FDR補正後に有意だった検定についてLOO・置換検定を実施
# ===========================================================================
loo_frames = []
perm_rows = []
sig_hd = hd_df[hd_df["q値(BH-FDR)"] < 0.05]
for _, r in sig_hd.iterrows():
    domain = r["CDR下位領域"]
    panel = panels[domain]
    label = f"{domain} × 意欲低下"
    loo_frames.append(loo_interaction_sensitivity(panel, psych_apathy, label))
    perm_rows.append(permutation_interaction_test(panel, psych_apathy, r["交互作用項係数(time×意欲低下)"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/121_psych_subdomain_loo.csv", index=False, encoding="utf-8-sig")

perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/122_psych_subdomain_permutation.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 解釈補助: 群別の個人別傾き(記述統計、新規検定ではない、2-Bの75番ファイルと同じ枠組み)
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
for domain, category in CDR_DOMAINS:
    slopes = per_subject_slope(panels[domain])
    apathy_group = psych_apathy.reindex(slopes.index)
    with_a = slopes[apathy_group == 1]
    without_a = slopes[apathy_group == 0]
    desc_rows.append({
        "CDR下位領域": domain, "分類(事前規定)": category,
        "意欲低下あり_N": len(with_a), "意欲低下あり_傾き平均(/月)": with_a.mean(),
        "意欲低下なし_N": len(without_a), "意欲低下なし_傾き平均(/月)": without_a.mean(),
    })
desc_df = pd.DataFrame(desc_rows)
desc_df.to_csv(f"{OUT}/124_psych_subdomain_group_slope_descriptive.csv", index=False, encoding="utf-8-sig")
print("\n=== 解釈補助: 意欲低下の有無別、CDR下位領域ごとの個人別傾き平均(記述統計) ===")
print(desc_df.to_string(index=False))

with open(f"{OUT}/123_psych_subdomain_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "hd_n_tests": len(hd_df), "hd_n_tested": int(valid_hd.sum()),
        "n_apathy": n_apathy, "n_loo_runs": len(loo_df),
        "n_perm": N_PERM, "n_perm_runs": len(perm_df),
        "background_finding": "CDR-SB x 意欲低下 (2-B): coef=0.0692, p=0.00176, q=0.0106, "
                               "LOO robust (33/33, max p=0.0137), permutation p=0.040 (borderline)",
    }, f, ensure_ascii=False, indent=2)

print("=== H-D: CDR6下位領域 × 意欲低下 の時間交互作用(事前分類: 認知系 vs 機能系) ===")
print(hd_df.to_string(index=False))

if len(loo_df):
    print("\n=== Leave-one-out感度分析(FDR補正後有意だった検定について) ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後に有意な検定はなかったため、LOO・置換検定は実施対象なし ***")
