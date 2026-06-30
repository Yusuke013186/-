"""
ステップ2-F: 偏相関ネットワーク(Gaussian Graphical Model)

ALL_PAIRS_SCAN.mdの単純な2変数間Spearman相関は、AとBの関連が直接的なものか、
それとも第3の変数Cを介した間接的(媒介)な関連かを区別できない。たとえば
「CDR-SBの悪化」と「MMSE時間見当識の悪化」が相関するのは、両者が共通して
「全般的な重症度悪化」を反映しているだけかもしれない。

偏相関(他の全変数を統制した上での2変数間の相関)を使えば、こうした間接的な
関連を取り除いた「直接的なつながり」だけを可視化できる。対象はALL_PAIRS_SCAN.md
3節で頑健性が確認された9件のペアに登場するユニークな9変数のΔ(18か月-0か月)。
N(症例数)が変数数に対して小さいため(N≈25, P=9)、正則化(Graphical Lasso)を用いて
疎な(=本当に重要なつながりだけが残る)偏相関行列を推定する。

頑健性の検証として、ブートストラップ再標本化で各エッジが推定構造に
繰り返し現れる頻度(エッジ安定性, stability selectionの考え方)を計算し、
安定して現れたエッジのみを「候補」として報告する。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from sklearn.covariance import GraphicalLassoCV, GraphicalLasso
from sklearn.preprocessing import StandardScaler

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_BOOT = 500

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


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


def get_paired_delta(df, col):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    ids = sort_ids([
        sid for sid in STUDY_IDS
        if sid in d0.index and sid in d18.index and pd.notna(d0.loc[sid]) and pd.notna(d18.loc[sid])
    ])
    delta = pd.Series(d18.loc[ids].astype(float).values - d0.loc[ids].astype(float).values, index=ids)
    return delta


# ALL_PAIRS_SCAN.md 3節で頑健性が確認された9ペアに登場するユニーク9変数。
# 符号は「正=悪化方向」に統一する(MMSE/MoCA-Jはスコア低下が悪化のため反転)。
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


def fit_partial_corr_cv(X, alphas=20, cv=5):
    model = GraphicalLassoCV(alphas=alphas, cv=cv, max_iter=2000)
    model.fit(X)
    prec = model.precision_
    d = np.sqrt(np.diag(prec))
    pcorr = -prec / np.outer(d, d)
    np.fill_diagonal(pcorr, 1.0)
    return pcorr, model.alpha_


def fit_partial_corr_fixed(X, alpha):
    model = GraphicalLasso(alpha=alpha, max_iter=2000)
    model.fit(X)
    prec = model.precision_
    d = np.sqrt(np.diag(prec))
    pcorr = -prec / np.outer(d, d)
    np.fill_diagonal(pcorr, 1.0)
    return pcorr


pcorr_full, alpha_selected = fit_partial_corr_cv(X, cv=min(5, n))

pcorr_df = pd.DataFrame(pcorr_full, index=names, columns=names)
pcorr_df.to_csv(f"{OUT}/50_partial_correlation_matrix.csv", encoding="utf-8-sig")

edge_rows = []
for i in range(p):
    for j in range(i + 1, p):
        edge_rows.append({"変数A": names[i], "変数B": names[j], "偏相関係数": pcorr_full[i, j]})
edge_df = pd.DataFrame(edge_rows).sort_values("偏相関係数", key=lambda s: s.abs(), ascending=False)

# ===========================================================================
# 頑健性検証: ブートストラップによるエッジ安定性(stability selection)
# ===========================================================================
EDGE_THRESHOLD = 0.05  # この絶対値を超える偏相関を「エッジあり」とみなす
edge_presence = np.zeros((N_BOOT, p, p))
idx_all = np.arange(n)
n_failed = 0
for b in range(N_BOOT):
    boot_idx = RNG.choice(idx_all, size=n, replace=True)
    Xb = X[boot_idx]
    if np.any(Xb.std(axis=0) < 1e-8):
        n_failed += 1
        continue
    try:
        pcorr_b = fit_partial_corr_fixed(Xb, alpha=alpha_selected)
        edge_presence[b] = (np.abs(pcorr_b) > EDGE_THRESHOLD).astype(float)
    except Exception:
        n_failed += 1
        continue

stability = edge_presence.mean(axis=0)
edge_df["ブートストラップ安定性(エッジ出現率)"] = edge_df.apply(
    lambda r: stability[names.index(r["変数A"]), names.index(r["変数B"])], axis=1
)
edge_df.to_csv(f"{OUT}/51_partial_correlation_edges.csv", index=False, encoding="utf-8-sig")

STABLE_THRESHOLD = 0.7
stable_edges = edge_df[
    (edge_df["偏相関係数"].abs() > EDGE_THRESHOLD) & (edge_df["ブートストラップ安定性(エッジ出現率)"] >= STABLE_THRESHOLD)
]
stable_edges.to_csv(f"{OUT}/52_partial_correlation_stable_edges.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/53_partial_correlation_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_subjects": n, "n_variables": p,
        "alpha_selected_graphical_lasso": float(alpha_selected),
        "n_bootstrap": N_BOOT, "n_bootstrap_failed": n_failed,
        "edge_threshold": EDGE_THRESHOLD, "stable_threshold": STABLE_THRESHOLD,
        "variables": names,
        "sign_convention": "正の値=悪化方向(MMSE/MoCA-Jは符号反転済み)",
    }, f, ensure_ascii=False, indent=2)

print(f"=== 偏相関ネットワーク: N(共通症例)={n}, P(変数数)={p}, 選定された正則化強度alpha={alpha_selected:.4f} ===")
print(f"(ブートストラップ{N_BOOT}回中、分散ゼロ等で失敗={n_failed}回)\n")
print("=== 偏相関行列 ===")
print(pcorr_df.round(3).to_string())
print("\n=== 全エッジ(|偏相関|降順)とブートストラップ安定性 ===")
print(edge_df.to_string(index=False))
print(f"\n=== 安定エッジ(|偏相関|>{EDGE_THRESHOLD} かつ 安定性>={STABLE_THRESHOLD}) ===")
if len(stable_edges):
    print(stable_edges.to_string(index=False))
else:
    print("*** 安定エッジなし: 正則化推定値が小サンプルのため不安定で、頑健な直接的つながりは確認できなかった ***")
