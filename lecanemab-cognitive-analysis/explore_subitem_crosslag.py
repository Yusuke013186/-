"""
深掘りステップ4: 下位項目間の時間的先行関係(cross-lagged precedence)の検定

背景: `ALL_PAIRS_SCAN.md`の693検定による網羅的探索で頑健に残った9ペアのうち、
8件は「同じ重症度をMMSE/CDR/MoCA-Jという異なる物差しで測れば当然相関する」
(収束的妥当性)または概念的に近接した項目同士(見当識×見当識)であり、目新しさは
乏しいと結論づけた。唯一の例外が

  MMSE:場所見当識(Δ) × CDR:判断力・問題解決(Δ)  rho=-0.627, q=0.012 (ALL_PAIRS_SCAN)

であり、これは概念的に異なる認知ドメイン(空間見当識 vs 判断力・問題解決)間の
関連という点で構造的に自明ではない。さらに2-F(偏相関ネットワーク)・本セッションの
MB近傍選択でも、他の7変数の影響を統制した偏相関として独立に再現されている
(GLasso偏相関=0.394・ブートストラップ安定性0.956、MB近傍選択でも安定エッジ一致)。
3つの独立した手法すべてで頑健というのは、本プロジェクトを通じて他に例がない。

ただし、これまでの検定はすべて「同一時間窓(0→18か月)のΔ同士の相関」であり、
「どちらが先に悪化し、どちらが後から追随するか」という時間的先行関係
(temporal precedence)は未検定である。論文化を見据えるなら、単なる同時相関より
「Aの早期悪化がBの後期悪化を予測する」という時間的順序を示せる方が、
仮説（例: 空間見当識の低下が遂行機能低下の前兆である）として強い主張になる。

本解析は、この1ペアに限定したcross-lagged解析を事前に規定し検定する
(結果は有意・非有意を問わずすべて報告する)。

H-C(2検定、1ファミリーとしてBH-FDR補正):
  C1: 早期Δ(0→6か月)MMSE:場所見当識 は 後期Δ(6→18か月)CDR:判断力・問題解決 を予測するか
  C2: 早期Δ(0→6か月)CDR:判断力・問題解決 は 後期Δ(6→18か月)MMSE:場所見当識 を予測するか
  → C1の関連がC2より明確に強ければ「場所見当識の悪化が先行する」傍証、逆もまた然り。
  Spearman順位相関を用いる(H-A・ALL_PAIRS_SCANと同一手法、小サンプルでの外れ値に頑健なため)。

FDR補正はH-C単独の2検定ファミリーとして実施し、他のどの解析ファミリーともプールしない
(本プロジェクト一貫の方針)。FDR補正後に有意だった検定について、H-Aと同じ枠組みで
leave-one-out感度分析と置換検定(後期Δのシャッフル)を実施する。
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

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")

STUDY_IDS = sorted(mmse["研究番号"].dropna().unique(), key=lambda x: int(x[1:]))


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


def get_value(df, col, time_label):
    s = df[df["時点"] == time_label].set_index("研究番号")[col]
    return pd.to_numeric(s, errors="coerce").reindex(STUDY_IDS)


loc0 = get_value(mmse, "場所見当識", "0か月")
loc6 = get_value(mmse, "場所見当識", "6か月")
loc18 = get_value(mmse, "場所見当識", "18か月")
jud0 = get_value(cdr, "判断力・問題解決", "0か月")
jud6 = get_value(cdr, "判断力・問題解決", "6か月")
jud18 = get_value(cdr, "判断力・問題解決", "18か月")

delta_loc_early = loc6 - loc0
delta_loc_late = loc18 - loc6
delta_jud_early = jud6 - jud0
delta_jud_late = jud18 - jud6

# ===========================================================================
# H-C: cross-lagged Spearman相関(2検定)
# ===========================================================================
hc_data = {}
rows_hc = []

valid_c1 = delta_loc_early.notna() & delta_jud_late.notna()
de_c1 = delta_loc_early[valid_c1]
dl_c1 = delta_jud_late[valid_c1]
hc_data["C1"] = (de_c1, dl_c1)
if len(de_c1) >= 3:
    rho_c1, p_c1 = stats.spearmanr(de_c1, dl_c1)
else:
    rho_c1, p_c1 = np.nan, np.nan
rows_hc.append({
    "検定": "C1: 早期Δ場所見当識(0→6mo) → 後期Δ判断力問題解決(6→18mo)",
    "N(症例数)": len(de_c1),
    "早期Δ中央値(場所見当識)": de_c1.median() if len(de_c1) else np.nan,
    "後期Δ中央値(判断力問題解決)": dl_c1.median() if len(dl_c1) else np.nan,
    "Spearman順位相関係数": rho_c1, "p値": p_c1,
})

valid_c2 = delta_jud_early.notna() & delta_loc_late.notna()
de_c2 = delta_jud_early[valid_c2]
dl_c2 = delta_loc_late[valid_c2]
hc_data["C2"] = (de_c2, dl_c2)
if len(de_c2) >= 3:
    rho_c2, p_c2 = stats.spearmanr(de_c2, dl_c2)
else:
    rho_c2, p_c2 = np.nan, np.nan
rows_hc.append({
    "検定": "C2: 早期Δ判断力問題解決(0→6mo) → 後期Δ場所見当識(6→18mo)",
    "N(症例数)": len(de_c2),
    "早期Δ中央値(判断力問題解決)": de_c2.median() if len(de_c2) else np.nan,
    "後期Δ中央値(場所見当識)": dl_c2.median() if len(dl_c2) else np.nan,
    "Spearman順位相関係数": rho_c2, "p値": p_c2,
})

hc_df = pd.DataFrame(rows_hc)
valid_hc = hc_df["p値"].notna()
q_hc = pd.Series(np.nan, index=hc_df.index)
if valid_hc.sum() > 0:
    _, qvals, _, _ = multipletests(hc_df.loc[valid_hc, "p値"], method="fdr_bh")
    q_hc.loc[valid_hc] = qvals
hc_df["q値(BH-FDR)"] = q_hc
hc_df.to_csv(f"{OUT}/110_subitem_crosslag_correlation.csv", index=False, encoding="utf-8-sig")


# ===========================================================================
# 頑健性検証: FDR補正後に有意だった検定についてLOO・置換検定を実施
# ===========================================================================
def loo_spearman(de, dl, label):
    rows = []
    ids = sort_ids(de.index)
    for sid in ids:
        de_sub = de.drop(sid)
        dl_sub = dl.drop(sid)
        if len(de_sub) >= 3:
            rho, p = stats.spearmanr(de_sub, dl_sub)
        else:
            rho, p = np.nan, np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後rho": rho, "除外後p値": p})
    return pd.DataFrame(rows)


def perm_spearman(de, dl, observed_rho, label, n_perm=N_PERM):
    dl_vals = dl.values.copy()
    perm_rhos = []
    for _ in range(n_perm):
        shuffled = RNG.permutation(dl_vals)
        rho, _ = stats.spearmanr(de.values, shuffled)
        perm_rhos.append(rho)
    perm_rhos = np.array(perm_rhos)
    p_perm = float(np.mean(np.abs(perm_rhos) >= np.abs(observed_rho)))
    return {"検定": label, "観測rho": observed_rho, "置換検定p値": p_perm, "n_perm": n_perm}


label_map = {
    "C1": "C1: 早期Δ場所見当識→後期Δ判断力問題解決",
    "C2": "C2: 早期Δ判断力問題解決→後期Δ場所見当識",
}

loo_frames = []
perm_rows = []
sig_hc = hc_df[hc_df["q値(BH-FDR)"] < 0.05]
for idx, r in sig_hc.iterrows():
    key = "C1" if idx == 0 else "C2"
    de, dl = hc_data[key]
    label = label_map[key]
    loo_frames.append(loo_spearman(de, dl, label))
    perm_rows.append(perm_spearman(de, dl, r["Spearman順位相関係数"], label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/111_subitem_crosslag_loo.csv", index=False, encoding="utf-8-sig")

perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/112_subitem_crosslag_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/113_subitem_crosslag_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "hc_n_tests": len(hc_df), "hc_n_tested": int(valid_hc.sum()),
        "n_loo_runs": len(loo_df), "n_perm": N_PERM, "n_perm_runs": len(perm_df),
        "background_finding": "MMSE:場所見当識(Δ) x CDR:判断力・問題解決(Δ), ALL_PAIRS_SCAN rho=-0.627 q=0.012; "
                               "GLasso偏相関=0.394 stability=0.956; MB近傍選択でも安定エッジ一致",
    }, f, ensure_ascii=False, indent=2)

print("=== H-C: 場所見当識 と 判断力・問題解決 のcross-lagged Spearman順位相関 ===")
print(hc_df.to_string(index=False))

if len(loo_df):
    print("\n=== Leave-one-out感度分析(FDR補正後有意だった検定について) ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後に有意な検定はなかったため、LOO・置換検定は実施対象なし ***")
