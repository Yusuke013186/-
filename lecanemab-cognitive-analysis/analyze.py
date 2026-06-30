"""
レカネマブ研究 L1-33: MMSE / CDR / MoCA-J / 精神症状 解析

データ: data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx
出力:   output/ 配下のCSV一式 + REPORT.md（リポジトリ直下）

方針:
- 主要評価項目4つ（MMSE合計・CDR-SB・Global CDR・MoCA-J合計）は
  Shapiro-Wilk検定で差分の正規性を確認し、t検定 or Wilcoxon符号順位検定を選択。
- 下位項目17個（MMSE11+CDR6）は全てWilcoxon符号順位検定（変化が皆無の場合は検定不能として記録）。
- 主要4 + 下位17 = 21検定を1ファミリーとしてHolm法で多重比較補正。
- 0か月・18か月の対応ペアが揃う症例のみ各項目ごとに抽出（項目によって除外症例は異なる）。
"""
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy import stats
from statsmodels.stats.multitest import multipletests

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"
RNG_SEED = 12345

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
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
N_TOTAL = len(STUDY_IDS)


def sort_ids(ids):
    return sorted(ids, key=lambda x: int(x[1:]))


# ---------------------------------------------------------------------------
# 除外理由（要再確認ログ・原資料記載状況から確認済み）
# ---------------------------------------------------------------------------
EXCLUSION_REASONS = {
    ("MMSE合計・MMSE下位項目11個", "L20"): "18か月のMMSE原資料(PDF)が確認できず、全項目が空欄",
    ("MMSE合計・MMSE下位項目11個", "L29"): "18か月資料が今回のPDF内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("CDR-SB・Global CDR・CDR下位6領域", "L5"): "0か月のCDR-J用紙が原資料(PDF)内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("CDR-SB・Global CDR・CDR下位6領域", "L8"): "0か月のCDR-Jデータが原資料に記載なし（空欄）",
    ("CDR-SB・Global CDR・CDR下位6領域", "L19"): "0か月のCDR-Jデータが原資料に記載なし（空欄）",
    ("CDR-SB・Global CDR・CDR下位6領域", "L20"): "18か月の原資料(PDF)が確認できず、全項目が空欄",
    ("CDR-SB・Global CDR・CDR下位6領域", "L25"): "18か月のCDR-J用紙が原資料(PDF)内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("CDR-SB・Global CDR・CDR下位6領域", "L29"): "18か月資料が今回のPDF内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("MoCA-J合計", "L9"): "0か月のMoCA-Jデータが原資料に記載なし（空欄）",
    ("MoCA-J合計", "L3"): "18か月のMoCA-J用紙が原資料(PDF)内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("MoCA-J合計", "L10"): "18か月のMoCA-J用紙が原資料(PDF)内で確認できず空欄（該当ページにMoCA-Jの記載なし）",
    ("MoCA-J合計", "L11"): "18か月のMoCA-J用紙が原資料(PDF)内で確認できず空欄（該当ページにMoCA-Jの記載なし）",
    ("MoCA-J合計", "L15"): "18か月のMoCA-J用紙が原資料(PDF)内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("MoCA-J合計", "L18"): "18か月のMoCA-J用紙が原資料(PDF)内で確認できず空欄のままとされている（要再確認ログに記載）",
    ("MoCA-J合計", "L20"): "18か月の原資料(PDF)が確認できず、全項目が空欄",
    ("MoCA-J合計", "L29"): "18か月資料が今回のPDF内で確認できず空欄のままとされている（要再確認ログに記載）",
}

exclusions_records = []

# ---------------------------------------------------------------------------
# ペア抽出ユーティリティ
# ---------------------------------------------------------------------------
def get_paired_values(df, col, group_label):
    d0 = df[df["時点"] == "0か月"].set_index("研究番号")[col]
    d18 = df[df["時点"] == "18か月"].set_index("研究番号")[col]
    avail0 = {sid for sid in STUDY_IDS if sid in d0.index and pd.notna(d0.loc[sid])}
    avail18 = {sid for sid in STUDY_IDS if sid in d18.index and pd.notna(d18.loc[sid])}
    paired = sort_ids(avail0 & avail18)
    excluded = sort_ids(set(STUDY_IDS) - set(paired))

    for sid in excluded:
        reason = EXCLUSION_REASONS.get((group_label, sid))
        if reason is None:
            missing_at = []
            if sid not in avail0:
                missing_at.append("0か月")
            if sid not in avail18:
                missing_at.append("18か月")
            reason = f"{'/'.join(missing_at)}のデータが原資料に記載なし（空欄）"
        exclusions_records.append(
            {"対象項目グループ": group_label, "研究番号": sid, "除外理由": reason}
        )

    x0 = d0.loc[paired].astype(float).values
    x18 = d18.loc[paired].astype(float).values
    return paired, x0, x18, len(avail0), len(avail18)


