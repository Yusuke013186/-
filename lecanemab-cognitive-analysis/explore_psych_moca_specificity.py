"""
深掘りステップ7: MoCA-J合計でも意欲低下との時間交互作用は見られるか(主要3項目からの抜け穴埋め)

背景: 2-B(`explore_effect_modification.py`)のFamily 2は、時間×精神症状の交互作用を
「主要3項目」(MMSE合計・CDR-SB・Global CDR)についてのみ検定した。MoCA-Jはこの主要3項目に
含まれておらず、本プロジェクトを通じて意欲低下との交互作用を一度も検定されていない。

MoCA-Jをこれまで主要3項目から除外してきたのは、後述する深刻な欠測パターンが理由である
(`explore_missingness.py`等で既知)。0/6/12/18か月のうちMoCA-J合計が観測されている症例数は
0か月=32、6か月=18、12か月=4、18か月=26であり、特に12か月はわずか4症例しか値がない。
2症例以上の時点を持つ症例は33例中28例にとどまり、各症例が持つ観測時点数も1〜4とまちまちで
ある。この欠測パターンは深刻な限界であり、本検定の結果はその点を割り引いて解釈する必要が
あることをあらかじめ明記する。

それでもなお、MMSE合計・CDR-SBという「主要3項目」のうち2項目で意欲低下との交互作用を
検定済み(MMSE合計は非有意、CDR-SBは2-Bで有意)である以上、第3の主要な総合認知指標である
MoCA-J合計についても同一の枠組みで検定し、結果を有意・非有意を問わず報告することが
一貫性のある対応である。易怒性はN=3で検出力不足のため、本解析でも対象外とする
(2-B・H-D・H-Eと同じ判断)。

H-F(1検定、単独のためFDR補正は不要、p値をそのまま報告する):
  MoCA-J合計 ~ time_c × 意欲低下 (ランダム切片混合モデル)。2-B・H-D・H-Eと同一の手法・
  パネル構築(0/6/12/18か月)。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
import statsmodels.formula.api as smf

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


moca = sheet_to_df("MoCA-J")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(moca["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}

psych_apathy = psych.set_index("研究番号")["意欲低下"].astype(float)


def build_panel(df, col):
    sub = df[df["時点"].isin(TIME_MAP)].copy()
    sub = sub[sub["研究番号"].isin(STUDY_IDS)]
    sub["time"] = sub["時点"].map(TIME_MAP)
    sub["score"] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["score"])
    return sub[["研究番号", "time", "score"]].rename(columns={"研究番号": "subject"})


def fit_interaction_model(panel, moderator_series):
    panel = panel.copy()
    mean_t = panel["time"].mean()
    panel["time_c"] = panel["time"] - mean_t
    mod = moderator_series.reindex(panel["subject"].values).values.astype(float)
    panel["mod"] = mod
    panel = panel.dropna(subset=["mod"])
    n_obs = len(panel)
    n_subj = panel["subject"].nunique()
    n_with_2plus = (panel.groupby("subject").size() >= 2).sum()
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
    return n_obs, n_subj, n_with_2plus, coef_int, p_int, converged


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
# H-F: MoCA-J合計 × 意欲低下 の時間交互作用(単独検定、FDR補正不要)
# ===========================================================================
panel = build_panel(moca, "合計_原資料記載値")
n_apathy = int(psych_apathy.reindex(STUDY_IDS).sum())
n_per_tp = {tp: int(panel[panel["time"] == t].shape[0]) for tp, t in TIME_MAP.items()}
n_obs, n_subj, n_with_2plus, coef_int, p_int, conv = fit_interaction_model(panel, psych_apathy)

hf_row = {
    "結果変数": "MoCA-J合計", "N(観測数)": n_obs, "N(症例数)": n_subj,
    "N(2時点以上)": n_with_2plus, "N(意欲低下あり症例)": n_apathy,
    "時点別N": json.dumps(n_per_tp, ensure_ascii=False),
    "交互作用項係数(time×意欲低下)": coef_int, "p値": p_int, "収束": conv,
}
hf_df = pd.DataFrame([hf_row])
hf_df.to_csv(f"{OUT}/140_psych_moca_specificity.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証: p<0.05の場合のみLOO・置換検定を実施(単独検定のためq値ではなくp値で判断)
# ===========================================================================
loo_df = pd.DataFrame()
perm_df = pd.DataFrame()
if pd.notna(p_int) and p_int < 0.05:
    label = "MoCA-J合計 × 意欲低下"
    loo_df = loo_interaction_sensitivity(panel, psych_apathy, label)
    loo_df.to_csv(f"{OUT}/141_psych_moca_loo.csv", index=False, encoding="utf-8-sig")
    perm_row = permutation_interaction_test(panel, psych_apathy, coef_int, label)
    perm_df = pd.DataFrame([perm_row])
    perm_df.to_csv(f"{OUT}/142_psych_moca_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/143_psych_moca_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "hf_n_tests": 1, "n_apathy": n_apathy, "n_subj_2plus_timepoints": int(n_with_2plus),
        "n_per_timepoint": n_per_tp, "n_perm": N_PERM, "n_loo_runs": len(loo_df), "n_perm_runs": len(perm_df),
        "missingness_caveat": "12か月N=4と極端に少なく、主要3項目(MMSE合計/CDR-SB/Global CDR)から"
                               "MoCA-Jが除外されてきた既知の理由。本検定の結果はこの欠測パターンを"
                               "割り引いて解釈する必要がある。",
    }, f, ensure_ascii=False, indent=2)

print("=== H-F: MoCA-J合計 × 意欲低下 の時間交互作用(単独検定) ===")
print(hf_df.to_string(index=False))
if len(loo_df):
    print("\n=== Leave-one-out感度分析 ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df):
    print("\n*** p>=0.05のため、LOO・置換検定は実施対象なし ***")
