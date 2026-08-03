# -*- coding: utf-8 -*-
"""フェーズ0: データ読み込みと群定義(n=9/n=20)の再現性検証"""
import pandas as pd, numpy as np, sys, pathlib

XLSX = "レカネマブ研究_L1-66_白青交互配色_修正版_v19.xlsx"
OUT = pathlib.Path("output"); OUT.mkdir(exist_ok=True)

def load():
    mmse = pd.read_excel(XLSX, sheet_name="MMSE")
    cdr  = pd.read_excel(XLSX, sheet_name="CDR")
    moca = pd.read_excel(XLSX, sheet_name="MoCA-J")
    psy  = pd.read_excel(XLSX, sheet_name="精神症状")
    return mmse, cdr, moca, psy

mmse, cdr, moca, psy = load()

print("=== シート形状 ===")
for n, d in [("MMSE", mmse), ("CDR", cdr), ("MoCA-J", moca), ("精神症状", psy)]:
    print(f"{n}: {d.shape}")

print("\n=== 時点の値 ===")
print(mmse["時点"].value_counts(dropna=False).to_string())

print("\n=== 精神症状: 訴え列の値 ===")
col = "レカネマブ投与後に何らかの症状改善の訴えあり"
print(psy[col].value_counts(dropna=False).to_string())
print("研究番号ユニーク数:", psy["研究番号"].nunique(), " 行数:", len(psy))

# --- 18か月MMSEデータが存在する症例 ---
m18 = mmse[(mmse["時点"] == "18か月")].copy()
m18_ok = m18[m18["合計_原資料記載値"].notna()]
ids18 = set(m18_ok["研究番号"])
print("\n=== 18か月MMSE 実測値あり症例数 ===", len(ids18))

psy_i = psy.set_index("研究番号")
ari  = sorted([i for i in ids18 if psy_i.loc[i, col] == "あり"], key=lambda s: int(s[1:]))
nasi = sorted([i for i in ids18 if psy_i.loc[i, col] == "記載なし"], key=lambda s: int(s[1:]))
other= sorted([i for i in ids18 if psy_i.loc[i, col] not in ("あり", "記載なし")], key=lambda s: int(s[1:]))

print(f"訴えあり群 n={len(ari)}: {ari}")
print(f"訴えなし群 n={len(nasi)}: {nasi}")
if other:
    print(f"その他の値 n={len(other)}: {other}")

print(f"\n全体(N=66)  あり={int((psy[col]=='あり').sum())} / 記載なし={int((psy[col]=='記載なし').sum())}")

ok = (len(ari) == 9 and len(nasi) == 20)
print("\n*** 群定義 再現性チェック:", "PASS (n=9 / n=20 再現)" if ok else "FAIL", "***")

# 保存
pd.DataFrame({"研究番号": ari + nasi,
              "群": ["訴えあり"]*len(ari) + ["訴えなし"]*len(nasi)}).to_csv(
    OUT/"群定義_18M_29例.csv", index=False, encoding="utf-8-sig")

# 精神症状の記述（結果1との突合用）
print("\n=== 精神症状フラグ 全体(N=66) ===")
for c in ["易怒性", "意欲低下", "両方なし"]:
    print(f"{c}: あり={int(pd.to_numeric(psy[c], errors='coerce').fillna(0).sum())} / {len(psy)}")

if not ok:
    sys.exit(1)
