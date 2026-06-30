"""
深掘りステップ3-A: 新規の事前規定仮説(臨床的に意味のある未検証の問い)

これまでの解析は、「悪化のペースは集団全体でおおむね一定」という前提のもとでの
平均的傾向(REPORT.md〜)や、症例の特性による傾き自体の違い(2-B)、9つの既知ペアの
非線形性(2-C)、軌跡の異質なサブグループ(2-D)などを検定してきたが、いずれも
「時間軸上での変化パターンの一貫性」や「CDR内部のサブドメイン構造」そのものは
検定していない。本解析では、事前に2つの仮説を規定し検定する(結果は有意・非有意を
問わずすべて報告する)。

H-A(家族1, 3検定): 早期Δ(0→6か月)は後期Δ(6→18か月)を予測するか
  「最初の6か月でよく悪化した症例は、その後も悪化が速いか」という、軌跡の
  一貫性(track-record consistency)に関する仮説。対象はMMSE合計・CDR-SB・
  Global CDRの主要3項目。Spearman順位相関を用いる(小サンプルでの外れ値に
  頑健なため)。

H-B(家族2, 1検定): CDR内の「認知系」サブドメインΔと「機能系」サブドメインΔは
  異なる速度で悪化するか
  CDR-SBは6領域(記憶・見当識・判断力問題解決・地域社会の活動・家庭趣味・
  身の回りの世話)の合計である。前者3領域(記憶・見当識・判断力問題解決)を
  「認知系」、後者3領域(地域社会の活動・家庭趣味・身の回りの世話)を「機能系」
  サブドメイン複合スコアとして、0→18か月のΔを対応のあるWilcoxon符号順位検定で
  比較する。これは2-Eで因子分析が「明確な潜在構造なし」という非有意な結果に
  終わったCDR内部構造を、データ駆動ではなく臨床的に事前規定した形で再検証する
  確証的(confirmatory)な代替アプローチでもある。

FDR補正はH-A(3検定)とH-B(1検定)をそれぞれ独立したファミリーとして実施する
(他のどの解析ファミリーともプールしない、本プロジェクト一貫の方針)。
FDR補正後に有意だった検定について、leave-one-out感度分析と置換検定
(H-Aは後期Δのシャッフル、H-Bは症例ごとの符号反転permutation)で頑健性を検証する。
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


OUTCOME_VARS = [
    ("MMSE合計", mmse, "下位項目合計_自動計算"),
    ("CDR-SB", cdr, "CDR-SB_自動計算"),
    ("Global CDR", cdr, "Global CDR_原資料記載値"),
]

# ===========================================================================
# H-A: 早期Δ(0→6か月) は 後期Δ(6→18か月) を予測するか(Spearman順位相関)
# ===========================================================================
ha_data = {}
rows_ha = []
for name, df, col in OUTCOME_VARS:
    v0 = get_value(df, col, "0か月")
    v6 = get_value(df, col, "6か月")
    v18 = get_value(df, col, "18か月")
    delta_early = v6 - v0
    delta_late = v18 - v6
    valid = delta_early.notna() & delta_late.notna()
    de = delta_early[valid]
    dl = delta_late[valid]
    ha_data[name] = (de, dl)
    if len(de) >= 3:
        rho, p = stats.spearmanr(de, dl)
    else:
        rho, p = np.nan, np.nan
    rows_ha.append({
        "結果変数": name, "N(症例数)": len(de),
        "早期Δ中央値(0→6mo)": de.median() if len(de) else np.nan,
        "後期Δ中央値(6→18mo)": dl.median() if len(dl) else np.nan,
        "Spearman順位相関係数": rho, "p値": p,
    })
ha_df = pd.DataFrame(rows_ha)
valid_ha = ha_df["p値"].notna()
q_ha = pd.Series(np.nan, index=ha_df.index)
if valid_ha.sum() > 0:
    _, qvals, _, _ = multipletests(ha_df.loc[valid_ha, "p値"], method="fdr_bh")
    q_ha.loc[valid_ha] = qvals
ha_df["q値(BH-FDR)"] = q_ha
ha_df.to_csv(f"{OUT}/80_early_late_delta_correlation.csv", index=False, encoding="utf-8-sig")

# ===========================================================================
# H-B: CDR「認知系」サブドメインΔ vs「機能系」サブドメインΔ(対応ありWilcoxon)
# ===========================================================================
COGNITIVE_DOMAINS = ["記憶", "見当識", "判断力・問題解決"]
FUNCTIONAL_DOMAINS = ["地域社会の活動", "家庭・趣味", "身の回りの世話"]


def composite(df, domains, time_label):
    vals = pd.DataFrame({d: get_value(df, d, time_label) for d in domains})
    return vals.sum(axis=1, min_count=len(domains))


cog0 = composite(cdr, COGNITIVE_DOMAINS, "0か月")
cog18 = composite(cdr, COGNITIVE_DOMAINS, "18か月")
func0 = composite(cdr, FUNCTIONAL_DOMAINS, "0か月")
func18 = composite(cdr, FUNCTIONAL_DOMAINS, "18か月")

delta_cog = (cog18 - cog0)
delta_func = (func18 - func0)
valid_hb = delta_cog.notna() & delta_func.notna()
dcog = delta_cog[valid_hb]
dfunc = delta_func[valid_hb]
diff_hb = (dcog - dfunc)

if len(dcog) >= 3 and not np.allclose(diff_hb.values, 0):
    w_stat, p_hb = stats.wilcoxon(dcog, dfunc)
else:
    w_stat, p_hb = np.nan, np.nan

hb_df = pd.DataFrame([{
    "比較": "CDR認知系サブドメインΔ vs 機能系サブドメインΔ(0→18か月)",
    "N(症例数)": len(dcog),
    "認知系Δ中央値(記憶+見当識+判断力問題解決)": dcog.median() if len(dcog) else np.nan,
    "機能系Δ中央値(地域社会活動+家庭趣味+身の回りの世話)": dfunc.median() if len(dfunc) else np.nan,
    "Wilcoxon統計量": w_stat, "p値": p_hb,
    "q値(BH-FDR)": p_hb,  # 単独検定のためq=p
}])
hb_df.to_csv(f"{OUT}/81_cdr_subdomain_composite_paired_test.csv", index=False, encoding="utf-8-sig")


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


def loo_wilcoxon(dcog, dfunc, label):
    rows = []
    ids = sort_ids(dcog.index)
    for sid in ids:
        c_sub = dcog.drop(sid)
        f_sub = dfunc.drop(sid)
        diff_sub = c_sub - f_sub
        if len(c_sub) >= 3 and not np.allclose(diff_sub.values, 0):
            w, p = stats.wilcoxon(c_sub, f_sub)
        else:
            w, p = np.nan, np.nan
        rows.append({"検定": label, "除外症例": sid, "除外後W統計量": w, "除外後p値": p})
    return pd.DataFrame(rows)


def perm_sign_flip_wilcoxon(diff, observed_w, label, n_perm=N_PERM):
    """対応のある差(diff)の符号をランダムに反転するpermutation(対応ありデータの標準的な置換検定)"""
    vals = diff.values
    n = len(vals)
    perm_ws = []
    for _ in range(n_perm):
        signs = RNG.choice([-1.0, 1.0], size=n)
        flipped = vals * signs
        try:
            w, _ = stats.wilcoxon(flipped)
        except ValueError:
            continue
        perm_ws.append(w)
    perm_ws = np.array(perm_ws)
    # Wilcoxon Wは小さいほど偏りが強いので、観測値以下になる割合を片側、両側はabs(diffからの統計)で評価
    # ここでは観測|差の和|に相当する指標として「中央値からの乖離」を使う代わりに、
    # 標準のW統計量の両側p値相当として観測W以下の割合を採用する
    p_perm = float(np.mean(perm_ws <= observed_w)) if len(perm_ws) > 0 else np.nan
    return {"検定": label, "観測W統計量": observed_w, "置換検定p値(符号反転)": p_perm, "n_perm": len(perm_ws)}


loo_frames = []
perm_rows = []

sig_ha = ha_df[ha_df["q値(BH-FDR)"] < 0.05]
for _, r in sig_ha.iterrows():
    name = r["結果変数"]
    de, dl = ha_data[name]
    label = f"{name}: 早期Δ→後期Δ"
    loo_frames.append(loo_spearman(de, dl, label))
    perm_rows.append(perm_spearman(de, dl, r["Spearman順位相関係数"], label))

if pd.notna(p_hb) and p_hb < 0.05:
    label = "CDR認知系Δ vs 機能系Δ"
    loo_frames.append(loo_wilcoxon(dcog, dfunc, label))
    perm_rows.append(perm_sign_flip_wilcoxon(diff_hb, w_stat, label))

loo_df = pd.concat(loo_frames, ignore_index=True) if loo_frames else pd.DataFrame()
if len(loo_df):
    loo_df.to_csv(f"{OUT}/82_new_hypotheses_loo.csv", index=False, encoding="utf-8-sig")

perm_df = pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame()
if len(perm_df):
    perm_df.to_csv(f"{OUT}/83_new_hypotheses_permutation.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/84_new_hypotheses_meta.json", "w", encoding="utf-8") as f:
    json.dump({
        "ha_n_tests": len(ha_df), "ha_n_tested": int(valid_ha.sum()),
        "hb_n_tests": 1,
        "n_loo_runs": len(loo_df), "n_perm": N_PERM, "n_perm_runs": len(perm_df),
        "cognitive_domains": COGNITIVE_DOMAINS, "functional_domains": FUNCTIONAL_DOMAINS,
    }, f, ensure_ascii=False, indent=2)

print("=== H-A: 早期Δ(0→6mo) と 後期Δ(6→18mo) のSpearman順位相関 ===")
print(ha_df.to_string(index=False))

print("\n=== H-B: CDR認知系サブドメインΔ vs 機能系サブドメインΔ(対応ありWilcoxon) ===")
print(hb_df.to_string(index=False))

if len(loo_df):
    print("\n=== Leave-one-out感度分析(FDR補正後有意だった検定について) ===")
    print(loo_df.to_string(index=False))
if len(perm_df):
    print("\n=== 置換検定 ===")
    print(perm_df.to_string(index=False))
if not len(loo_df) and not len(perm_df):
    print("\n*** FDR補正後に有意な検定はなかったため、LOO・置換検定は実施対象なし ***")
