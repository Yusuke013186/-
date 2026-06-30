"""
深掘りステップ10: MMSE11下位項目「同士」の関連だけに絞った再検定(H-I)

背景: `explore_all_pairs.py`(ALL_PAIRS_SCAN.md)は693検定(MMSE11項目・CDR6項目・
MMSE合計・CDR-SB・Global CDR・MoCA-J合計の計21変数の全組み合わせ)を1ファミリーとして
BH-FDR補正した。この補正後に頑健に残った9件はいずれもMMSE-CDR間・尺度合計同士の
組み合わせであり、**MMSE下位項目「同士」(他の尺度を介さない)の組み合わせで補正後
有意だったものは1件もなかった**(最も近かったのはΔ場所見当識×Δ遅延再生でq=0.076、
有意水準にわずかに届かず)。

本解析はこの「MMSE下位項目同士」という組み合わせだけを取り出した狭いファミリーとして
独立にBH-FDR補正をかけ直す(本プロジェクト一貫の方針: ファミリーは解析の問いごとに
事前規定し、他のファミリーとはプールしない)。693検定という大きなファミリーの中では
補正の重みで埋もれていた関連が、55+121=176検定という狭いファミリーでは検出限界を
超える可能性がある。事後的に都合よく範囲を選んだわけではなく、「MMSE下位項目同士の
関連」という単一の明確な問いを新たに事前規定して全数検定する。

H-I-A(55検定): MMSE11下位項目のΔ(0→18か月)同士の全組み合わせ(C(11,2)=55)。
H-I-B(121検定、自己ペア11件を含む): MMSE11下位項目のベースライン値(A)→Δ(B)の
  全組み合わせ(11×11)。自己ペア(A=B)は回帰効果の参考として残すが、新規所見の
  候補からは除外する。

H-I-AとH-I-Bを合わせた176検定を1ファミリーとしてBH-FDR補正する。低分散注意
(`ALL_PAIRS_SCAN.md`と同じ非モーダル数<5の基準)を付与し、補正後有意かつ低分散注意・
自己ペアでない検定について、leave-one-out感度分析・置換検定で頑健性を確認する。
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
STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


MMSE_ITEMS = [
    "時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
    "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写",
]


def get_series(col, timepoint):
    d = mmse[mmse["時点"] == timepoint].set_index("研究番号")[col]
    d = pd.to_numeric(d, errors="coerce").dropna()
    return d[d.index.isin(STUDY_IDS)]


baseline, delta = {}, {}
for item in MMSE_ITEMS:
    s0 = get_series(item, "0か月")
    s18 = get_series(item, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    baseline[item] = s0
    delta[item] = (s18.loc[common] - s0.loc[common]).reindex(common)


def n_nonmodal(s):
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


baseline_nonmodal = {a: n_nonmodal(baseline[a]) for a in MMSE_ITEMS}
delta_nonmodal = {a: n_nonmodal(delta[a]) for a in MMSE_ITEMS}


def spearman_safe(x, y):
    common = sort_ids(set(x.index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan
    xv, yv = x.loc[common].values, y.loc[common].values
    if np.unique(xv).size == 1 or np.unique(yv).size == 1:
        return n, np.nan, np.nan
    rho, p = stats.spearmanr(xv, yv)
    return n, rho, p


def loo_spearman(x, y, label):
    common = sort_ids(set(x.index) & set(y.index))
    rows = []
    for sid in common:
        keep = [s for s in common if s != sid]
        xv, yv = x.loc[keep].values, y.loc[keep].values
        try:
            rho, p = stats.spearmanr(xv, yv)
        except Exception:
            rho = p = np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後rho": rho, "除外後p値": p})
    return pd.DataFrame(rows)


def permutation_spearman(x, y, observed_rho, label, n_perm=N_PERM):
    common = sort_ids(set(x.index) & set(y.index))
    xv, yv = x.loc[common].values, y.loc[common].values
    perm_rhos, n_failed = [], 0
    for _ in range(n_perm):
        shuffled = RNG.permutation(yv)
        try:
            rho, _ = stats.spearmanr(xv, shuffled)
            perm_rhos.append(rho)
        except Exception:
            n_failed += 1
            continue
    perm_rhos = np.array(perm_rhos)
    p_perm = float(np.mean(np.abs(perm_rhos) >= np.abs(observed_rho))) if len(perm_rhos) > 0 else np.nan
    return {"検定": label, "観測rho": observed_rho, "置換検定p値": p_perm, "n_perm": n_perm, "n_failed": n_failed}


# ===========================================================================
# H-I-A: Δ×Δ 全55組み合わせ
# ===========================================================================
rows = []
for i in range(len(MMSE_ITEMS)):
    for j in range(i + 1, len(MMSE_ITEMS)):
        a, b = MMSE_ITEMS[i], MMSE_ITEMS[j]
        n, rho, p = spearman_safe(delta[a], delta[b])
        rows.append({
            "検定族": "H-I-A: Δ×Δ", "変数A": f"MMSE:{a}(Δ)", "変数B": f"MMSE:{b}(Δ)",
            "自己ペア": False, "N": n, "rho": rho, "p値": p,
            "低分散注意": (delta_nonmodal[a] < FRAGILE_THRESHOLD) or (delta_nonmodal[b] < FRAGILE_THRESHOLD),
        })

# ===========================================================================
# H-I-B: ベースライン(A)→Δ(B) 全121組み合わせ(自己ペア11件含む)
# ===========================================================================
for a in MMSE_ITEMS:
    for b in MMSE_ITEMS:
        n, rho, p = spearman_safe(baseline[a], delta[b])
        rows.append({
            "検定族": "H-I-B: ベースライン→Δ", "変数A": f"MMSE:{a}(baseline)", "変数B": f"MMSE:{b}(Δ)",
            "自己ペア": a == b, "N": n, "rho": rho, "p値": p,
            "低分散注意": (baseline_nonmodal[a] < FRAGILE_THRESHOLD) or (delta_nonmodal[b] < FRAGILE_THRESHOLD),
        })

hi_df = pd.DataFrame(rows)
valid = hi_df["p値"].notna()
q = pd.Series(np.nan, index=hi_df.index)
if valid.sum() > 0:
    _, qvals, _, _ = multipletests(hi_df.loc[valid, "p値"], method="fdr_bh")
    q.loc[valid] = qvals
hi_df["q値(BH-FDR)"] = q
hi_df.to_csv(f"{OUT}/170_mmse_subitem_internal_pairs.csv", index=False, encoding="utf-8-sig")

print(f"=== H-I: MMSE下位項目同士の関連(計{len(hi_df)}検定、176検定族としてBH-FDR補正) ===")
sig_df = hi_df[hi_df["q値(BH-FDR)"] < 0.05].sort_values("q値(BH-FDR)")
if len(sig_df):
    print(sig_df.to_string(index=False))
else:
    print(f"FDR補正後有意な検定なし(最小q値 = {hi_df['q値(BH-FDR)'].min():.4f})")

print("\n=== 参考: 未補正p<0.05だった上位検定(有意・非有意問わず全件表示の一部) ===")
print(hi_df[hi_df["p値"] < 0.05].sort_values("p値").to_string(index=False))

# ===========================================================================
# 頑健性検証: FDR補正後有意 かつ 自己ペアでない・低分散注意のない検定
# ===========================================================================
loo_frames, perm_rows = [], []
robust_candidates = hi_df[(hi_df["q値(BH-FDR)"] < 0.05) & (~hi_df["自己ペア"]) & (~hi_df["低分散注意"])]
for _, r in robust_candidates.iterrows():
    fam = r["検定族"]
    a_name = r["変数A"].split(":")[1].split("(")[0]
    b_name = r["変数B"].split(":")[1].split("(")[0]
    label = f"{r['変数A']} × {r['変数B']}"
    if fam.startswith("H-I-A"):
        x, y = delta[a_name], delta[b_name]
    else:
        x, y = baseline[a_name], delta[b_name]
    loo_frames.append(loo_spearman(x, y, label))
    perm_rows.append(permutation_spearman(x, y, r["rho"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/171_mmse_subitem_internal_pairs_loo.csv", index=False, encoding="utf-8-sig")
perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/172_mmse_subitem_internal_pairs_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/173_mmse_subitem_internal_pairs_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_tests": len(hi_df), "n_tested": int(valid.sum()), "fragile_threshold": FRAGILE_THRESHOLD,
        "n_perm": N_PERM, "n_loo_runs": len(loo_df), "n_perm_runs": len(perm_df),
        "background": "ALL_PAIRS_SCAN(693検定, MMSE/CDR/MoCA-J混合)では、MMSE下位項目同士の組み合わせで"
                       "FDR後有意なものは皆無だった(最も近いのはΔ場所見当識×Δ遅延再生でq=0.076)。"
                       "本解析はMMSE下位項目同士の組み合わせ176検定だけを独立ファミリーとして再補正。",
    }, f, ensure_ascii=False, indent=2)

if len(loo_df):
    print("\n=== Leave-one-out感度分析 ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後有意かつ自己ペアでない・低分散注意のない検定はなかったため、LOO・置換検定は実施対象なし ***")
