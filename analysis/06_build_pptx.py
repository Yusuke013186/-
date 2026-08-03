# -*- coding: utf-8 -*-
"""フェーズ4：新規スライドを 8月5日に見せるスライド.pptx に統合する。
結果1（スライド1）・結果5（スライド2）は一切改変しない。"""
import copy, pathlib
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from PIL import Image

SRC = "8月5日に見せるスライド.pptx"
DST = "8月5日に見せるスライド_更新版.pptx"
FIGD = pathlib.Path("output/slide_figures")

# 既存スライドから採寸したレイアウト定数（EMU）
TITLE = (457200, 292608, 11247120, 566928)
LINE  = (457200, 1161288, 10817352, 0)
SUB   = (457200, 1243584, 11247120, 246888)
BODY  = (457200, 1600200, 11247120, 4160520)
CAP   = (457200, 6126480, 11247120, 685800)
ACCENT = RGBColor(0x15, 0x60, 0x82)
GREY   = RGBColor(0x66, 0x66, 0x66)
DARK   = RGBColor(0x1A, 0x1A, 0x1A)
BLACK  = RGBColor(0x00, 0x00, 0x00)
FONT   = "Arial"


def _font(run, size, color, bold=False):
    run.font.size = Pt(size); run.font.bold = bold
    run.font.color.rgb = color; run.font.name = FONT
    # 日本語（East Asian）フォントも Arial に揃える
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.makeelement(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}" + tag.split(":")[1], {})
        el.set("typeface", FONT); rPr.append(el)


def add_textbox(slide, rect, lines, size, color, spacing=1.05):
    """lines: [(text, size, bold), ...] または [str, ...]"""
    tb = slide.shapes.add_textbox(*(Emu(v) for v in rect))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = spacing
        parts = ln if isinstance(ln, list) else [(ln, size, False)]
        for txt, sz, bd in parts:
            _font(p.add_run(), sz, color, bd)
            p.runs[-1].text = txt
    return tb