def iqr(x):
    q1, q3 = np.percentile(x, [25, 75])
    return q1, q3


def describe(x0, x18, n0_avail, n18_avail, n_total=N_TOTAL):
    n_pair = len(x0)
    med0, med18 = np.median(x0), np.median(x18)
    q1_0, q3_0 = iqr(x0)
    q1_18, q3_18 = iqr(x18)
    return {
        "N(対応ペア)": n_pair,
        "欠測数(全%d例中)" % n_total: n_total - n_pair,
        "N(0か月のみ利用可)": n0_avail,
        "N(18か月のみ利用可)": n18_avail,
        "0か月_中央値": med0,
        "0か月_IQR": f"{q1_0:.2f}-{q3_0:.2f}",
        "18か月_中央値": med18,
        "18か月_IQR": f"{q1_18:.2f}-{q3_18:.2f}",
    }


# ---------------------------------------------------------------------------
# 検定ユーティリティ
# ---------------------------------------------------------------------------
def rank_biserial_effect(diff):
    nz = diff[diff != 0]
    if len(nz) == 0:
        return np.nan
    ranks = stats.rankdata(np.abs(nz))
    pos = ranks[nz > 0].sum()
    neg = ranks[nz < 0].sum()
    denom = pos + neg
    if denom == 0:
        return np.nan
    return (pos - neg) / denom


def bootstrap_median_ci(diff, seed=RNG_SEED):
    if len(np.unique(diff)) == 1:
        m = np.median(diff)
        return (m, m)
    res = stats.bootstrap(
        (diff,),
        np.median,
        confidence_level=0.95,
        method="percentile",
        n_resamples=9999,
        random_state=np.random.default_rng(seed),
    )
    return (res.confidence_interval.low, res.confidence_interval.high)


def primary_test(x0, x18):
    diff = x18 - x0
    n = len(diff)
    shapiro_p = np.nan
    if len(np.unique(diff)) > 1:
        shapiro_p = stats.shapiro(diff).pvalue

    if shapiro_p is not np.nan and shapiro_p > 0.05:
        method = "paired t-test"
        _, p = stats.ttest_rel(x18, x0)
        mean_diff = diff.mean()
        sd_diff = diff.std(ddof=1)
        se = sd_diff / np.sqrt(n)
        tcrit = stats.t.ppf(0.975, n - 1)
        ci = (mean_diff - tcrit * se, mean_diff + tcrit * se)
        dz = mean_diff / sd_diff if sd_diff > 0 else np.nan
        return {
            "正規性(Shapiro-Wilk p)": shapiro_p,
            "選択した検定": method,
            "p値(未補正)": p,
            "点推定(差分の代表値)": mean_diff,
            "95%CI_下限": ci[0],
            "95%CI_上限": ci[1],
            "効果量の種類": "Cohen's dz",
            "効果量": dz,
        }
    else:
        method = "Wilcoxon signed-rank"
        if np.all(diff == 0):
            p = np.nan
        else:
            _, p = stats.wilcoxon(diff, zero_method="wilcox", mode="auto")
        median_diff = np.median(diff)
        ci = bootstrap_median_ci(diff)
        r = rank_biserial_effect(diff)
        return {
            "正規性(Shapiro-Wilk p)": shapiro_p,
            "選択した検定": method,
            "p値(未補正)": p,
            "点推定(差分の代表値)": median_diff,
            "95%CI_下限": ci[0],
            "95%CI_上限": ci[1],
            "効果量の種類": "matched-pairs rank-biserial r",
            "効果量": r,
        }


