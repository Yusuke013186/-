# 再解析一式（研究の問いの変更版）

研究の問いを「NPIアパシースコアが低下した2例の推移」から
**「NPIアパシースコアが上昇した症例と上昇しなかった症例で認知機能の変化が異なるか」**
に変更して実施した再解析の成果物。

元データ・旧解析コード・旧抄録はいずれも変更していない。

## 成果物

| 種別 | パス |
|---|---|
| 修正抄録（テキスト） | `abstract_v2/抄録_NPIアパシースコア上昇の有無と認知機能変化.md` |
| 修正抄録（Word） | `abstract_v2/抄録_NPIアパシースコア上昇の有無と認知機能変化.docx` |
| 再解析レポート（全文） | `output_v2/v2_reanalysis_report.md` |
| 再解析表（Excel 9シート） | `output_v2/再解析表_NPIアパシースコア上昇の有無.xlsx` |
| 変更・検証メモ | `output_v2/v2_変更・検証メモ.md` |
| 解析コード | `analysis/npi_increase_analysis.py` |

## 再実行

```bash
python3 analysis/npi_increase_analysis.py
```

読み込むファイル・シート・列、症例選択、欠測処理、評価時点の選択はすべて
コード内に記述されており、`output_v2/` の全CSVとレポートが再生成される。

## 個別CSV

| ファイル | 内容 |
|---|---|
| `v2_selection_flow.csv` | 97研究番号の組み入れフロー（S1〜S5） |
| `v2_case_detail.csv` | 匿名症例別の採用評価日・初回値・追跡値・変化量・新分類 |
| `v2_timepoints.csv` | 症例ごとのNPI評価日、認知機能評価日、経過月数、ずれ |
| `v2_summary_stats.csv` | 両群の背景・NPI・主要評価項目の集計と検定結果 |
| `v2_exploratory_subitems.csv` | MMSE下位11項目・CDR下位6領域の探索的比較 |
| `v2_direction_counts.csv` | 主要評価項目の上昇・不変・低下の症例数 |
| `v2_baseline_ceiling.csv` | 初回値の分布と満点例の数 |
| `v2_sensitivity.csv` | 感度分析2件の結果 |
| `v2_old_abstract_reconciliation.csv` | 旧抄録の下位項目と合計点の突合 |

## 主な結果

- 対象: 97研究番号 → NPIスコアが初回・追跡時とも算出できた21例 → MMSE・CDRの追跡も
  得られた **14例**（全例レカネマブ）
- **スコア上昇群5例 / 非上昇群9例**
- ΔMMSE合計: 0［−2, 3］ vs 0［−4, 3］（p=0.73）
- ΔCDR-SB: 0.5［0, 2.5］ vs 1［0, 2］（p=1.00）
- MMSE下位11項目・CDR下位6領域を多重性未調整で比較し、p<0.05は **0件**
- **両群に明瞭な違いを示すことはできなかった**