def add_slide(prs, num_label, title_rest, subtitle, image, captions):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    # タイトル（「結果N」40pt ＋ 以降 32pt、結果1・結果5と同一書式）
    add_textbox(slide, TITLE, [[(num_label, 40, False), (title_rest, 30, False)]], 40, BLACK)
    # 見出し下の水平線
    ln = slide.shapes.add_connector(1, Emu(LINE[0]), Emu(LINE[1]),
                                    Emu(LINE[0] + LINE[2]), Emu(LINE[1]))
    ln.line.color.rgb = ACCENT; ln.line.width = Emu(22225)
    # サブタイトル（このスライドが存在する理由を一文で明記）
    add_textbox(slide, SUB, [subtitle], 13, GREY)
    # 図（縦横比を保ってコンテンツ枠に内接させ、水平中央に配置）
    if image is not None:
        bx, by, bw, bh = BODY
        iw, ih = Image.open(image).size
        sc = min(bw / iw, bh / ih)
        w, h = int(iw * sc), int(ih * sc)
        slide.shapes.add_picture(str(image), Emu(bx + (bw - w) // 2), Emu(by + (bh - h) // 2),
                                 Emu(w), Emu(h))
    # 図の注釈
    if captions:
        add_textbox(slide, CAP, captions, 11, DARK)
    return slide


NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

NOTES_BODY_XML = """<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <p:nvSpPr><p:cNvPr id="2" name="Notes Placeholder 1"/>
 <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
 <p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>
 <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>"""


def set_notes(slide, text):
    """このファイルのnotesMasterにはプレースホルダ定義がないため、
    notesSlideにbodyプレースホルダを自前で追加してからノートを書き込む。"""
    ns = slide.notes_slide
    if ns.notes_text_frame is None:
        from pptx.oxml import parse_xml
        ns.shapes._spTree.append(parse_xml(NOTES_BODY_XML))
    tf = ns.notes_text_frame
    lines = text.split("\n")
    tf.text = lines[0]
    for ln in lines[1:]:
        tf.add_paragraph().text = ln


prs = Presentation(SRC)
n_orig = len(prs.slides)
assert n_orig == 2, f"元ファイルのスライド数が想定外です: {n_orig}"

# ============================== 結果2（応用Ver） ==============================
s = add_slide(
    prs, "結果2",
    "　改善の訴えをアンカーとしたΔMMSEの推移",
    "この図の役割：主観的な訴えがMMSEの変化量を層別しないことを、先行研究と同じアンカーベースの枠組みで示す。",
    FIGD / "slide_ΔMMSE_アンカー別推移.png",
    ["各時点の値はベースライン（0か月）からのΔMMSEの群平均、エラーバーは95% CI。淡色の点は個別症例（横方向にジッターを付与）。",
     "改善訴えあり群 n=9、改善訴えなし群 n=20（12か月のみ n=19）。18か月時点のΔMMSE：Welchのt検定 p=0.581、Mann-Whitney検定 p=0.200。",
     "灰色帯は年 −1.01 点の低下（Aakre JA, et al. Alzheimers Dement (N Y). 2025）を目安として示した参照帯であり、本研究で閾値判定に用いたものではない。"])
set_notes(s, """【このスライドの存在理由】
Cano S, et al. J Prev Alzheimers Dis 2022 (doi:10.14283/jpad.2022.102) は、全般的印象（＝臨床医の主観的判断）をアンカー、MMSEをターゲット測度としたアンカーベース解析で、MMSEとアンカーの相関が36週より前のどの時点でも不十分であったと報告している。
本スライドはその枠組みを本研究データに当てはめたもので、アンカーを「レカネマブ投与後の症状改善の訴え（あり／記載なし）」に置き換えた追試にあたる。
主観的な訴えというアンカーは、いずれの時点でもΔMMSEを層別しなかった。2群の95%CIは全時点で重なっている。
→ したがって結果5の「有意差なし」は、検出力不足の産物ではなく、先行研究と整合する既知の現象の再現として提示できる。

【想定される質問】
Q: n=9 では検出力がないのでは？
A: そのとおりで、本研究単独では非劣性も同等性も主張できない。ただし主張は「差がないことの証明」ではなく「主観アンカーとMMSEが対応しないという先行知見と矛盾しない」という水準にとどめている。

Q: 参照帯の根拠は？
A: Mayo Clinic Study of Aging の集団ベース解析（Aakre 2025, doi:10.1002/trc2.70160）で、MCI発症をアンカーとしたMMSEの年間変化は −1.01（95%CI −1.12 to −0.91）。あくまで目盛りの目安であり、本研究の判定基準ではない。""")

# ============================== 結果3（個別症例推移） ==============================
s = add_slide(
    prs, "結果3",
    "　個別症例のMMSE推移（29例の重ね合わせ）",
    "この図の役割：群平均が重なっていても個々の軌跡は同一ではないことを示す（結果5への伏線）。",
    FIGD / "slide_個別症例MMSE推移_重ね合わせ.png",
    ["細線は個別症例、太線は群平均。赤＝改善訴えあり（n=9）、青＝改善訴えなし（n=20）。色分けはMMSEの増減とは無関係である。",
     "個人内の変動幅（4時点の最大−最小）の平均は 訴えあり 4.67点／訴えなし 3.05点。18か月時点のΔMMSEの標準偏差は 訴えあり 4.76／訴えなし 2.83。",
     "18か月時点でベースラインより改善／不変／悪化：訴えあり 6／0／3例、訴えなし 7／4／9例。群平均の推移は両群でほぼ重なる（結果5）。"])
set_notes(s, """【このスライドの存在理由】
結果5では2群の平均MMSEがほぼ重なる。しかしそれは「29例が同じように推移した」ことを意味しない。
個別軌跡を重ねると、訴えあり群（赤）のほうが軌跡のばらつきが大きい。個人内変動幅の平均は 4.67点 対 3.05点、18か月ΔMMSEのSDは 4.76 対 2.83 で、いずれも訴えあり群のほうが大きい。
つまり「訴えあり」は平均の水準ではなく、変動の大きさの側に現れている可能性がある。ただしこれは事後的な観察であり、n=9 では分散の差の検定も安定しない。

【この観察の扱い】
探索的所見にとどめる。ばらつきが大きい群では、6か月時点の一時的な上昇（訴えあり群は平均 +1.67点）が「効いている」という実感につながり、それが訴えとして記録された可能性がある——という仮説の提示までが本スライドの射程である。

【注意】
6か月時点で訴えあり群のMMSEが上昇して見えるのは、ベースラインが低い症例を含むこと（平均22.89 対 24.25）とも整合し、平均への回帰の影響を否定できない。因果の向きは本データからは決められない。""")

# ============================== 結果4（下位項目） ==============================
s = add_slide(
    prs, "結果4",
    "　MMSE下位項目別の推移の群間比較",
    "この図の役割：11の下位項目のいずれでも訴えの有無が推移を層別しないことを確認する（探索的解析）。",
    FIGD / "slide_MMSE下位項目パネル.png",
    ["各パネルは下位項目ごとの群平均±95% CI。赤＝改善訴えあり（n=9）、青＝改善訴えなし（n=20）。",
     "18か月時点の変化量を項目ごとにMann-Whitney検定で比較し、Benjamini-Hochberg法でFDR補正した。補正前 p<0.05 は 0/11、補正後 q<0.05 も 0/11。",
     "多重比較を含む探索的（hypothesis-generating）解析であり、確証的解析ではない。1点満点の項目は1例の増減で結果が動くため単独では解釈しない。"])
set_notes(s, """【このスライドの存在理由】
「合計点で差が出ないのは、改善した下位項目と悪化した下位項目が打ち消し合っているからではないか」という当然の反論に、あらかじめ答えておくためのスライド。
結論は、11項目のいずれでも訴えの有無は18か月の変化量を層別しなかった、である。補正前の段階ですでに有意な項目はなく、FDR補正で初めて消えたわけではない点は強調してよい。

【変化量の群間差が大きかった項目】
1位 時間見当識（+0.71点、5点満点、補正前 p=0.212 / q=0.778）
2位 注意計算（+0.66点、5点満点、補正前 p=0.397 / q=0.792）
いずれも訴えあり群のほうが保たれる方向だが、95%CIは大きく重なる。

【既存テーマの「遅延再生」について】
遅延再生の群間差は −0.19点（3点満点）で11項目中4位、補正前 p=0.704。訴えあり群のほうがむしろわずかに低下が大きく、上位2項目には入らない。
つまり本データでは、遅延再生が「訴えあり」を特徴づける項目にはなっていない。

【CDR 6領域】
同様に解析したが、補正前・補正後とも有意な領域はなかった（最小 p=0.598）。CDR-SBのΔ18Mも 訴えあり +1.75 対 訴えなし +1.39、p=0.736。

【注意】
n=9 対 20 の小標本かつ不均衡であり、この解析で「差がない」ことを結論づけることはできない。あくまで結果5を補強する材料である。""")

# ============================== 参考スライド ==============================
s = add_slide(
    prs, "参考1", "　個別症例のMMSE推移（群別表示）",
    "結果3の代替案：群内のばらつきを見やすくした2パネル版。どちらを本番で使うかは要相談。",
    FIGD / "slide_個別症例MMSE推移_群別2パネル.png",
    ["細線は個別症例、太線は群平均。左：改善訴えあり（n=9）、右：改善訴えなし（n=20）。縦軸は両パネルで共通。",
     "重ね合わせ版（結果3）と同一データ。群内のばらつきを見せたい場合はこちら、2群の比較を見せたい場合は重ね合わせ版が適する。"])
set_notes(s, "結果3のスライドに使う図の代替案。指示書タスク②-1(b)に対応。重ね合わせ版(a)と群別2パネル版(b)のどちらをメインにするかは上野先生の判断を仰ぐ。")

s = add_slide(
    prs, "参考2", "　18か月ΔMMSEの分布とベースライン重症度",
    "結果2の補足：群分けよりベースライン重症度のほうがMMSEの推移をよく説明する。",
    FIGD / "slide_18か月ΔMMSE_ドットプロット.png",
    ["左：18か月時点のΔMMSEの分布（箱ひげ＋個別点、点の色はベースラインMMSE）。灰色帯は年 −1.01 点相当の参照帯。",
     "右：ベースラインMMSEと18か月ΔMMSEの関係（29例全体で r = −0.50, p = 0.006）。ベースラインが高い症例ほど18か月での低下が大きい。",
     "ただしΔMMSEはベースラインを含んで計算されるため、この相関には平均への回帰（regression to the mean）が数学的に含まれる。因果的な解釈はできない。"])
set_notes(s, """【このスライドの存在理由】
文献調査の「応用Ver 図の設計仕様」パネルBに対応。個々の点をベースラインMMSEで着色すると、群分け（訴えの有無）よりもベースライン重症度のほうがΔMMSEを説明していることが見える。

【重要な留保】
r = −0.50, p = 0.006 は統計的に有意だが、Δ = 18か月値 − ベースライン値 という定義上、ベースラインとΔは数学的に負に相関する（平均への回帰）。この所見を「重症度が予後を決める」と読むことはできない。
発表で言及する場合は、必ずこの留保を添える。触れないという選択もある。

【参照帯を超えて低下した症例の割合】
訴えあり 2/9 (22.2%)、訴えなし 6/20 (30.0%)、Fisher正確検定 p=1.00。ここでも両群はほぼ同等である。""")

s = add_slide(
    prs, "参考3", "　精神症状項目の測定上の限界（易怒性・意欲低下）",
    "結果1の補足：精神症状フラグが確立された尺度に基づかないことを質疑応答に備えて明示する。",
    None, None)
body_lines = [
    [("本研究の操作的定義", 14, True)],
    [("　易怒性・意欲低下は、NPI-Q等の確立された尺度によらず、診療録記載の有無に基づく二値変数（0/1）として後方視的に定義した。", 13, False)],
    [("", 7, False)],
    [("先行研究の標準的な定義との差", 14, True)],
    [("　NPI（Cummings 1994）、NPI-Q（Kaufer 2000）、AES（Marin／Clarke 2007）、Starkstein Apathy Scale はいずれも、", 13, False)],
    [("　(1) 情報提供者への構造化された聴取、(2) 頻度・重症度の段階評価、(3) 直近1か月などの観察期間の明示、という3要素を備える。", 13, False)],
    [("　本研究の二値フラグはこの3要素をいずれも満たさず、Robertら（2018）のアパシー国際コンセンサス基準の充足も判定できない。", 13, False)],
    [("　したがって本項目は「アパシー」ではなく「意欲低下（診療録記載）」と記述するのが正確である。", 13, False)],
    [("", 7, False)],
    [("方法論上の直接的な根拠", 14, True)],
    [("　Eikelboom WS, et al. Alzheimers Res Ther. 2023;15:94 は、2つのメモリークリニックコホート（n=3001／n=646）で、", 13, False)],
    [("　臨床医が診療録に記載した精神症状と介護者がNPIで報告した症状の一致度が低いことを示している。", 13, False)],
    [("　このため、診療録記載の有無をNPI無関心ドメインの代理指標として扱うことはできない。", 13, False)],
    [("", 7, False)],
    [("本研究に固有の留意点", 14, True)],
    [("　レカネマブ導入後は診察頻度と問診密度が上がるため、記載の有無が「症状の有無」ではなく「聞かれたかどうか」を反映しうる。", 13, False)],
    [("　群分け変数（症状改善の訴え）も記載依存であり、共通の記載バイアスは見かけの関連を生む方向にも消す方向にも働きうる。", 13, False)],
]
add_textbox(s, (457200, 1600200, 11247120, 4600000), body_lines, 13, DARK, spacing=1.25)
set_notes(s, """タスク④に対応。文献調査_意欲低下定義.md の考察を反映した。

【スライドで述べる1〜2文の要約】
本研究の意欲低下は診療録記載の有無に基づく二値変数であり、情報提供者への構造化聴取・頻度／重症度評価・観察期間の明示という、NPIやAESが備える3要素をいずれも満たさない。
さらにEikelboomら（2023）は診療録記載と介護者評価の一致度が低いことを実データで示しており、本項目をNPI無関心ドメインの代理指標として扱うことはできない。

【limitation への転用文案】
1. 意欲低下はNPI-Q等の確立された尺度によらず、診療録記載の有無に基づく二値変数として後方視的に定義した。
2. このため重症度・頻度・持続期間の情報を欠き、Robertら（2018）のアパシー診断基準を満たすか否かは判定できない。
3. 診療録記載は問診の密度や記載者の裁量に依存するため、症状の有無を系統的に反映していない可能性がある。
4. 上記より本項目の結果は探索的であり、先行研究のアパシー有病率（NPIベース）と直接比較することはできない。

【重要：本スライドで決めていないこと】
「易怒性／意欲低下のどちらかを解析から減らすべきか」という論点については、指示書の方針に従い削除は実行していない。確認事項リストに論点として記載した。""")

# ---- スライド順序の並べ替え：結果1 → 結果2/3/4（新規）→ 結果5 → 参考1/2/3 ----
sldIdLst = prs.slides._sldIdLst
ids = list(sldIdLst)                      # [結果1, 結果5, 結果2, 結果3, 結果4, 参考1, 参考2, 参考3]
order = [0, 2, 3, 4, 1, 5, 6, 7]
for i in ids:
    sldIdLst.remove(i)
for k in order:
    sldIdLst.append(ids[k])

prs.save(DST)
print(f"保存: {DST}（{len(prs.slides)} 枚）")
for i, sl in enumerate(Presentation(DST).slides, 1):
    t = [sh.text_frame.text.split("\n")[0] for sh in sl.shapes
         if sh.has_text_frame and sh.text_frame.text.strip()]
    print(f"  {i}: {t[0] if t else '(no title)'}")
