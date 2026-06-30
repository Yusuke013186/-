"""
深掘りステップ9: MMSE場所見当識の5下位構成要素(県・市・病院・階・地方)のうち
どれが最も落ちやすいか、また「どれが落ちるか」は他のどの項目と関連するか

背景: MMSE「場所見当識」(0〜5点)は採点表上、県・市・病院・階・地方の5つの
個別正誤(各0/1点)の合計として記録されている(`data`シートの場所_県/場所_市/
場所_病院/場所_階/場所_地方列)。本プロジェクトのこれまでの解析はすべて
「場所見当識」を合計5点の単一変数として扱っており、下位構成要素レベルの
分析は未実施だった。

Part 1: 記述統計 — 5構成要素それぞれの不正解率(全観測プール・ベースライン・
追跡期間中に一度でも不正解だった症例数)を集計する。

Part 2: 相関探索 — 各構成要素について「追跡期間中(0/6/12/18か月)に一度でも
不正解だった症例」と「常に正解だった症例」の2群に分け、ALL_PAIRS_SCANと同じ
21変数(ベースライン値・Δ)・精神症状(意欲低下)との関連をMann-Whitney U検定/
Fisher正確検定で網羅的に検定する(県は全例正解で分散ゼロのため検定対象外)。
ALL_PAIRS_SCANと同じ低分散注意フラグ(非モーダル数<5)、および場所見当識・
MMSE合計という構造的に部分-全体関係にある変数への注意フラグを付与する。
1ファミリーとしてBH-FDR補正し、補正後有意かつ低分散注意・構造的注意のつかない
検定についてleave-one-out感度分析・置換検定で頑健性を確認する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
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


PLACE_ITEMS = ["場所_県", "場所_市", "場所_病院", "場所_階", "場所_地方"]

# ===========================================================================
# Part 1: 記述統計 — どの構成要素が最も落ちやすいか
# ===========================================================================
sub_all = mmse[mmse["時点"].isin(TIME_MAP)].copy()
desc_rows = []
ever_fail = {}
for col in PLACE_ITEMS:
    s_all = pd.to_numeric(sub_all[col], errors="coerce").dropna()
    n_obs = len(s_all)
    n_fail_obs = int((s_all == 0).sum())
    base = mmse[mmse["時点"] == "0か月"]
    s_base = pd.to_numeric(base[col], errors="coerce").dropna()
    n_base = len(s_base)
    n_fail_base = int((s_base == 0).sum())
    sub_all[col + "_num"] = pd.to_numeric(sub_all[col], errors="coerce")
    g = sub_all.groupby("研究番号")[col + "_num"].apply(lambda x: (x == 0).any() if x.notna().any() else np.nan)
    g = g.reindex(STUDY_IDS)
    ever_fail[col] = g
    desc_rows.append({
        "構成要素": col, "全観測N": n_obs, "全観測不正解数": n_fail_obs,
        "全観測不正解率(%)": round(n_fail_obs / n_obs * 100, 1) if n_obs else np.nan,
        "ベースラインN": n_base, "ベースライン不正解数": n_fail_base,
        "ベースライン不正解率(%)": round(n_fail_base / n_base * 100, 1) if n_base else np.nan,
        "追跡中に一度でも不正解だった症例数": int(g.sum(skipna=True)), "評価可能症例数": int(g.notna().sum()),
    })
desc_df = pd.DataFrame(desc_rows).sort_values("全観測不正解率(%)", ascending=False)
desc_df.to_csv(f"{OUT}/160_mmse_place_subcomponent_descriptive.csv", index=False, encoding="utf-8-sig")
print("=== Part 1: MMSE場所見当識5構成要素の不正解率(落ちやすさ) ===")
print(desc_df.to_string(index=False))

# ===========================================================================
# Part 2: 相関探索 — 21変数(ベースライン・Δ)+ 精神症状(意欲低下)
# ===========================================================================
VAR_DEFS = [
    ("MMSE合計", mmse, "下位項目合計_自動計算", "主要"),
    ("CDR-SB", cdr, "CDR-SB_自動計算", "主要"),
    ("Global CDR", cdr, "Global CDR_原資料記載値", "主要"),
    ("MoCA-J合計", moca, "合計_原資料記載値", "主要"),
]
for item in ["時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
             "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写"]:
    VAR_DEFS.append((f"MMSE:{item}", mmse, item, "MMSE下位"))
for item in ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]:
    VAR_DEFS.append((f"CDR:{item}", cdr, item, "CDR下位"))
names = [v[0] for v in VAR_DEFS]


def get_series(df, col, timepoint):
    d = df[df["時点"] == timepoint].set_index("研究番号")[col]
    d = pd.to_numeric(d, errors="coerce").dropna()
    return d[d.index.isin(STUDY_IDS)]


baseline, delta = {}, {}
for name, df, col, grp in VAR_DEFS:
    s0 = get_series(df, col, "0か月")
    s18 = get_series(df, col, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    baseline[name] = s0
    delta[name] = (s18.loc[common] - s0.loc[common]).reindex(common)


def n_nonmodal(s):
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


baseline_nonmodal = {a: n_nonmodal(baseline[a]) for a in names}
delta_nonmodal = {a: n_nonmodal(delta[a]) for a in names}

STRUCTURAL = {"MMSE合計", "MMSE:場所見当識"}  # 場所見当識の構成要素を含むため部分-全体関係


def mannwhitney_safe(group_labels, y):
    common = sort_ids(set(group_labels.dropna().index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan, np.nan, np.nan
    g = group_labels.loc[common]
    yv = y.loc[common]
    cats = sorted(g.unique())
    if len(cats) != 2:
        return n, np.nan, np.nan, np.nan, np.nan
    g1 = yv[g == cats[0]]
    g2 = yv[g == cats[1]]
    if len(g1) < 2 or len(g2) < 2 or np.unique(yv.values).size == 1:
        return n, np.nan, np.nan, np.nan, np.nan
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    r = 1 - (2 * u) / (len(g1) * len(g2))
    return n, u, p, r, f"{cats[0]}(N={len(g1)}) vs {cats[1]}(N={len(g2)})"


def loo_mannwhitney(group_labels, y, label):
    common = sort_ids(set(group_labels.dropna().index) & set(y.index))
    rows = []
    for sid in common:
        keep = [s for s in common if s != sid]
        g = group_labels.loc[keep]
        yv = y.loc[keep]
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
    common = sort_ids(set(group_labels.dropna().index) & set(y.index))
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
            continue
    perm_rs = np.array(perm_rs)
    p_perm = float(np.mean(np.abs(perm_rs) >= np.abs(observed_r))) if len(perm_rs) > 0 else np.nan
    return {"検定": label, "観測効果量r": observed_r, "置換検定p値": p_perm, "n_perm": n_perm, "n_failed": n_failed}


apathy = psych.set_index("研究番号")["意欲低下"].astype(float).reindex(STUDY_IDS)

rows = []
for comp in ["場所_市", "場所_病院", "場所_階", "場所_地方"]:  # 場所_県は分散ゼロのため対象外
    grp = ever_fail[comp].map({True: "落ちた", False: "落ちなかった"})
    for vname in names:
        n, u, p, r, glabel = mannwhitney_safe(grp, baseline[vname])
        rows.append({
            "構成要素": comp, "検定種別": "ベースライン", "比較変数": vname, "群構成": glabel,
            "N": n, "効果量r": r, "p値": p,
            "構造的部分全体注意": vname in STRUCTURAL,
            "低分散注意": baseline_nonmodal.get(vname, 99) < FRAGILE_THRESHOLD,
        })
        n, u, p, r, glabel = mannwhitney_safe(grp, delta[vname])
        rows.append({
            "構成要素": comp, "検定種別": "Δ(0→18か月)", "比較変数": vname, "群構成": glabel,
            "N": n, "効果量r": r, "p値": p,
            "構造的部分全体注意": vname in STRUCTURAL,
            "低分散注意": delta_nonmodal.get(vname, 99) < FRAGILE_THRESHOLD,
        })
    # 精神症状(意欲低下)との関連: Fisher正確検定(両方とも二値)
    common = sort_ids(set(grp.dropna().index) & set(apathy.dropna().index))
    if len(common) >= 5:
        ct = pd.crosstab(grp.loc[common], apathy.loc[common])
        if ct.shape == (2, 2):
            odds, p = stats.fisher_exact(ct.values)
            rows.append({
                "構成要素": comp, "検定種別": "精神症状", "比較変数": "意欲低下", "群構成": f"N={len(common)}",
                "N": len(common), "効果量r": np.nan, "p値": p,
                "構造的部分全体注意": False, "低分散注意": False, "オッズ比": odds,
            })

hh_df = pd.DataFrame(rows)
valid = hh_df["p値"].notna()
q = pd.Series(np.nan, index=hh_df.index)
if valid.sum() > 0:
    _, qvals, _, _ = multipletests(hh_df.loc[valid, "p値"], method="fdr_bh")
    q.loc[valid] = qvals
hh_df["q値(BH-FDR)"] = q
hh_df.to_csv(f"{OUT}/161_mmse_place_subcomponent_correlates.csv", index=False, encoding="utf-8-sig")

print(f"\n=== Part 2: 構成要素ごとの「落ちた/落ちなかった」群と他変数の関連(計{len(hh_df)}検定、BH-FDR補正) ===")
sig_df = hh_df[hh_df["q値(BH-FDR)"] < 0.05].sort_values("q値(BH-FDR)")
if len(sig_df):
    print(sig_df.to_string(index=False))
else:
    print("FDR補正後有意な検定なし(最小q値 = {:.4f})".format(hh_df["q値(BH-FDR)"].min()))

# ===========================================================================
# 頑健性検証: FDR補正後有意 かつ 構造的注意・低分散注意のない検定
# ===========================================================================
loo_frames, perm_rows = [], []
robust_candidates = hh_df[
    (hh_df["q値(BH-FDR)"] < 0.05) & (~hh_df["構造的部分全体注意"]) & (~hh_df["低分散注意"]) & (hh_df["検定種別"] != "精神症状")
]
for _, r in robust_candidates.iterrows():
    comp, kind, vname = r["構成要素"], r["検定種別"], r["比較変数"]
    grp = ever_fail[comp].map({True: "落ちた", False: "落ちなかった"})
    y = baseline[vname] if kind == "ベースライン" else delta[vname]
    label = f"{comp}({kind}) × {vname}"
    loo_frames.append(loo_mannwhitney(grp, y, label))
    perm_rows.append(permutation_mannwhitney(grp, y, r["効果量r"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/162_mmse_place_subcomponent_loo.csv", index=False, encoding="utf-8-sig")
perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/163_mmse_place_subcomponent_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/164_mmse_place_subcomponent_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_tests": len(hh_df), "n_tested": int(valid.sum()), "fragile_threshold": FRAGILE_THRESHOLD,
        "n_perm": N_PERM, "n_loo_runs": len(loo_df), "n_perm_runs": len(perm_df),
        "place_subcomponents": PLACE_ITEMS,
        "note": "場所_県は全観測で1点(不正解0件)のため相関探索の対象外。",
    }, f, ensure_ascii=False, indent=2)

if len(loo_df):
    print("\n=== Leave-one-out感度分析 ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ構造的注意・低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")
