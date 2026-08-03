# -*- coding: utf-8 -*-
"""ネイティブPowerPointチャート（右クリック→「データの編集」が可能な本物のグラフ
オブジェクト）を組み立てるための共通部品。画像の貼り付けは一切行わない。"""
import numpy as np
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

RED = "C00000"
BLUE = "2E75B6"
GREY = "888888"
GRID = "E1E0D9"
REFLINE = "595959"
TEXT = "000000"


def rgb(hexstr):
    return RGBColor.from_string(hexstr)


# ------------------------------------------------------------------
# 低レベルXMLヘルパー（結果5の既存ネイティブグラフのerrBars構造を踏襲）
# ------------------------------------------------------------------

def add_error_bars(series, plus_vals, minus_vals, color=REFLINE, width_pt=0.75):
    """系列にY方向のカスタム誤差棒を追加する（結果5の既存グラフと同じ書式）。"""
    ser_elem = series._element
    w = int(width_pt * 12700)
    plus_pts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(plus_vals))
    minus_pts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(minus_vals))
    xml = (f'<c:errBars xmlns:c="{C_NS}" xmlns:a="{A_NS}">'
           f'<c:errDir val="y"/><c:errBarType val="both"/><c:errValType val="cust"/><c:noEndCap val="0"/>'
           f'<c:plus><c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="{len(plus_vals)}"/>{plus_pts}</c:numLit></c:plus>'
           f'<c:minus><c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="{len(minus_vals)}"/>{minus_pts}</c:numLit></c:minus>'
           f'<c:spPr><a:ln w="{w}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln></c:spPr>'
           f'</c:errBars>')
    el = parse_xml(xml)
    for tag in (qn("c:cat"), qn("c:xVal")):
        found = ser_elem.find(tag)
        if found is not None:
            found.addprevious(el)
            return
    ser_elem.append(el)


def set_alpha(fill_format, pct):
    """塗りつぶし色に透過度を設定する（pct=0〜100、値が大きいほど透明）。"""
    fill_format.solid()
    clr_elem = fill_format.fore_color._xFill.find(qn("a:srgbClr"))
    if clr_elem is None:
        return
    for ch in list(clr_elem):
        clr_elem.remove(ch)
    alpha = clr_elem.makeelement(qn("a:alpha"), {"val": str(int((100 - pct) * 1000))})
    clr_elem.append(alpha)


def hide_legend_entries(chart, indices):
    """凡例から指定した系列（0始まりのインデックス）を非表示にする。"""
    if not indices:
        return
    chart.has_legend = True
    legend_el = chart._chartSpace.find(f".//{{{C_NS}}}legend")
    legend_pos = legend_el.find(f"{{{C_NS}}}legendPos")
    anchor = legend_pos if legend_pos is not None else legend_el
    for i in sorted(indices):
        xml = f'<c:legendEntry xmlns:c="{C_NS}"><c:idx val="{i}"/><c:delete val="1"/></c:legendEntry>'
        anchor.addnext(parse_xml(xml))


# ------------------------------------------------------------------
# 見た目の統一（結果5の既存グラフの配色・フォントに合わせる）
# ------------------------------------------------------------------

def style_chart(chart, font_size=12, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM,
                legend_size=11):
    chart.font.name = "Arial"
    chart.font.size = Pt(font_size)
    chart.font.color.rgb = rgb(TEXT)
    chart.has_title = False
    if legend:
        chart.has_legend = True
        chart.legend.position = legend_pos
        chart.legend.include_in_layout = False
        chart.legend.font.name = "Arial"
        chart.legend.font.size = Pt(legend_size)
        chart.legend.font.color.rgb = rgb(TEXT)
    else:
        chart.has_legend = False


def style_axis(axis, title=None, title_size=12, min_=None, max_=None, major_unit=None,
               grid=True, tick_size=10.5, num_format=None):
    axis.format.line.color.rgb = rgb(GREY)
    axis.format.line.width = Pt(1)
    axis.tick_labels.font.name = "Arial"
    axis.tick_labels.font.size = Pt(tick_size)
    axis.tick_labels.font.color.rgb = rgb(TEXT)
    if num_format:
        axis.tick_labels.number_format = num_format
        axis.tick_labels.number_format_is_linked = False
    if grid:
        axis.has_major_gridlines = True
        gl = axis.major_gridlines
        gl.format.line.color.rgb = rgb(GRID)
        gl.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        gl.format.line.width = Pt(0.75)
    else:
        axis.has_major_gridlines = False
    if min_ is not None:
        axis.minimum_scale = min_
    if max_ is not None:
        axis.maximum_scale = max_
    if major_unit is not None:
        axis.major_unit = major_unit
    if title:
        axis.has_title = True
        tf = axis.axis_title.text_frame
        tf.text = title
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.name = "Arial"; r.font.size = Pt(title_size); r.font.color.rgb = rgb(TEXT)
    else:
        axis.has_title = False


def style_mean_series(series, color, width_pt=2.6, marker_size=8):
    series.format.line.color.rgb = rgb(color)
    series.format.line.width = Pt(width_pt)
    series.marker.style = XL_MARKER_STYLE.CIRCLE
    series.marker.size = marker_size
    series.marker.format.fill.solid(); series.marker.format.fill.fore_color.rgb = rgb(color)
    series.marker.format.line.color.rgb = rgb("FFFFFF")
    series.marker.format.line.width = Pt(1.2)


def style_individual_series(series, color, width_pt=1.1, alpha_pct=45, marker=False):
    series.format.line.color.rgb = rgb(color)
    series.format.line.width = Pt(width_pt)
    set_alpha(series.format.line.fill, alpha_pct)
    if marker:
        series.marker.style = XL_MARKER_STYLE.CIRCLE
        series.marker.size = 4
        series.marker.format.fill.solid(); series.marker.format.fill.fore_color.rgb = rgb(color)
        set_alpha(series.marker.format.fill, alpha_pct)
        series.marker.format.line.fill.background()
    else:
        series.marker.style = XL_MARKER_STYLE.NONE


def style_scatter_points_only(series, color, size=5, alpha_pct=35):
    series.format.line.fill.background()
    series.marker.style = XL_MARKER_STYLE.CIRCLE
    series.marker.size = size
    series.marker.format.fill.solid(); series.marker.format.fill.fore_color.rgb = rgb(color)
    set_alpha(series.marker.format.fill, alpha_pct)
    series.marker.format.line.fill.background()


def style_ref_line(series, color=GREY, width_pt=1.1):
    series.format.line.color.rgb = rgb(color)
    series.format.line.width = Pt(width_pt)
    series.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    series.marker.style = XL_MARKER_STYLE.NONE