def secondary_test(x0, x18):
    diff = x18 - x0
    if np.all(diff == 0):
        p = np.nan
        method = "Wilcoxon signed-rank（全例差分0のため検定不能）"
    else:
        try:
            _, p = stats.wilcoxon(diff, zero_method="wilcox", mode="auto")
            method = "Wilcoxon signed-rank"
        except ValueError:
            p = np.nan
            method = "Wilcoxon signed-rank（計算不能）"
    r = rank_biserial_effect(diff)
    median_diff = np.median(diff)
    n_changed = int(np.sum(diff != 0))
    n_increase = int(np.sum(diff > 0))
    n_decrease = int(np.sum(diff < 0))
    return {
        "選択した検定": method,
        "p値(未補正)": p,
        "中央値差分": median_diff,
        "効果量(rank-biserial r)": r,
        "変化ありの例数": n_changed,
        "増加例数": n_increase,
        "減少例数": n_decrease,
    }


# ---------------------------------------------------------------------------
# 主要評価項目4つ
# ---------------------------------------------------------------------------
primary_defs = [
    ("MMSE合計", mmse, "下位項目合計_自動計算", "MMSE合計・MMSE下位項目11個"),
    ("CDR-SB", cdr, "CDR-SB_自動計算", "CDR-SB・Global CDR・CDR下位6領域"),
    ("Global CDR", cdr, "Global CDR_原資料記載値", "CDR-SB・Global CDR・CDR下位6領域"),
    ("MoCA-J合計", moca, "合計_原資料記載値", "MoCA-J合計"),
]

primary_rows = []
all_tests = []  # (項目区分, 項目名, p値)

for label, df, col, group in primary_defs:
    paired, x0, x18, n0a, n18a = get_paired_values(df, col, group)
    desc = describe(x0, x18, n0a, n18a)
    test = primary_test(x0, x18)
    row = {"項目": label, **desc, **test}
    primary_rows.append(row)
    all_tests.append(("主要評価項目", label, test["p値(未補正)"]))

primary_df = pd.DataFrame(primary_rows)

# ---------------------------------------------------------------------------
# 下位項目: MMSE 11項目
# ---------------------------------------------------------------------------
mmse_items = [
    "時間見当識", "場所見当識", "物品呼称", "記銘", "注意計算",
    "遅延再生", "復唱", "読字理解", "3段階命令", "書字", "図形模写",
]
cdr_items = ["記憶", "見当識", "判断力・問題解決", "地域社会の活動", "家庭・趣味", "身の回りの世話"]

secondary_rows = []

for item in mmse_items:
    paired, x0, x18, n0a, n18a = get_paired_values(mmse, item, "MMSE合計・MMSE下位項目11個")
    desc = describe(x0, x18, n0a, n18a)
    test = secondary_test(x0, x18)
    row = {"項目区分": "MMSE下位項目", "項目": item, **desc, **test}
    secondary_rows.append(row)
    all_tests.append(("下位項目(探索的)", f"MMSE:{item}", test["p値(未補正)"]))

for item in cdr_items:
    paired, x0, x18, n0a, n18a = get_paired_values(cdr, item, "CDR-SB・Global CDR・CDR下位6領域")
    desc = describe(x0, x18, n0a, n18a)
    test = secondary_test(x0, x18)
    row = {"項目区分": "CDR下位領域", "項目": item, **desc, **test}
    secondary_rows.append(row)
    all_tests.append(("下位項目(探索的)", f"CDR:{item}", test["p値(未補正)"]))

secondary_df = pd.DataFrame(secondary_rows)

# ---------------------------------------------------------------------------
# Holm法による多重比較補正（主要4 + 下位17 = 21検定を1ファミリーとして）
# ---------------------------------------------------------------------------
family_labels = [t[1] for t in all_tests]
family_p = [t[2] for t in all_tests]

# NaN（検定不能）は補正対象から除外し、補正後はNaNのまま保持
valid_mask = [not (p is None or (isinstance(p, float) and np.isnan(p))) for p in family_p]
valid_p = [p for p, v in zip(family_p, valid_mask) if v]

adj_p_full = [np.nan] * len(family_p)
if valid_p:
    _, adj_p_valid, _, _ = multipletests(valid_p, method="holm", alpha=0.05)
    it = iter(adj_p_valid)
    for i, v in enumerate(valid_mask):
        if v:
            adj_p_full[i] = next(it)

holm_df = pd.DataFrame(
    {
        "検定区分": [t[0] for t in all_tests],
        "項目": family_labels,
        "p値(未補正)": family_p,
        "p値(Holm補正後)": adj_p_full,
        "有意(補正後 p<0.05)": [
            (not np.isnan(p)) and p < 0.05 for p in adj_p_full
        ],
    }
)

