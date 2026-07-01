"""
深掘りステップ12: MMSE認知ドメイン合算スコア × 意欲低下(H-K)

背景と動機:
  H-E(混合効果モデル時間交互作用)・H-G(ベースライン/Δ Mann-Whitney)で
  MMSE11下位項目を個別に意欲低下と比較したが、すべて補正後非有意だった。
  主因は各項目の天井効果(記銘: ほぼ全例3/3、物品呼称: ほぼ全例2/2 等)で
  分散が極端に低く、Mann-WhitneyやSpearmanで差を検出できない状態にある。

  一方、標準的な神経心理学的アプローチでは、MMSE下位項目を認知ドメインごとに
  合算することで天井効果を部分的に軽減し、検出力を改善する。本解析はMMSE30点を
  4認知ドメイン合算スコアに集約して同一の検定を再実施する(H-K)。

認知ドメイン定義(MMSE標準分類に基づく):
  1. 見当識合計: 時間見当識(0-5) + 場所見当識(0-5) = 0-10
  2. 記憶合計:   記銘(0-3) + 遅延再生(0-3)         = 0-6
  3. 言語合計:   物品呼称(0-2)+復唱(0-1)+読字理解(0-1)+書字(0-1) = 0-5
  4. 注意実行合計: 注意計算(0-5)+3段階命令(0-3)+図形模写(0-1) = 0-9

  (4ドメイン合計 = 10+6+5+9 = 30 = MMSE合計 ✓)

H-K-A(8検定): 4ドメイン合算スコア × 意欲低下、ベースライン値とΔ(0→18か月)を
  Mann-Whitney U比較、1ファミリーとしてBH-FDR補正。
H-K-B(4検定): 4ドメイン合算スコアの時間×意欲低下交互作用(スロープ差)を
  ランダム切片混合効果モデルで検定、1ファミリーとしてBH-FDR補正。

H-K-AとH-K-Bを別ファミリーとするのは、検定統計量が異なるため
(Mann-WhitneyのU値 vs 混合モデルのz/t統計量)p値の性質が異なり、
プロジェクト既出の先例(H-E: 混合モデルのみ、H-G: Mann-Whitneyのみ)に合わせ
検定手法ごとに独立補正するのが適切なため。

FDR補正後有意かつ低分散注意(非モーダル数<5)のない検定について
Leave-one-out感度分析と置換検定(B=1000)で頑健性を確認する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_PERM = 1000
FRAGILE_THRESHOLD = 5

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    return pd.DataFrame(rows[1:], columns=rows[0])


mmse = sheet_to_df("MMSE")
psych = sheet_to_df("精神症状")
STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))
TIME_MAP = {"0か月": 0, "6か月": 6, "12か月": 12, "18か月": 18}


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


apathy_df = psych.set_index("研究番号")["意欲低下"].astype(float)
apathy_group = apathy_df.apply(lambda v: "あり" if v == 1 else ("なし" if v == 0 else np.nan))
apathy_group = apathy_group.reindex(STUDY_IDS).dropna()

n_apathy = int((apathy_group == "あり").sum())
n_no_apathy = int((apathy_group == "なし").sum())

DOMAINS = {
    "見当識合計(0-10)": ["時間見当識", "場所見当識"],
    "記憶合計(0-6)":    ["記銘", "遅延再生"],
    "言語合計(0-5)":    ["物品呼称", "復唱", "読字理解", "書字"],
    "注意実行合計(0-9)": ["注意計算", "3段階命令", "図形模写"],
}


def get_item(item, timepoint):
    d = mmse[mmse["時点"] == timepoint].set_index("研究番号")[item]
    return pd.to_numeric(d, errors="coerce").dropna()


def build_composite(items, timepoint):
    series_list = [get_item(it, timepoint) for it in items]
    common = sort_ids(set.intersection(*[set(s.index) for s in series_list]) & set(STUDY_IDS))
    return pd.Series(
        {sid: sum(s.loc[sid] for s in series_list) for sid in common},
        name="_".join(items),
    )


def n_nonmodal(s):
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


# ベースラインと18か月の合算スコア
composites_base = {name: build_composite(items, "0か月") for name, items in DOMAINS.items()}
composites_18 = {name: build_composite(items, "18か月") for name, items in DOMAINS.items()}
composites_delta = {}
for name in DOMAINS:
    b, e = composites_base[name], composites_18[name]
    common = sort_ids(set(b.index) & set(e.index))
    composites_delta[name] = (e.loc[common] - b.loc[common]).reindex(common)


def mannwhitney_safe(group_labels, y):
    common = sort_ids(set(group_labels.index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan, np.nan, np.nan
    g = group_labels.loc[common]
    yv = y.loc[common]
    cats = sorted(g.unique())
    if len(cats) != 2:
        return n, np.nan, np.nan, np.nan, np.nan
    g1, g2 = yv[g == cats[0]], yv[g == cats[1]]
    if len(g1) < 2 or len(g2) < 2 or np.unique(yv.values).size == 1:
        return n, np.nan, np.nan, np.nan, np.nan
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    r = 1 - (2 * u) / (len(g1) * len(g2))
    return n, u, p, r, f"{cats[0]}(N={len(g1)}) vs {cats[1]}(N={len(g2)})"


def loo_mannwhitney(group_labels, y, label):
    common = sort_ids(set(group_labels.index) & set(y.index))
    rows = []
    for sid in common:
        keep = [s for s in common if s != sid]
        g, yv = group_labels.loc[keep], y.loc[keep]
        cats = sorted(g.unique())
        if len(cats) != 2:
            rows.append({"検定": label, "除外症例": sid, "除外後p値": np.nan, "除外後効果量r": np.nan})
            continue
        g1, g2 = yv[g == cats[0]], yv[g == cats[1]]
        try:
            u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            r = 1 - (2 * u) / (len(g1) * len(g2))
        except Exception:
            p = r = np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後p値": p, "除外後効果量r": r})
    return pd.DataFrame(rows)


def permutation_mannwhitney(group_labels, y, observed_r, label, n_perm=N_PERM):
    common = sort_ids(set(group_labels.index) & set(y.index))
    g_vals = group_labels.loc[common].values
    yv = y.loc[common].values
    perm_rs, n_failed = [], 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(g_vals)
        cats = sorted(set(shuffled))
        g1, g2 = yv[shuffled == cats[0]], yv[shuffled == cats[1]]
        try:
            u, _ = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            perm_rs.append(1 - (2 * u) / (len(g1) * len(g2)))
        except Exception:
            n_failed += 1
    perm_rs = np.array(perm_rs)
    p_perm = float(np.mean(np.abs(perm_rs) >= np.abs(observed_r))) if len(perm_rs) > 0 else np.nan
    return {"検定": label, "観測効果量r": observed_r, "置換検定p値": p_perm,
            "n_perm": n_perm, "n_failed": n_failed}


# ===========================================================================
# H-K-A: Mann-Whitney (ベースライン・Δ) × 意欲低下
# ===========================================================================
hka_rows = []
for name in DOMAINS:
    for kind, y in [("ベースライン", composites_base[name]), ("Δ(0→18か月)", composites_delta[name])]:
        n, u, p, r, glabel = mannwhitney_safe(apathy_group, y)
        nm = n_nonmodal(y)
        hka_rows.append({
            "認知ドメイン": name, "比較種別": kind, "群構成": glabel,
            "N": n, "統計量(U)": u, "効果量r": r, "p値": p,
            "低分散注意": nm < FRAGILE_THRESHOLD, "非モーダル数": nm,
        })

hka_df = pd.DataFrame(hka_rows)
valid_a = hka_df["p値"].notna()
q_a = pd.Series(np.nan, index=hka_df.index)
if valid_a.sum() > 0:
    _, qvals, _, _ = multipletests(hka_df.loc[valid_a, "p値"], method="fdr_bh")
    q_a.loc[valid_a] = qvals
hka_df["q値(BH-FDR)"] = q_a

print(f"=== H-K-A: MMSE認知ドメイン合算スコア × 意欲低下 ベースライン・Δ({len(hka_df)}検定) ===")
print(f"意欲低下あり: N={n_apathy}、なし: N={n_no_apathy}")
print()
print(hka_df.to_string(index=False))

# 記述統計: 各ドメイン・各時点の中央値
print("\n=== 参考: 各ドメインの時点別中央値(意欲低下あり vs なし) ===")
for name, items in DOMAINS.items():
    row_vals = []
    for tp_label, tp in TIME_MAP.items():
        c = build_composite(items, tp_label)
        g = apathy_group.reindex(c.index).dropna()
        c2 = c.reindex(g.index)
        med_yes = c2[g == "あり"].median() if (g == "あり").sum() > 0 else np.nan
        med_no  = c2[g == "なし"].median() if (g == "なし").sum() > 0 else np.nan
        n_yes = int((g == "あり").sum())
        n_no  = int((g == "なし").sum())
        row_vals.append(f"{tp_label}: あり={med_yes:.1f}(N={n_yes}), なし={med_no:.1f}(N={n_no})")
    print(f"\n{name}")
    for rv in row_vals:
        print(f"  {rv}")


# ===========================================================================
# H-K-B: 混合効果モデル 時間×意欲低下交互作用
# ===========================================================================
def build_panel(items):
    frames = []
    for tp_label, t_val in TIME_MAP.items():
        c = build_composite(items, tp_label)
        sub_df = pd.DataFrame({"subject": c.index, "time": t_val, "score": c.values})
        frames.append(sub_df)
    panel = pd.concat(frames, ignore_index=True)
    mod = apathy_df.reindex(panel["subject"].values).values.astype(float)
    panel["mod"] = mod
    panel = panel.dropna(subset=["mod", "score"])
    panel["time_c"] = panel["time"] - panel["time"].mean()
    return panel


def fit_interaction(panel, domain_name):
    n_obs = len(panel)
    n_subj = panel["subject"].nunique()
    n_with_2plus = int((panel.groupby("subject").size() >= 2).sum())
    try:
        md = smf.mixedlm("score ~ time_c * mod", data=panel, groups=panel["subject"])
        mdf = md.fit(reml=True)
        coef = mdf.params.get("time_c:mod", np.nan)
        p = mdf.pvalues.get("time_c:mod", np.nan)
        converged = bool(mdf.converged)
    except Exception:
        coef = p = np.nan
        converged = False
    return {"認知ドメイン": domain_name, "N(観測数)": n_obs, "N(症例数)": n_subj,
            "N(2時点以上)": n_with_2plus, "交互作用係数(time×意欲低下)": coef,
            "p値": p, "収束": converged}


def loo_interaction(panel, label):
    subjects = sort_ids(panel["subject"].unique())
    rows = []
    for sid in subjects:
        sub_panel = panel[panel["subject"] != sid].copy()
        try:
            md = smf.mixedlm("score ~ time_c * mod", data=sub_panel, groups=sub_panel["subject"])
            mdf = md.fit(reml=True)
            p = mdf.pvalues.get("time_c:mod", np.nan)
            coef = mdf.params.get("time_c:mod", np.nan)
        except Exception:
            p = coef = np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後交互作用係数": coef, "除外後p値": p})
    return pd.DataFrame(rows)


def permutation_interaction(panel, observed_coef, label, n_perm=N_PERM):
    subjects = sort_ids(panel["subject"].unique())
    mod_vals = apathy_df.reindex(subjects).values.astype(float)
    valid_mask = ~np.isnan(mod_vals)
    subjects_valid = [s for s, v in zip(subjects, valid_mask) if v]
    mod_valid = mod_vals[valid_mask]
    pan = panel[panel["subject"].isin(subjects_valid)].copy()
    perm_coefs, n_failed = [], 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(mod_valid)
        mod_map = dict(zip(subjects_valid, shuffled))
        pan["mod"] = pan["subject"].map(mod_map).values.astype(float)
        try:
            md = smf.mixedlm("score ~ time_c * mod", data=pan, groups=pan["subject"])
            mdf = md.fit(reml=True)
            perm_coefs.append(mdf.params.get("time_c:mod", np.nan))
        except Exception:
            n_failed += 1
    perm_coefs = np.array([c for c in perm_coefs if not np.isnan(c)])
    p_perm = float(np.mean(np.abs(perm_coefs) >= np.abs(observed_coef))) if len(perm_coefs) > 0 else np.nan
    return {"検定": label, "観測交互作用係数": observed_coef, "置換検定p値": p_perm,
            "n_perm": n_perm, "n_failed": n_failed}


hkb_rows = []
panels = {}
for name, items in DOMAINS.items():
    pan = build_panel(items)
    panels[name] = pan
    hkb_rows.append(fit_interaction(pan, name))

hkb_df = pd.DataFrame(hkb_rows)
valid_b = hkb_df["p値"].notna()
q_b = pd.Series(np.nan, index=hkb_df.index)
if valid_b.sum() > 0:
    _, qvals, _, _ = multipletests(hkb_df.loc[valid_b, "p値"], method="fdr_bh")
    q_b.loc[valid_b] = qvals
hkb_df["q値(BH-FDR)"] = q_b

print(f"\n=== H-K-B: MMSE認知ドメイン合算スコア × 時間×意欲低下交互作用({len(hkb_df)}検定) ===")
print(hkb_df.to_string(index=False))

# 出力
hka_df.to_csv(f"{OUT}/190_psych_mmse_composites_apathy_mw.csv", index=False, encoding="utf-8-sig")
hkb_df.to_csv(f"{OUT}/191_psych_mmse_composites_apathy_lme.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# 頑健性検証
# ===========================================================================
loo_frames_a, perm_rows_a = [], []
sig_a = hka_df[(hka_df["q値(BH-FDR)"] < 0.05) & (~hka_df["低分散注意"])]
for _, r in sig_a.iterrows():
    name = r["認知ドメイン"]
    y = composites_base[name] if r["比較種別"] == "ベースライン" else composites_delta[name]
    label = f"{name}({r['比較種別']}) × 意欲低下"
    loo_frames_a.append(loo_mannwhitney(apathy_group, y, label))
    perm_rows_a.append(permutation_mannwhitney(apathy_group, y, r["効果量r"], label))

loo_frames_b, perm_rows_b = [], []
sig_b = hkb_df[(hkb_df["q値(BH-FDR)"] < 0.05)]
for _, r in sig_b.iterrows():
    name = r["認知ドメイン"]
    label = f"{name} × 意欲低下(時間交互作用)"
    loo_frames_b.append(loo_interaction(panels[name], label))
    perm_rows_b.append(permutation_interaction(panels[name], r["交互作用係数(time×意欲低下)"], label))

loo_df = pd.concat(loo_frames_a + loo_frames_b, ignore_index=True) if (loo_frames_a or loo_frames_b) else pd.DataFrame()
perm_df = pd.DataFrame(perm_rows_a + perm_rows_b) if (perm_rows_a or perm_rows_b) else pd.DataFrame()

if len(loo_df):
    loo_df.to_csv(f"{OUT}/192_psych_mmse_composites_apathy_loo.csv", index=False, encoding="utf-8-sig")
    print("\n=== Leave-one-out感度分析 ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    perm_df.to_csv(f"{OUT}/193_psych_mmse_composites_apathy_permutation.csv", index=False, encoding="utf-8-sig")
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")

with open(f"{OUT}/194_psych_mmse_composites_apathy_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "hka_n_tests": len(hka_df), "hkb_n_tests": len(hkb_df),
        "n_apathy": n_apathy, "n_no_apathy": n_no_apathy,
        "n_perm": N_PERM, "n_loo_a": len(loo_df), "n_perm_runs": len(perm_df),
        "domains": {name: items for name, items in DOMAINS.items()},
        "background": "H-E(混合モデル、個別11項目)・H-G(MW、個別11項目)はいずれも全件非有意。"
                      "本解析は天井効果軽減のためMMSE11項目を4認知ドメインに合算して再検定。",
    }, f, ensure_ascii=False, indent=2)
