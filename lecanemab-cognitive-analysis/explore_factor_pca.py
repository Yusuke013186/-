"""
ステップ2-E: 因子分析/PCAによる下位項目の潜在構造探索

MMSE 11下位項目・CDR 6下位領域は、これまですべて個別の変数として扱われてきた。
しかし臨床的には「記憶」「見当識」「実行機能」のような少数の潜在因子に
集約できる可能性があり、それが本当に存在するかを主成分分析(PCA)で探る。

N=33という小規模サンプルでの因子分析・PCAは本質的に不安定であり
(一般的な目安はサンプルサイズが変数の5〜10倍以上)、観測された主成分が
真の潜在構造かそれとも単なるサンプリングノイズかを区別する必要がある。
このため、Horn(1965)のparallel analysis(ランダムデータで生成した
固有値の95パーセンタイルを基準とする)を頑健性検証として用い、
基準を超えた主成分のみを「採用」とする。

対象は4セット: MMSE下位項目(ベースライン値/Δ) × CDR下位領域(ベースライン値/Δ)。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from sklearn.decomposition import PCA

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG = np.random.default_rng(20260630)
N_PERM = 2000

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))

MMSE_ITEMS = ["時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
              "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写"]
CDR_ITEMS = ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]


def get_baseline_matrix(df, items):
    sub = df[df["時点"] == "0か月"].set_index("研究番号")
    sub = sub[sub.index.isin(STUDY_IDS)]
    mat = sub[items].apply(pd.to_numeric, errors="coerce")
    return mat.dropna()


def get_delta_matrix(df, items):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")
    common = sorted(set(d0.index) & set(d18.index) & set(STUDY_IDS), key=lambda x: int(x[1:]))
    d0 = d0.loc[common, items].apply(pd.to_numeric, errors="coerce")
    d18 = d18.loc[common, items].apply(pd.to_numeric, errors="coerce")
    delta = (d18 - d0).dropna()
    return delta


def parallel_analysis_threshold(n, p, n_perm=N_PERM, percentile=95):
    """N x P の標準正規乱数でPCAを繰り返し、各成分順位の固有値分布の
    パーセンタイルを基準値として返す(Horn 1965のparallel analysis)。"""
    eig_mat = np.zeros((n_perm, min(n, p)))
    for i in range(n_perm):
        X = RNG.standard_normal((n, p))
        Xc = (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)
        pca = PCA(n_components=min(n, p))
        pca.fit(Xc)
        eig_mat[i] = pca.explained_variance_
    return np.percentile(eig_mat, percentile, axis=0)


def run_pca_with_parallel_analysis(mat, label):
    n, p = mat.shape
    Xz = (mat.values - mat.values.mean(axis=0)) / mat.values.std(axis=0, ddof=1)
    pca = PCA(n_components=min(n, p))
    pca.fit(Xz)
    eigvals = pca.explained_variance_
    explained_ratio = pca.explained_variance_ratio_
    pa_threshold = parallel_analysis_threshold(n, p)
    n_retained = int(np.sum(eigvals > pa_threshold))

    comp_rows = []
    for k in range(len(eigvals)):
        comp_rows.append({
            "セット": label, "成分": f"PC{k + 1}",
            "固有値": eigvals[k], "寄与率": explained_ratio[k],
            "累積寄与率": float(np.sum(explained_ratio[:k + 1])),
            "parallel_analysis基準値(乱数95%点)": pa_threshold[k],
            "採用(固有値>基準値)": bool(eigvals[k] > pa_threshold[k]),
        })
    comp_df = pd.DataFrame(comp_rows)

    loading_rows = []
    if n_retained > 0:
        loadings = pca.components_[:n_retained].T * np.sqrt(eigvals[:n_retained])
        for j, item in enumerate(mat.columns):
            row = {"セット": label, "項目": item}
            for k in range(n_retained):
                row[f"PC{k + 1}負荷量"] = loadings[j, k]
            loading_rows.append(row)
    loading_df = pd.DataFrame(loading_rows)

    return n, p, n_retained, comp_df, loading_df


datasets = [
    ("MMSE下位項目(ベースライン)", get_baseline_matrix(mmse, MMSE_ITEMS)),
    ("MMSE下位項目(Δ=18-0ヶ月)", get_delta_matrix(mmse, MMSE_ITEMS)),
    ("CDR下位領域(ベースライン)", get_baseline_matrix(cdr, CDR_ITEMS)),
    ("CDR下位領域(Δ=18-0ヶ月)", get_delta_matrix(cdr, CDR_ITEMS)),
]

all_comp = []
all_loadings = []
summary_rows = []
for label, mat in datasets:
    # 分散ゼロの項目(全員同じ値)はPCAに投入できないため除外
    nonzero_var = mat.columns[mat.std(axis=0, ddof=1) > 0]
    dropped = sorted(set(mat.columns) - set(nonzero_var))
    mat_use = mat[nonzero_var]
    n, p, n_retained, comp_df, loading_df = run_pca_with_parallel_analysis(mat_use, label)
    all_comp.append(comp_df)
    all_loadings.append(loading_df)
    summary_rows.append({
        "セット": label, "N(症例)": n, "P(項目数)": p,
        "除外項目(分散ゼロ)": ", ".join(dropped) if dropped else "なし",
        "parallel_analysisで採用された成分数": n_retained,
    })

comp_all_df = pd.concat(all_comp, ignore_index=True)
loading_all_df = pd.concat(all_loadings, ignore_index=True) if any(len(d) for d in all_loadings) else pd.DataFrame()
summary_df = pd.DataFrame(summary_rows)

comp_all_df.to_csv(f"{OUT}/40_pca_components.csv", index=False, encoding="utf-8-sig")
loading_all_df.to_csv(f"{OUT}/41_pca_loadings_retained_only.csv", index=False, encoding="utf-8-sig")
summary_df.to_csv(f"{OUT}/42_pca_summary.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/43_pca_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "n_perm_parallel_analysis": N_PERM,
        "datasets": summary_rows,
    }, f, ensure_ascii=False, indent=2)

print("=== PCA + Parallel Analysisによる成分採否の要約 ===")
print(summary_df.to_string(index=False))
print("\n=== 全成分の固有値・寄与率・parallel analysis基準 ===")
print(comp_all_df.to_string(index=False))
if len(loading_all_df):
    print("\n=== 採用された成分の負荷量(parallel analysis基準を超えた成分のみ) ===")
    print(loading_all_df.to_string(index=False))
else:
    print("\n*** いずれのデータセットでもparallel analysis基準を超える成分はなかった ***")
    print("*** (N=33という小規模サンプルでは、ランダムノイズと区別できる潜在構造を検出できなかった) ***")