# 主要・下位の各表にHolm補正後p値をマージ
primary_df = primary_df.merge(
    holm_df[holm_df["検定区分"] == "主要評価項目"][["項目", "p値(Holm補正後)", "有意(補正後 p<0.05)"]],
    on="項目", how="left",
)

secondary_df["__key"] = secondary_df.apply(
    lambda r: f"{'MMSE' if r['項目区分']=='MMSE下位項目' else 'CDR'}:{r['項目']}", axis=1
)
holm_secondary = holm_df[holm_df["検定区分"] == "下位項目(探索的)"][["項目", "p値(Holm補正後)", "有意(補正後 p<0.05)"]]
secondary_df = secondary_df.merge(
    holm_secondary, left_on="__key", right_on="項目", suffixes=("", "_drop")
)
secondary_df = secondary_df.drop(columns=["__key", "項目_drop"], errors="ignore")

# ---------------------------------------------------------------------------
# MMSE 場所見当識の内訳（記述統計のみ。検定なし）
# ---------------------------------------------------------------------------
location_subitems = ["場所_県", "場所_市", "場所_病院", "場所_階", "場所_地方"]
location_rows = []
for item in location_subitems:
    paired, x0, x18, n0a, n18a = get_paired_values(mmse, item, "MMSE合計・MMSE下位項目11個")
    diff = x18 - x0
    location_rows.append(
        {
            "項目": item,
            "N(対応ペア)": len(paired),
            "0か月_中央値": np.median(x0),
            "18か月_中央値": np.median(x18),
            "変化ありの例数": int(np.sum(diff != 0)),
            "増加例数": int(np.sum(diff > 0)),
            "減少例数": int(np.sum(diff < 0)),
        }
    )
location_df = pd.DataFrame(location_rows)

# ---------------------------------------------------------------------------
# 精神症状（全体・時点別データなし、記述統計のみ）
# ---------------------------------------------------------------------------
n_psych = len(psych)
psych_rows = []
for col in ["易怒性", "意欲低下", "両方なし"]:
    cnt = int(psych[col].sum())
    psych_rows.append({"項目": col, "該当人数": cnt, "割合(%)": round(100 * cnt / n_psych, 1), "N": n_psych})
psych_df = pd.DataFrame(psych_rows)

# 整合性チェック: 各症例で3カテゴリが一意かどうか
psych_check = psych[["易怒性", "意欲低下", "両方なし"]].sum(axis=1)
psych_multi_flag = (psych_check != 1).sum()

# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
import os

os.makedirs(OUT, exist_ok=True)

exclusions_df = pd.DataFrame(exclusions_records).drop_duplicates()

primary_df.to_csv(f"{OUT}/01_primary_results.csv", index=False, encoding="utf-8-sig")
secondary_df.to_csv(f"{OUT}/02_secondary_results.csv", index=False, encoding="utf-8-sig")
holm_df.to_csv(f"{OUT}/03_holm_correction_all21.csv", index=False, encoding="utf-8-sig")
location_df.to_csv(f"{OUT}/04_location_subitems_descriptive.csv", index=False, encoding="utf-8-sig")
psych_df.to_csv(f"{OUT}/05_psychiatric_symptoms.csv", index=False, encoding="utf-8-sig")
exclusions_df.to_csv(f"{OUT}/06_exclusions.csv", index=False, encoding="utf-8-sig")

with open(f"{OUT}/00_meta.json", "w", encoding="utf-8") as f:
    json.dump({"n_total": N_TOTAL, "study_ids": STUDY_IDS}, f, ensure_ascii=False, indent=2)

print("=== 主要評価項目 ===")
print(primary_df.to_string(index=False))
print("\n=== Holm補正(全21検定) ===")
print(holm_df.to_string(index=False))
print("\n=== 場所見当識 内訳(記述のみ) ===")
print(location_df.to_string(index=False))
print("\n=== 精神症状 ===")
print(psych_df.to_string(index=False))
print("\n=== 整合性チェック: 精神症状3カテゴリが一意でない例数 ===", psych_multi_flag)
print("\n=== 除外症例一覧 ===")
print(exclusions_df.to_string(index=False))

print("\nDone. CSV出力先:", OUT)
