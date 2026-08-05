# -*- coding: utf-8 -*-
"""結果2・結果3・結果4・参考1・参考2で使う5つのスライドを、画像ではなく
本物のPowerPointネイティブグラフ（右クリック→「データの編集」が可能）として
組み立てる関数群。common.py のデータ・群定義をそのまま使う。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import numpy as np
from pptx.util import Emu, Pt
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.dml.color import RGBColor
from pptx.chart.data import CategoryChartData, XyChartData
from scipy import stats

from common import (load_all, define_groups, wide_scores, mean_ci,
                    TP_LABELS, TP_MONTHS, MMSE_SUBITEMS, MMSE_SUB_MAX)
from chart_kit import (RED, BLUE, GREY, REFLINE, rgb, add_error_bars, hide_legend_entries,
                       style_chart, style_axis, style_mean_series, style_individual_series,
                       style_scatter_points_only, style_ref_line)

rng = np.random.default_rng(20250805)

mmse, cdr, moca, psy = load_all()
ari, nasi, grp = define_groups(mmse, psy)
IDS = ari + nasi
W_MMSE = wide_scores(mmse, "合計_原資料記載値", IDS)
D_MMSE = W_MMSE.sub(W_MMSE["0か月"], axis=0)


def _rect_to_inches(rect):
    x, y, w, h = rect
    return Emu(x), Emu(y), Emu(w), Emu(h)


# ============================================================
# 結果2：改善の訴えをアンカーとしたΔMMSEの推移（XY散布グラフ）
# ============================================================

def build_kekka2_chart(slide, rect):
    """LibreOfficeのXY散布図には「先に追加した系列の点数が、後で追加した系列の点数より
    少ないと、先の系列が描画されないことがある」という表示上の既知の癖があるため、
    系列は必ず点数の多い順（降順）に追加する。データ自体はどの順でも同一。"""
    ANN = -1.01
    DTP, DX = ["6か月", "12か月", "18か月"], [6, 12, 18]

    xd = XyChartData()

    # 点数の多い順：個別症例(なし→あり) → 群平均・参照帯（同数） → Δ=0（最少）
    s_nasi_ind = xd.add_series("改善訴えなし 個別症例")
    for pid in nasi:
        for t, x in zip(DTP, DX):
            y = D_MMSE.loc[pid, t]
            if pd_notna(y):
                s_nasi_ind.add_data_point(round(x + rng.uniform(-0.35, 0.35), 3), round(float(y), 3))

    s_ari_ind = xd.add_series("改善訴えあり 個別症例")
    for pid in ari:
        for t, x in zip(DTP, DX):
            y = D_MMSE.loc[pid, t]
            if pd_notna(y):
                s_ari_ind.add_data_point(round(x + rng.uniform(-0.35, 0.35), 3), round(float(y), 3))

    ari_ms = [mean_ci(D_MMSE.loc[ari, t]) for t in DTP]
    nasi_ms = [mean_ci(D_MMSE.loc[nasi, t]) for t in DTP]
    s_ari_mean = xd.add_series("改善訴えあり 群平均 (n=9)")
    for x, (m, h, n) in zip(DX, ari_ms):
        s_ari_mean.add_data_point(x, round(m, 3))
    s_nasi_mean = xd.add_series("改善訴えなし 群平均 (n=20)")
    for x, (m, h, n) in zip(DX, nasi_ms):
        s_nasi_mean.add_data_point(x, round(m, 3))

    s_ref_top = xd.add_series("参照帯上限（年−1.01点の低下相当）")
    s_ref_bot = xd.add_series("参照帯下限")
    for x in DX:
        band = ANN * x / 12
        s_ref_top.add_data_point(x, round(band + 0.35, 3))
        s_ref_bot.add_data_point(x, round(band - 0.35, 3))

    s_zero = xd.add_series("Δ=0")
    s_zero.add_data_point(0, 0); s_zero.add_data_point(24, 0)

    x, y, w, h = _rect_to_inches(rect)
    gframe = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES, x, y, w, h, xd)
    chart = gframe.chart
    style_chart(chart, legend_pos=XL_LEGEND_POSITION.BOTTOM)

    plot = chart.plots[0]
    ser = plot.series
    # ser[0]=なし個別 ser[1]=あり個別 ser[2]=あり平均 ser[3]=なし平均 ser[4]=上限 ser[5]=下限 ser[6]=Δ0
    style_scatter_points_only(ser[0], BLUE, size=5, alpha_pct=35)
    style_scatter_points_only(ser[1], RED, size=5, alpha_pct=35)
    style_mean_series(ser[2], RED, width_pt=2.8, marker_size=9)
    style_mean_series(ser[3], BLUE, width_pt=2.8, marker_size=9)
    style_ref_line(ser[4]); style_ref_line(ser[5])
    ser[6].format.line.color.rgb = rgb("404040")
    ser[6].format.line.width = Pt(1.0)
    ser[6].marker.style = XL_MARKER_STYLE.NONE

    ari_h = [a[1] for a in ari_ms]; nasi_h = [a[1] for a in nasi_ms]
    add_error_bars(ser[2], ari_h, ari_h, color=RED)
    add_error_bars(ser[3], nasi_h, nasi_h, color=BLUE)

    hide_legend_entries(chart, [4, 5, 6])

    # 縦軸：ゼロを中心に整数のみを振る（実測データは-9〜+6）
    val_ax = chart.value_axis
    style_axis(val_ax, title="Δ MMSE（ベースラインからの変化量、点）", min_=-10, max_=10, major_unit=2)
    # 横軸：実際のデータ点（6・12・18か月）に目盛りが一致するよう整数化
    cat_ax = chart.category_axis
    style_axis(cat_ax, title="レカネマブ投与開始からの経過時点（か月）", min_=0, max_=24, major_unit=6)
    return chart


def pd_notna(v):
    import pandas as pd
    return pd.notna(v)


# ============================================================
# 結果3：個別症例のMMSE推移（29例、カテゴリ軸の折れ線グラフ）
#   ※参考1（群別2パネル）もこの関数の左右分割版として使う
# ============================================================

def _build_overlay_line_chart(slide, rect, ids_nasi, ids_ari, title_x=None, title_y=None,
                              show_legend=True):
    cd = CategoryChartData()
    cd.categories = TP_LABELS
    idx_nasi = list(range(len(ids_nasi)))
    for pid in ids_nasi:
        vals = tuple(W_MMSE.loc[pid, t] if pd_notna(W_MMSE.loc[pid, t]) else None for t in TP_LABELS)
        cd.add_series(f"{pid}（訴えなし）", vals)
    idx_ari_start = len(ids_nasi)
    for pid in ids_ari:
        vals = tuple(W_MMSE.loc[pid, t] if pd_notna(W_MMSE.loc[pid, t]) else None for t in TP_LABELS)
        cd.add_series(f"{pid}（訴えあり）", vals)
    idx_mean_nasi = len(ids_nasi) + len(ids_ari)
    mean_nasi = [mean_ci(W_MMSE.loc[ids_nasi, t])[0] for t in TP_LABELS]
    cd.add_series(f"改善訴えなし 群平均 (n={len(ids_nasi)})", tuple(round(v, 3) for v in mean_nasi))
    idx_mean_ari = idx_mean_nasi + 1
    mean_ari = [mean_ci(W_MMSE.loc[ids_ari, t])[0] for t in TP_LABELS]
    cd.add_series(f"改善訴えあり 群平均 (n={len(ids_ari)})", tuple(round(v, 3) for v in mean_ari))

    x, y, w, h = _rect_to_inches(rect)
    gframe = slide.shapes.add_chart(XL_CHART_TYPE.LINE, x, y, w, h, cd)
    chart = gframe.chart
    style_chart(chart, legend=show_legend, legend_pos=XL_LEGEND_POSITION.BOTTOM)

    ser = chart.plots[0].series
    for i in idx_nasi:
        style_individual_series(ser[i], BLUE, width_pt=1.0, alpha_pct=42)
    for i in range(idx_ari_start, idx_mean_nasi):
        style_individual_series(ser[i], RED, width_pt=1.2, alpha_pct=55)
    style_mean_series(ser[idx_mean_nasi], BLUE, width_pt=3.2, marker_size=8)
    style_mean_series(ser[idx_mean_ari], RED, width_pt=3.2, marker_size=8)

    if show_legend:
        hide_indices = list(range(0, idx_mean_nasi))
        hide_legend_entries(chart, hide_indices)

    # 縦軸：MMSE実測値（実データは16〜29点）を整数目盛りで表示
    val_ax = chart.value_axis
    style_axis(val_ax, title=title_y, min_=14, max_=30, major_unit=2)
    cat_ax = chart.category_axis
    style_axis(cat_ax, title=title_x, grid=False)
    return chart


def build_kekka3_chart(slide, rect):
    return _build_overlay_line_chart(slide, rect, nasi, ari,
                                     title_x="レカネマブ投与開始からの経過時点",
                                     title_y="MMSE実測値（点）", show_legend=True)


def build_sanko1_charts(slide, rect):
    """群別2パネル：左に訴えあり(n=9)、右に訴えなし(n=20)を別グラフとして並べる。"""
    x, y, w, h = rect
    gap = 180000
    half_w = (w - gap) // 2
    left_rect = (x, y, half_w, h)
    right_rect = (x + half_w + gap, y, half_w, h)

    cd_l = CategoryChartData(); cd_l.categories = TP_LABELS
    for pid in ari:
        vals = tuple(W_MMSE.loc[pid, t] if pd_notna(W_MMSE.loc[pid, t]) else None for t in TP_LABELS)
        cd_l.add_series(pid, vals)
    mean_ari = [mean_ci(W_MMSE.loc[ari, t])[0] for t in TP_LABELS]
    cd_l.add_series(f"群平均 (n={len(ari)})", tuple(round(v, 3) for v in mean_ari))
    xl, yl, wl, hl = _rect_to_inches(left_rect)
    gframe_l = slide.shapes.add_chart(XL_CHART_TYPE.LINE, xl, yl, wl, hl, cd_l)
    chart_l = gframe_l.chart
    style_chart(chart_l, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM)
    ser_l = chart_l.plots[0].series
    for i in range(len(ari)):
        style_individual_series(ser_l[i], RED, width_pt=1.2, alpha_pct=55)
    style_mean_series(ser_l[len(ari)], RED, width_pt=3.0, marker_size=8)
    hide_legend_entries(chart_l, list(range(len(ari))))
    style_axis(chart_l.value_axis, title="MMSE実測値（点）", min_=14, max_=30, major_unit=2)
    style_axis(chart_l.category_axis, title=f"改善訴えあり（n={len(ari)}）", grid=False)

    cd_r = CategoryChartData(); cd_r.categories = TP_LABELS
    for pid in nasi:
        vals = tuple(W_MMSE.loc[pid, t] if pd_notna(W_MMSE.loc[pid, t]) else None for t in TP_LABELS)
        cd_r.add_series(pid, vals)
    mean_nasi = [mean_ci(W_MMSE.loc[nasi, t])[0] for t in TP_LABELS]
    cd_r.add_series(f"群平均 (n={len(nasi)})", tuple(round(v, 3) for v in mean_nasi))
    xr, yr, wr, hr = _rect_to_inches(right_rect)
    gframe_r = slide.shapes.add_chart(XL_CHART_TYPE.LINE, xr, yr, wr, hr, cd_r)
    chart_r = gframe_r.chart
    style_chart(chart_r, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM)
    ser_r = chart_r.plots[0].series
    for i in range(len(nasi)):
        style_individual_series(ser_r[i], BLUE, width_pt=1.0, alpha_pct=42)
    style_mean_series(ser_r[len(nasi)], BLUE, width_pt=3.0, marker_size=8)
    hide_legend_entries(chart_r, list(range(len(nasi))))
    style_axis(chart_r.value_axis, min_=14, max_=30, major_unit=2, grid=True)
    style_axis(chart_r.category_axis, title=f"改善訴えなし（n={len(nasi)}）", grid=False)
    return chart_l, chart_r


# ============================================================
# 結果4：MMSE下位項目パネル（11個の小さいネイティブグラフを敷き詰める）
# ============================================================

def build_kekka4_panel(slide, rect):
    x0, y0, w0, h0 = rect
    ncols, nrows = 4, 3
    cell_w = w0 // ncols
    cell_h = h0 // nrows
    charts = []
    for k, it in enumerate(MMSE_SUBITEMS):
        r, c = divmod(k, ncols)
        cx, cy = x0 + c * cell_w, y0 + r * cell_h
        Wi = wide_scores(mmse, it, IDS)
        cd = CategoryChartData(); cd.categories = ["0", "6", "12", "18"]
        ari_ms = [mean_ci(Wi.loc[ari, t]) for t in TP_LABELS]
        nasi_ms = [mean_ci(Wi.loc[nasi, t]) for t in TP_LABELS]
        cd.add_series("改善訴えあり", tuple(round(a[0], 3) for a in ari_ms))
        cd.add_series("改善訴えなし", tuple(round(a[0], 3) for a in nasi_ms))
        gframe = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS,
                                        Emu(cx + 30000), Emu(cy + 30000),
                                        Emu(cell_w - 60000), Emu(cell_h - 60000), cd)
        chart = gframe.chart
        style_chart(chart, legend=False, font_size=8)
        chart.has_title = True
        chart.chart_title.text_frame.text = f"{it}（{MMSE_SUB_MAX[it]}点満点）"
        for p in chart.chart_title.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(9); run.font.bold = False; run.font.name = "Arial"
        ser = chart.plots[0].series
        style_mean_series(ser[0], RED, width_pt=1.6, marker_size=5)
        style_mean_series(ser[1], BLUE, width_pt=1.6, marker_size=5)
        ari_h = [a[1] if not np.isnan(a[1]) else 0 for a in ari_ms]
        nasi_h = [a[1] if not np.isnan(a[1]) else 0 for a in nasi_ms]
        add_error_bars(ser[0], ari_h, ari_h, color=RED, width_pt=0.6)
        add_error_bars(ser[1], nasi_h, nasi_h, color=BLUE, width_pt=0.6)

        # 縦軸：0点を原点（横軸との交差点）とし、上限を満点、1点刻みで整数目盛りを振る
        style_axis(chart.value_axis, min_=0, max_=MMSE_SUB_MAX[it], major_unit=1, tick_size=7.5)
        style_axis(chart.category_axis, grid=False, tick_size=7.5)
        charts.append(chart)
    return charts


# ============================================================
# 参考2：左＝18か月ΔMMSEの分布（中央値±IQR＋個別点で箱ひげの代替）
#         右＝ベースラインMMSEとの相関（回帰直線つき散布図）
# ============================================================

def build_sanko2_charts(slide, rect):
    x0, y0, w0, h0 = rect
    gap = 220000
    left_w = int(w0 * 0.42)
    right_w = w0 - left_w - gap
    left_rect = (x0, y0, left_w, h0)
    right_rect = (x0 + left_w + gap, y0, right_w, h0)
    ANN = -1.01

    # ---- 左：中央値±IQR（箱ひげの代替）＋ジッター付き個別点 ----
    d_ari = D_MMSE.loc[ari, "18か月"].astype(float).dropna()
    d_nasi = D_MMSE.loc[nasi, "18か月"].astype(float).dropna()
    q1a, meda, q3a = np.percentile(d_ari, [25, 50, 75])
    q1n, medn, q3n = np.percentile(d_nasi, [25, 50, 75])

    # 点数の多い順に系列を追加する（LibreOfficeのXY散布図で、先に追加した系列の
    # 点数が後の系列より少ないと描画されなくなる表示上の癖を避けるため）
    xd = XyChartData()
    s_nasi_pts = xd.add_series("改善訴えなし 個別症例")
    for v in d_nasi:
        s_nasi_pts.add_data_point(round(2 + rng.uniform(-0.12, 0.12), 3), round(float(v), 3))
    s_ari_pts = xd.add_series("改善訴えあり 個別症例")
    for v in d_ari:
        s_ari_pts.add_data_point(round(1 + rng.uniform(-0.12, 0.12), 3), round(float(v), 3))
    s_ari_med = xd.add_series("改善訴えあり 中央値(IQR)")
    s_ari_med.add_data_point(1, round(float(meda), 3))
    s_nasi_med = xd.add_series("改善訴えなし 中央値(IQR)")
    s_nasi_med.add_data_point(2, round(float(medn), 3))
    s_ref_top = xd.add_series("参照帯上限")
    s_ref_bot = xd.add_series("参照帯下限")
    band = ANN * 1.5
    for xx in (0.2, 2.8):  # 横軸の整数目盛り範囲（0〜3）に合わせて全幅に敷く
        s_ref_top.add_data_point(xx, round(band + 0.35, 3))
        s_ref_bot.add_data_point(xx, round(band - 0.35, 3))

    xl, yl, wl, hl = _rect_to_inches(left_rect)
    gframe_l = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, xl, yl, wl, hl, xd)
    chart_l = gframe_l.chart
    style_chart(chart_l, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM, legend_size=9.5)
    ser = chart_l.plots[0].series
    # ser[0]=なし個別 ser[1]=あり個別 ser[2]=あり中央値 ser[3]=なし中央値 ser[4]=上限 ser[5]=下限
    style_scatter_points_only(ser[0], BLUE, size=6, alpha_pct=30)
    style_scatter_points_only(ser[1], RED, size=6, alpha_pct=30)
    for s_, color in [(ser[2], RED), (ser[3], BLUE)]:
        s_.format.line.fill.background()
        s_.marker.style = XL_MARKER_STYLE.DIAMOND
        s_.marker.size = 12
        s_.marker.format.fill.solid()
        s_.marker.format.fill.fore_color.rgb = RGBColor.from_string(color)
        s_.marker.format.line.color.rgb = RGBColor.from_string("FFFFFF")
        s_.marker.format.line.width = Pt(1.2)
    add_error_bars(ser[2], [q3a - meda], [meda - q1a], color=RED, width_pt=1.4)
    add_error_bars(ser[3], [q3n - medn], [medn - q1n], color=BLUE, width_pt=1.4)
    style_ref_line(ser[4]); style_ref_line(ser[5])
    hide_legend_entries(chart_l, [4, 5])
    # 縦軸：結果2と同じくゼロを中心に整数のみ（実データは-9〜+5）
    style_axis(chart_l.value_axis, title="18か月時点の Δ MMSE（点）", min_=-10, max_=10, major_unit=2)
    style_axis(chart_l.category_axis,
              title="1 = 改善訴えあり(n=9)　　2 = 改善訴えなし(n=20)",
              min_=0, max_=3, major_unit=1, grid=False)

    # ---- 右：ベースラインMMSEとの相関＋回帰直線 ----
    # ここも点数の多い順（なし20例 → あり9例 → 回帰直線・Δ=0）に系列を追加する
    base = W_MMSE["0か月"].astype(float)
    xd2 = XyChartData()
    s_nasi2 = xd2.add_series(f"改善訴えなし (n={len(nasi)})")
    for pid in nasi:
        s_nasi2.add_data_point(round(float(base.loc[pid]), 2), round(float(D_MMSE.loc[pid, "18か月"]), 2))
    s_ari2 = xd2.add_series(f"改善訴えあり (n={len(ari)})")
    for pid in ari:
        s_ari2.add_data_point(round(float(base.loc[pid]), 2), round(float(D_MMSE.loc[pid, "18か月"]), 2))

    b_all = base.loc[IDS].astype(float).values
    d_all = D_MMSE.loc[IDS, "18か月"].astype(float).values
    slope, intercept = np.polyfit(b_all, d_all, 1)
    r, pval = stats.pearsonr(b_all, d_all)
    xmin, xmax = 18, 30  # 横軸の整数目盛り範囲（18〜30）と一致させる
    s_reg = xd2.add_series(f"回帰直線（全29例, r={r:.2f}, p={pval:.3f}）")
    s_reg.add_data_point(round(xmin, 2), round(slope * xmin + intercept, 3))
    s_reg.add_data_point(round(xmax, 2), round(slope * xmax + intercept, 3))
    s_zero = xd2.add_series("Δ=0")
    s_zero.add_data_point(round(xmin, 2), 0); s_zero.add_data_point(round(xmax, 2), 0)

    xr, yr, wr, hr = _rect_to_inches(right_rect)
    gframe_r = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, xr, yr, wr, hr, xd2)
    chart_r = gframe_r.chart
    style_chart(chart_r, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM, legend_size=9.5)
    ser2 = chart_r.plots[0].series
    # ser2[0]=なし ser2[1]=あり ser2[2]=回帰直線 ser2[3]=Δ0
    style_scatter_points_only(ser2[0], BLUE, size=6, alpha_pct=15)
    style_scatter_points_only(ser2[1], RED, size=6, alpha_pct=15)
    style_ref_line(ser2[2], color="404040", width_pt=1.6)
    style_ref_line(ser2[3], color=GREY, width_pt=1.0)
    hide_legend_entries(chart_r, [3])
    style_axis(chart_r.value_axis, title="18か月時点の Δ MMSE（点）", min_=-10, max_=10, major_unit=2)
    style_axis(chart_r.category_axis, title="ベースラインMMSE（点）", min_=18, max_=30, major_unit=2)

    return chart_l, chart_r, (r, pval, slope)
