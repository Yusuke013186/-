"""
深掘りステップ6: 精神症状(意欲低下)はMMSEのどの下位項目を悪化させるか(H-Dの対構造)

背景: H-D(`explore_psych_subdomain_specificity.py`)で、CDR6下位領域のうち
「記憶」領域が意欲低下との時間交互作用において最も頑健だった(q=0.00199、
LOO・置換検定とも頑健)。本解析はその対構造として、MMSE11下位項目について
同様の時間×意欲低下交互作用を検定する。CDRの記憶領域所見が真に「記憶という
認知ドメイン」を反映するものであれば、MMSE側の記憶関連項目(記銘・遅延再生)
でも同様の交互作用が観察されるはずだという、収束的妥当性の確認を兼ねた
事前規定の追加検定である。

MMSE下位項目は採点範囲が0〜5点(時間見当識・場所見当識・注意計算)、0〜3点
(記銘)、0〜2点(物品呼称)、0〜1点(他の多くの項目)とさまざまであり、特に
天井効果が強い項目(物品呼称・記銘・復唱・読字理解・書字など)は、追跡期間中に
値が変化する症例がきわめて少なく、交互作用検定の信頼性が乏しい。そこで
ALL_PAIRS_SCAN.mdと同じ方針で、追跡期間中に値が変化した症例数(非モーダル
変化症例数)が5未満の項目には低分散注意フラグを付与し、頑健な新規所見の
候補からは除外する。

H-E(11検定、1ファミリーとしてBH-FDR補正):
  MMSE下位項目11個それぞれについて、混合効果モデル `score ~ time_c × 意欲低下`
  (ランダム切片)で交互作用項を検定する。2-B・H-Dと同一の手法・パネル構築
  (0/6/12/18か月)。易怒性はN=3で検出力不足のため対象外(2-B・H-Dと同じ判断)。

FDR補正はH-E単独の11検定ファミリーとして実施し、他のどの解析ファミリーとも
プールしない(本プロジェクト一貫の方針)。FDR補正後に有意、かつ低分散注意の
付かない検定について、leave-one-out感度分析と置換検定を実施する。
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
LOW_VAR_THRESHOLD = 5

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}

psych_apathy = psych.set_index("研究番号")["意欲低下"].astype(float)

MMSE_ITEMS = [
    "時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
    "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写",
]
MEMORY_RELATED = {"記銘", "遅延再生"}


def build_panel(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


def n_subjects_with_change(panel):
    n = 0
    for sid, g in panel.groupby("subject"):
        if len(g) >= 2 and g["score"].nunique() > 1:
            n += 1
    return n


def fit_interaction_model(panel, moderator_series):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    mod = moderator_series.reindex(panel["subject"].values).values.astype(float)
    panel["mod"] = mod
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
    panel["mod"] = mod
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
# H-E: MMSE11下位項目 × 意欲低下 の時間交互作用
# ===========================================================================
rows = []
panels = {}
n_apathy = int(psych_apathy.reindex(STUDY_IDS).sum())
for item in MMSE_ITEMS:
    panel = build_panel(mmse, item)
    panels[item] = panel
    n_changed = n_subjects_with_change(panel)
    n_obs, n_subj, coef_int, p_int, conv = fit_interaction_model(panel, psych_apathy)
    rows.append({
        "MMSE下位項目": item, "記憶関連項目(事前分類)": item in MEMORY_RELATED,
        "N(観測数)": n_obs, "N(症例数)": n_subj, "N(意欲低下あり症例)": n_apathy,
        "N(追跡中に値が変化した症例)": n_changed,
        "低分散注意": n_changed < LOW_VAR_THRESHOLD,
        "交互作用項係数(time×意欲低下)": coef_int, "p値": p_int, "収束": conv,
    })
he_df = pd.DataFrame(rows)
valid_he = he_df["p値"].notna()
q_he = pd.Series(np.nan, index=he_df.index)
if valid_he.sum() > 0:
    _, qvals, _, _ = multipletests(he_df.loc[valid_he, "p値"], method="fdr_bh")
    q_he.loc[valid_he] = qvals
he_df["q値(BH-FDR)"] = q_he
he_df.to_csv(f"{OUT}/130_psych_mmse_subitem_specificity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証: FDR補正後有意 かつ 低分散注意のつかない検定についてLOO・置換検定
# ===========================================================================
loo_frames = []
perm_rows = []
sig_he = he_df[(he_df["q値(BH-FDR)"] < 0.05) & (~he_df["低分散注意"])]
for _, r in sig_he.iterrows():
    item = r["MMSE下位項目"]
    panel = panels[item]
    label = f"{item} × 意欲低下"
    loo_frames.append(loo_interaction_sensitivity(panel, psych_apathy, label))
    perm_rows.append(permutation_interaction_test(panel, psych_apathy, r["交互作用項係数(time×意欲低下)"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/131_psych_mmse_subitem_loo.csv", index=False, encoding="utf-8-sig")

perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/132_psych_mmse_subitem_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/133_psych_mmse_subitem_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "he_n_tests": len(he_df), "he_n_tested": int(valid_he.sum()),
        "n_apathy": n_apathy, "n_loo_runs": len(loo_df),
        "n_perm": N_PERM, "n_perm_runs": len(perm_df),
        "low_var_threshold": LOW_VAR_THRESHOLD,
        "background_finding": "CDR:記憶 x 意欲低下 (H-D): coef=0.0174, q=0.00199, "
                               "LOO robust (33/33), permutation p=0.003",
    }, f, ensure_ascii=False, indent=2)

print("=== H-E: MMSE11下位項目 × 意欲低下 の時間交互作用 ===")
print(he_df.to_string(index=False))

if len(loo_df):
    print("\n=== Leave-one-out感度分析(FDR補正後有意・低分散注意なしの検定について) ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")
