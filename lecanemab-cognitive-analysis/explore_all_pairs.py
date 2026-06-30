"""
全変数の総当たり(A×B)探索的関連性スキャン

ユーザー依頼: 「全てA×Bという形の関連性で有意差がないか調べてみて」
時間をかけてでも網羅的に調べることが優先のため、以下の4フェーズで
考えうる組み合わせをすべて機械的に検定する。

変数セット(21個): 主要4項目(MMSE合計・CDR-SB・Global CDR・MoCA-J合計)
                  + MMSE下位項目11個 + CDR下位領域6個
各変数について「0か月値(ベースライン)」と「Δ(18か月-0か月)」を用いる。

Phase A: Δ × Δ （21変数 → 210ペア）       「Aが落ちる人はBも落ちるか」
Phase B: ベースライン(A) × Δ(B) （21×21=441通り、A=Bの対角21含む）
                                          「Aの初期値がBの変化を予測するか」
Phase C: 精神症状の有無 × Δ（21変数）      「精神症状の併存とBの変化」
Phase D: 精神症状の有無 × ベースライン（21変数）「精神症状の併存とBの初期値」

合計 210+441+21+21 = 693 検定。すべてを1つの検定ファミリーとして
Benjamini-Hochberg法でFDR補正したq値を算出する。

**重要**: これは事前に仮説を定めない総当たり探索（data dredging）である。
693検定では、真に関連が存在しなくても期待値として約35件が
未補正p<0.05になる（693×0.05≈35）。個々の未補正p値だけで「関連あり」と
判断してはならず、FDR補正後のq値を基準に解釈し、結果は厳密な意味で
仮説生成的なものに留める。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats
from statsmodels.stats.multitest import multipletests

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
moca = sheet_to_df("MoCA-J")
psych = sheet_to_df("精神症状")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


# ---------------------------------------------------------------------------
# 21変数の定義
# ---------------------------------------------------------------------------
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

assert len(VAR_DEFS) == 21


def get_series(df, col, timepoint):
    d = df[df["時点"] == timepoint].set_index("研究番号")[col]
    d = d.dropna().astype(float)
    return d[d.index.isin(STUDY_IDS)]


baseline = {}
delta = {}
parent_group = {}
for name, df, col, grp in VAR_DEFS:
    s0 = get_series(df, col, "0か月")
    s18 = get_series(df, col, "18か月")
    common = sort_ids(set(s0.index) & set(s18.index))
    baseline[name] = s0
    delta[name] = (s18.loc[common] - s0.loc[common]).reindex(common)
    parent_group[name] = grp

names = [v[0] for v in VAR_DEFS]


def n_nonmodal(s):
    """値の大半が単一の値に集中している変数を検出するための指標。
    N - (最頻値の個数)。小さいほど『ほぼ定数』に近く、見かけ上の強い相関が
    1〜数例の偶然の一致で生じやすい（疑似相関のリスクが高い）。"""
    if len(s) == 0:
        return 0
    return int(len(s) - s.value_counts().iloc[0])


baseline_nonmodal = {a: n_nonmodal(baseline[a]) for a in names}
delta_nonmodal = {a: n_nonmodal(delta[a]) for a in names}
FRAGILE_THRESHOLD = 5  # これ未満なら「ほぼ定数」とみなし注意フラグを付与


def fragile_flag_AB(a_nonmodal, b_nonmodal):
    flags = []
    if a_nonmodal < FRAGILE_THRESHOLD:
        flags.append(f"A非モーダル数={a_nonmodal}")
    if b_nonmodal < FRAGILE_THRESHOLD:
        flags.append(f"B非モーダル数={b_nonmodal}")
    return "低分散注意: " + ", ".join(flags) if flags else ""


def fragile_flag_single(nonmodal):
    if nonmodal < FRAGILE_THRESHOLD:
        return f"低分散注意: 非モーダル数={nonmodal}"
    return ""


def is_part_whole(a, b):
    """主要項目とその構成下位項目の組（構造的に相関するのが自明なペア）かを判定"""
    pairs = {
        frozenset({"MMSE合計", x}) for x in names if x.startswith("MMSE:")
    } | {
        frozenset({"CDR-SB", x}) for x in names if x.startswith("CDR:")
    } | {
        frozenset({"Global CDR", x}) for x in names if x.startswith("CDR:")
    }
    return frozenset({a, b}) in pairs


def spearman_safe(x, y):
    common = sort_ids(set(x.index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan
    xv = x.loc[common].values
    yv = y.loc[common].values
    if np.unique(xv).size == 1 or np.unique(yv).size == 1:
        return n, np.nan, np.nan
    rho, p = stats.spearmanr(xv, yv)
    return n, rho, p


def mannwhitney_safe(group_labels, y):
    common = sort_ids(set(group_labels.index) & set(y.index))
    n = len(common)
    if n < 5:
        return n, np.nan, np.nan, np.nan, np.nan
    g = group_labels.loc[common]
    yv = y.loc[common]
    cats = g.unique()
    if len(cats) != 2:
        return n, np.nan, np.nan, np.nan, np.nan
    g1 = yv[g == cats[0]]
    g2 = yv[g == cats[1]]
    if len(g1) < 2 or len(g2) < 2:
        return n, np.nan, np.nan, np.nan, np.nan
    if np.unique(yv.values).size == 1:
        return n, np.nan, np.nan, np.nan, np.nan
    u, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
    r = 1 - (2 * u) / (len(g1) * len(g2))
    return n, u, p, r, f"{cats[0]}(N={len(g1)}) vs {cats[1]}(N={len(g2)})"


# ---------------------------------------------------------------------------
# 精神症状グループ（あり/なし）
# ---------------------------------------------------------------------------
psych_df = psych.set_index("研究番号")
psych_group = psych_df.apply(
    lambda r: "あり" if r["両方なし"] == 0 else "なし", axis=1
)
psych_group = psych_group[psych_group.index.isin(STUDY_IDS)]

# ---------------------------------------------------------------------------
# Phase A: Δ × Δ （210ペア）
# ---------------------------------------------------------------------------
rows = []
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = names[i], names[j]
        n, rho, p = spearman_safe(delta[a], delta[b])
        rows.append({
            "Phase": "A: Δ×Δ", "変数A": a, "変数B": b,
            "関係性": "構造的(部分-全体)" if is_part_whole(a, b) else "独立した組み合わせ",
            "N": n, "統計量": rho, "p値": p, "検定": "Spearman相関",
            "低分散注意": fragile_flag_AB(delta_nonmodal[a], delta_nonmodal[b]),
        })
phaseA_df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Phase B: ベースライン(A) × Δ(B) （A=B含む 441通り）
# ---------------------------------------------------------------------------
rows = []
for a in names:
    for b in names:
        n, rho, p = spearman_safe(baseline[a], delta[b])
        rows.append({
            "Phase": "B: ベースライン→Δ", "変数A(ベースライン)": a, "変数B(Δ)": b,
            "関係性": "自己(回帰効果に注意)" if a == b else ("構造的(部分-全体)" if is_part_whole(a, b) else "独立した組み合わせ"),
            "N": n, "統計量": rho, "p値": p, "検定": "Spearman相関",
            "低分散注意": fragile_flag_AB(baseline_nonmodal[a], delta_nonmodal[b]),
        })
phaseB_df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Phase C: 精神症状 × Δ （21）
# ---------------------------------------------------------------------------
rows = []
for a in names:
    n, u, p, r, glabel = mannwhitney_safe(psych_group, delta[a])
    rows.append({
        "Phase": "C: 精神症状×Δ", "変数B(Δ)": a, "群構成": glabel,
        "N": n, "統計量(U)": u, "効果量r": r, "p値": p, "検定": "Mann-Whitney U",
        "低分散注意": fragile_flag_single(delta_nonmodal[a]),
    })
phaseC_df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Phase D: 精神症状 × ベースライン （21）
# ---------------------------------------------------------------------------
rows = []
for a in names:
    n, u, p, r, glabel = mannwhitney_safe(psych_group, baseline[a])
    rows.append({
        "Phase": "D: 精神症状×ベースライン", "変数B(ベースライン)": a, "群構成": glabel,
        "N": n, "統計量(U)": u, "効果量r": r, "p値": p, "検定": "Mann-Whitney U",
        "低分散注意": fragile_flag_single(baseline_nonmodal[a]),
    })
phaseD_df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# 全693検定をまとめてBH-FDR補正
# ---------------------------------------------------------------------------
all_p = pd.concat([
    phaseA_df[["Phase", "p値"]].assign(label=phaseA_df["変数A"] + " × " + phaseA_df["変数B"]),
    phaseB_df[["Phase", "p値"]].assign(label=phaseB_df["変数A(ベースライン)"] + "(baseline) → " + phaseB_df["変数B(Δ)"] + "(Δ)"),
    phaseC_df[["Phase", "p値"]].assign(label="精神症状 × " + phaseC_df["変数B(Δ)"] + "(Δ)"),
    phaseD_df[["Phase", "p値"]].assign(label="精神症状 × " + phaseD_df["変数B(ベースライン)"] + "(baseline)"),
], ignore_index=True)

n_total_tests = len(all_p)
n_tested = all_p["p値"].notna().sum()

valid_mask = all_p["p値"].notna()
q_full = pd.Series(np.nan, index=all_p.index)
if valid_mask.sum() > 0:
    _, q_valid, _, _ = multipletests(all_p.loc[valid_mask, "p値"], method="fdr_bh", alpha=0.05)
    q_full.loc[valid_mask] = q_valid
all_p["q値(BH-FDR)"] = q_full

# 各Phase DataFrameにq値をマージし直す
phaseA_df["q値(BH-FDR)"] = q_full.iloc[: len(phaseA_df)].values
offset = len(phaseA_df)
phaseB_df["q値(BH-FDR)"] = q_full.iloc[offset: offset + len(phaseB_df)].values
offset += len(phaseB_df)
phaseC_df["q値(BH-FDR)"] = q_full.iloc[offset: offset + len(phaseC_df)].values
offset += len(phaseC_df)
phaseD_df["q値(BH-FDR)"] = q_full.iloc[offset: offset + len(phaseD_df)].values

import os
os.makedirs(OUT, exist_ok=True)
phaseA_df.to_csv(f"{OUT}/10_phaseA_delta_vs_delta.csv", index=False, encoding="utf-8-sig")
phaseB_df.to_csv(f"{OUT}/11_phaseB_baseline_vs_delta.csv", index=False, encoding="utf-8-sig")
phaseC_df.to_csv(f"{OUT}/12_phaseC_psych_vs_delta.csv", index=False, encoding="utf-8-sig")
phaseD_df.to_csv(f"{OUT}/13_phaseD_psych_vs_baseline.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/14_scan_meta.json", "w", encoding="utf-8") as f:
    json.dump({"n_total_tests": int(n_total_tests), "n_tested": int(n_tested),
               "n_variables": len(names), "variables": names}, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# サマリー: 未補正 p<0.05 のものを全Phase横断で抽出
# ---------------------------------------------------------------------------
summary_rows = []
for _, r in phaseA_df.iterrows():
    if pd.notna(r["p値"]) and r["p値"] < 0.05:
        summary_rows.append({
            "Phase": r["Phase"], "組み合わせ": f"{r['変数A']}(Δ) × {r['変数B']}(Δ)",
            "関係性": r["関係性"], "N": r["N"], "検定": r["検定"],
            "統計量": r["統計量"], "p値(未補正)": r["p値"], "q値(BH-FDR)": r["q値(BH-FDR)"],
            "低分散注意": r["低分散注意"],
        })
for _, r in phaseB_df.iterrows():
    if pd.notna(r["p値"]) and r["p値"] < 0.05:
        summary_rows.append({
            "Phase": r["Phase"], "組み合わせ": f"{r['変数A(ベースライン)']}(baseline) → {r['変数B(Δ)']}(Δ)",
            "関係性": r["関係性"], "N": r["N"], "検定": r["検定"],
            "統計量": r["統計量"], "p値(未補正)": r["p値"], "q値(BH-FDR)": r["q値(BH-FDR)"],
            "低分散注意": r["低分散注意"],
        })
for _, r in phaseC_df.iterrows():
    if pd.notna(r["p値"]) and r["p値"] < 0.05:
        summary_rows.append({
            "Phase": r["Phase"], "組み合わせ": f"精神症状({r['群構成']}) × {r['変数B(Δ)']}(Δ)",
            "関係性": "-", "N": r["N"], "検定": r["検定"],
            "統計量": r["統計量(U)"], "p値(未補正)": r["p値"], "q値(BH-FDR)": r["q値(BH-FDR)"],
            "低分散注意": r["低分散注意"],
        })
for _, r in phaseD_df.iterrows():
    if pd.notna(r["p値"]) and r["p値"] < 0.05:
        summary_rows.append({
            "Phase": r["Phase"], "組み合わせ": f"精神症状({r['群構成']}) × {r['変数B(ベースライン)']}(baseline)",
            "関係性": "-", "N": r["N"], "検定": r["検定"],
            "統計量": r["統計量(U)"], "p値(未補正)": r["p値"], "q値(BH-FDR)": r["q値(BH-FDR)"],
            "低分散注意": r["低分散注意"],
        })

summary_df = pd.DataFrame(summary_rows).sort_values("p値(未補正)").reset_index(drop=True)
summary_df.to_csv(f"{OUT}/15_summary_raw_p_under_0.05.csv", index=False, encoding="utf-8-sig")

print(f"総検定数: {n_total_tests} (実施可能: {n_tested})")
print(f"未補正 p<0.05 の組み合わせ数: {len(summary_df)} （期待値[完全に無関連の場合]: 約{n_tested*0.05:.0f}件）")
print(f"BH-FDR補正後 q<0.05 の組み合わせ数: {(all_p['q値(BH-FDR)']<0.05).sum()}")
print(f"BH-FDR補正後 q<0.10 の組み合わせ数: {(all_p['q値(BH-FDR)']<0.10).sum()}")
print(f"BH-FDR補正後 q<0.20 の組み合わせ数: {(all_p['q値(BH-FDR)']<0.20).sum()}")
print()
print(summary_df.to_string(index=False))
