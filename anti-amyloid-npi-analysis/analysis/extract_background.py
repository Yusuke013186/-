# -*- coding: utf-8 -*-
"""
患者背景（年齢・性別・投与開始日）の抽出

提供された一覧表には氏名・よみがな・カルテIDが含まれるため、
本スクリプトは研究番号・年齢・性別・投与開始日のみを取り出した
連結不可能な形の CSV を生成する。氏名・よみがな・カルテIDは
一切出力せず、元ファイルもリポジトリには置かない。

使い方:
    python3 analysis/extract_background.py <レカネマブ一覧.xlsx> <ドナネマブ一覧.xlsx>

出力:
    data_local/patient_background.csv       研究番号・年齢・性別・投与開始日
    output/background_extraction_log.md     抽出時の注意点と既存データとの整合確認
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import sys

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data_local")
OUT = os.path.join(ROOT, "output")

SEX_MAP = {"F": "女性", "Ｆ": "女性", "女": "女性", "f": "女性",
           "M": "男性", "Ｍ": "男性", "男": "男性", "m": "男性"}


def norm_sex(v) -> tuple[str, str]:
    """性別を正規化する。戻り値は (正規化後, 注記)。"""
    if v is None:
        return "", "性別の記載なし"
    s = str(v).strip()
    if s in SEX_MAP:
        return SEX_MAP[s], ("全角の記載を正規化" if s in ("Ｆ", "Ｍ") else "")
    return "", f"性別の記載を判定できない（{s!r}）"


def norm_date(v) -> tuple[object, str]:
    """投与開始日を正規化する。推測による補正は行わない。"""
    if v is None:
        return None, "投与開始日の記載なし"
    if isinstance(v, dt.datetime):
        return v.date(), ""
    s = str(v).strip()
    m = re.match(r"^(\d{3,4})/(\d{1,2})/(\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 1000:
            return None, f"年の記載が3桁で確定できない（{s}）"
        try:
            return dt.date(y, mo, d), ""
        except ValueError:
            return None, f"暦上存在しない日付（{s}）"
    return None, f"日付として解釈できない（{s}）"


def main(lec_path: str, don_path: str) -> None:
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    recs: list[dict] = []
    log: list[str] = ["# 患者背景の抽出ログ\n",
                      f"生成日時: {dt.datetime.now():%Y-%m-%d %H:%M}\n",
                      "元ファイルには氏名・よみがな・カルテIDが含まれるため、"
                      "研究番号・年齢・性別・投与開始日のみを抽出した。"
                      "氏名等は出力せず、元ファイルもリポジトリには置いていない。\n"]

    # --- レカネマブ一覧（2行目がヘッダ）
    rows = list(openpyxl.load_workbook(lec_path, data_only=True)["Sheet1"]
                .iter_rows(values_only=True))
    hdr = [str(c).strip() if c is not None else "" for c in rows[1]]
    i_date, i_age, i_sex = hdr.index("日付"), hdr.index("年齢"), hdr.index("性別")
    notes_l: list[str] = []
    for r in rows[2:]:
        pid = str(r[0]).strip() if r[0] is not None else ""
        if not re.fullmatch(r"L\d+", pid):
            continue
        age = r[i_age]
        sex, sn = norm_sex(r[i_sex])
        d, dn = norm_date(r[i_date])
        if sn:
            notes_l.append(f"{pid}: {sn}")
        if dn:
            notes_l.append(f"{pid}: {dn}")
        if not isinstance(age, (int, float)):
            notes_l.append(f"{pid}: 年齢が数値でない（{age!r}）")
            age = None
        recs.append({"研究番号": pid, "薬剤": "レカネマブ", "年齢": age,
                     "性別": sex, "投与開始日": d})

    # --- ドナネマブ一覧（1行目がヘッダ、年齢の列はない）
    rows2 = list(openpyxl.load_workbook(don_path, data_only=True)["Sheet1"]
                 .iter_rows(values_only=True))
    hdr2 = [str(c).strip() if c is not None else "" for c in rows2[0]]
    j_sex = hdr2.index("性別")
    notes_d: list[str] = []
    for r in rows2[1:]:
        pid = str(r[0]).strip() if r[0] is not None else ""
        if not re.fullmatch(r"D\d+", pid):
            continue
        sex, sn = norm_sex(r[j_sex])
        if sn:
            notes_d.append(f"{pid}: {sn}")
        recs.append({"研究番号": pid, "薬剤": "ドナネマブ", "年齢": None,
                     "性別": sex, "投与開始日": None})

    with io.open(os.path.join(DATA, "patient_background.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["研究番号", "薬剤", "年齢", "性別", "投与開始日"])
        w.writeheader()
        for r in recs:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})

    lec = [r for r in recs if r["薬剤"] == "レカネマブ"]
    don = [r for r in recs if r["薬剤"] == "ドナネマブ"]
    log.append("\n## 抽出結果\n")
    log.append(f"- レカネマブ: {len(lec)}例"
               f"（年齢あり {sum(1 for r in lec if r['年齢'] is not None)}例、"
               f"性別あり {sum(1 for r in lec if r['性別'])}例、"
               f"投与開始日あり {sum(1 for r in lec if r['投与開始日'])}例）")
    log.append(f"- ドナネマブ: {len(don)}例"
               f"（**年齢の列が元表に存在しない**、"
               f"性別あり {sum(1 for r in don if r['性別'])}例）")
    ages = [r["年齢"] for r in lec if r["年齢"] is not None]
    if ages:
        import statistics as st
        log.append(f"- レカネマブの年齢: {st.mean(ages):.1f}±{st.stdev(ages):.1f}歳"
                   f"［{min(ages)}, {max(ages)}］")
    ds = [r["投与開始日"] for r in lec if r["投与開始日"]]
    if ds:
        log.append(f"- レカネマブの投与開始日: {min(ds)} 〜 {max(ds)}")
    log.append("\n## 抽出時に判断を要した点\n")
    if notes_l or notes_d:
        for n in notes_l + notes_d:
            log.append(f"- {n}")
        log.append("\n上記はいずれも推測による補正を行わず、欠測として扱った。")
    else:
        log.append("- なし")

    # --- 既存データとの整合確認（MMSE初回値で突合）
    log.append("\n## 既存の解析用データとの整合確認\n")
    log.append("背景一覧表にもMMSE等の列があるため、解析に用いている"
               "`data_local/lecanemab_L1-66_NPI.xlsx` のMMSE初回値と突合した。"
               "解析には従来どおり後者のみを用いる。\n")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from deep_analysis import read_panel, bl_fu
        mm = read_panel(os.path.join(DATA, "lecanemab_L1-66_NPI.xlsx"), "MMSE")
        i_mmse = hdr.index("MMSE")            # 初回MMSEの列
        agree = disagree = only_bg = only_an = 0
        diffs = []
        for r in rows[2:]:
            pid = str(r[0]).strip() if r[0] is not None else ""
            if not re.fullmatch(r"L\d+", pid):
                continue
            b = next((v for v in mm.get(pid, [])
                      if v.label == "0か月" and v.total is not None), None)
            a = r[i_mmse]
            a = a if isinstance(a, (int, float)) else None
            if a is None and b is None:
                continue
            if a is None:
                only_an += 1
            elif b is None:
                only_bg += 1
            elif float(a) == float(b.total):
                agree += 1
            else:
                disagree += 1
                diffs.append(f"{pid}: 背景表 {a} / 解析データ {b.total:g}")
        log.append(f"- 初回MMSEが一致: {agree}例")
        log.append(f"- 不一致: {disagree}例" + (f"（{'、'.join(diffs)}）" if diffs else ""))
        log.append(f"- 背景表のみに値あり: {only_bg}例 / 解析データのみに値あり: {only_an}例")
        if disagree == 0:
            log.append("\n→ 研究番号の対応に齟齬はなく、背景情報を安全に結合できる。")
    except Exception as e:                                    # pragma: no cover
        log.append(f"- 整合確認を実行できなかった: {e}")

    text = "\n".join(log)
    with io.open(os.path.join(OUT, "background_extraction_log.md"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
