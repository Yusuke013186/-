"""
ステップ1: データの全体棚卸し

元のExcelファイルの全シート・全列を機械的に一覧化し、これまでの3つの解析
(REPORT.md / EXPLORATORY_ASSOCIATIONS.md / explore_all_pairs.py)で使用済みの列と
未使用の列を突き合わせる。未使用変数を深掘りに使う前に、まずこの結果を
そのままユーザーに提示し、解析方針の確認を取ることを優先する(自動で先に進まない)。
"""
import json
import numpy as np
import pandas as pd
import openpyxl

SRC = "data/レカネマブ研究_L1-33_分割構造マスター_v19.xlsx"
OUT = "output"

wb = openpyxl.load_workbook(SRC, data_only=True)


def sheet_to_df(name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


# これまでの3解析で実際に使用した列(シート, 列名)を明示的に列挙
USED_COLUMNS = {
    ("MMSE", "研究番号"), ("MMSE", "時点"),
    ("MMSE", "下位項目合計_自動計算"),
    ("MMSE", "時間見当識"), ("MMSE", "場所見当識"), ("MMSE", "物品呼称"),
    ("MMSE", "記銘"), ("MMSE", "注意計算"), ("MMSE", "遅延再生"),
    ("MMSE", "復唱"), ("MMSE", "読字理解"), ("MMSE", "3段階命令"),
    ("MMSE", "書字"), ("MMSE", "図形模写"),
    ("MMSE", "場所_県"), ("MMSE", "場所_市"), ("MMSE", "場所_病院"),
    ("MMSE", "場所_階"), ("MMSE", "場所_地方"),  # 記述統計のみ(検定なし)
    ("CDR", "研究番号"), ("CDR", "時点"),
    ("CDR", "CDR-SB_自動計算"), ("CDR", "Global CDR_原資料記載値"),
    ("CDR", "記憶"), ("CDR", "見当識"), ("CDR", "判断力・問題解決"),
    ("CDR", "地域社会の活動"), ("CDR", "家庭・趣味"), ("CDR", "身の回りの世話"),
    ("MoCA-J", "研究番号"), ("MoCA-J", "時点"), ("MoCA-J", "合計_原資料記載値"),
    ("精神症状", "研究番号"), ("精神症状", "時点"),
    ("精神症状", "易怒性"), ("精神症状", "意欲低下"), ("精神症状", "両方なし"),
    ("要再確認ログ", "研究番号"), ("要再確認ログ", "内容"),  # 除外理由の手動クロスリファレンスのみ
}

# これまで未使用だが今回新たに見つかった「時点」: 0/18か月以外に6/12/24か月も存在する
ALL_TIMEPOINTS = ["0か月", "6か月", "12か月", "18か月", "24か月"]

SHEETS = ["README", "MMSE", "CDR", "MoCA-J", "精神症状", "要再確認ログ"]

inventory_rows = []
for sheet in SHEETS:
    if sheet == "README":
        continue
    df = sheet_to_df(sheet)
    for col in df.columns:
        s = df[col]
        n_total = len(s)
        n_missing = s.isna().sum()
        try:
            n_unique = s.dropna().nunique()
        except TypeError:
            n_unique = np.nan
        dtype = str(s.dropna().map(type).mode().iloc[0]) if n_missing < n_total else "all-NaN"
        sample_vals = s.dropna().unique()[:5]
        inventory_rows.append({
            "シート": sheet, "列名": col,
            "全行数": n_total, "欠測数": int(n_missing),
            "欠測率(%)": round(100 * n_missing / n_total, 1) if n_total else np.nan,
            "ユニーク値数": n_unique,
            "サンプル値(最大5)": ", ".join(map(str, sample_vals)),
            "これまでの解析で使用": "済" if (sheet, col) in USED_COLUMNS else "未使用",
        })

inventory_df = pd.DataFrame(inventory_rows)
inventory_df.to_csv(f"{OUT}/20_variable_inventory.csv", index=False, encoding="utf-8-sig")

unused_df = inventory_df[inventory_df["これまでの解析で使用"] == "未使用"].reset_index(drop=True)
unused_df.to_csv(f"{OUT}/20b_unused_variables.csv", index=False, encoding="utf-8-sig")

# 時点の棚卸し: 既存解析は0か月・18か月のみ使用していたが、実際は6/12/24か月のデータも存在する
mmse = sheet_to_df("MMSE")
cdr = sheet_to_df("CDR")
moca = sheet_to_df("MoCA-J")

timepoint_rows = []
for sheet_name, df, value_col in [
    ("MMSE", mmse, "下位項目合計_自動計算"),
    ("CDR", cdr, "CDR-SB_自動計算"),
    ("MoCA-J", moca, "合計_原資料記載値"),
]:
    for tp in ALL_TIMEPOINTS:
        n_have = df[df["時点"] == tp][value_col].notna().sum()
        timepoint_rows.append({"シート": sheet_name, "時点": tp, "値あり症例数": int(n_have),
                                "既存解析(0/18か月のみ)で使用": "済" if tp in ("0か月", "18か月") else "未使用"})
timepoint_df = pd.DataFrame(timepoint_rows)
timepoint_df.to_csv(f"{OUT}/20c_timepoint_inventory.csv", index=False, encoding="utf-8-sig")

print("=== シート一覧 ===")
for name in SHEETS:
    print(f"  {name}")

print(f"\n=== 全列数: {len(inventory_df)} / 未使用列数: {len(unused_df)} ===\n")
print(unused_df[["シート", "列名", "欠測率(%)", "ユニーク値数", "サンプル値(最大5)"]].to_string(index=False))

print("\n=== 時点別の値あり症例数(全シート・全時点) ===")
print(timepoint_df.to_string(index=False))
