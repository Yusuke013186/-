#!/usr/bin/env python3
"""Build the journal-club (抄読会) PPTX from a JSON content spec.

Usage:
    python build_pptx.py content_spec.json output.pptx

See SKILL.md for the full JSON schema. In short:

{
  "presenter": "堀内裕介",
  "date_label": "●月●日",
  "front_matter": [
    {"type": "title", "image": "extracted/page_1.png"},
    {"type": "visual_abstract", "image": "extracted/page_2.png"}
  ],
  "sections": [
    {"heading": "背景", "slides": [
      {"bullets": [{"level": 1, "text": "..."}, {"level": 2, "text": "..."}], "images": []}
    ]},
    {"heading": "結果", "slides": [
      {"bullets": [{"level": 1, "text": "..."}], "images": ["extracted/figure_1.png"]}
    ]}
  ]
}

All paths in the spec are resolved relative to the current working
directory the script is run from (or pass absolute paths).
"""

import json
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# ---------------------------------------------------------------------------
# Style configuration -- tuned to the spec given without sight of the actual
# reference template (精読の例.pdf was not available when this was written).
# Everything visual lives here; adjust freely once compared against the real
# template instead of restructuring the slide-building code below.
# ---------------------------------------------------------------------------

SLIDE_W_IN = 13.333  # 16:9
SLIDE_H_IN = 7.5

GREEN = RGBColor(0x3B, 0x7D, 0x23)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT_DARK = RGBColor(0x26, 0x26, 0x26)

FONT_EA = "Meiryo"  # East-Asian (Japanese) glyphs; bold runs use this + bold=True ("Meiryo-Bold")
FONT_LATIN = "Calibri"  # Latin / numeral glyphs

MARGIN_IN = 0.55

HEADER_H_IN = 0.85
HEADER_FONT_PT = 26
HEADING_LABELS = {"背景", "方法", "結果", "考察", "Limitation"}

TITLE_OVERLAY_H_IN = 0.55
TITLE_OVERLAY_FONT_PT = 16

L1_FONT_PT = 20
L2_FONT_PT = 16
L1_MARL_IN = 0.35
L1_INDENT_IN = 0.35
L2_MARL_IN = 0.75
L2_INDENT_IN = 0.3
LINE_SPACING = 1.15
PARA_SPACE_AFTER_PT = 10

TEXT_IMAGE_SPLIT = 0.35  # fraction of body height given to bullets when a slide has both bullets and images
IMAGE_GAP_IN = 0.3

# ---------------------------------------------------------------------------
# Low-level OOXML helpers
# ---------------------------------------------------------------------------


def set_run_font(run, size_pt=None, bold=None, color=None, latin=FONT_LATIN, ea=FONT_EA):
    """Set size/bold/color via the public API, then split Latin vs East-Asian
    typeface so Japanese text renders in `ea` and Latin/numerals in `latin`
    within the same run (the public python-pptx API only sets one font name
    for everything, which is wrong for mixed Japanese/English text)."""
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag, typeface in (("a:latin", latin), ("a:ea", ea), ("a:cs", latin)):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", typeface)


def set_bullet(paragraph, char, indent_in, marl_in, font_typeface=FONT_EA):
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("marL", str(Inches(marl_in)))
    pPr.set("indent", str(-Inches(indent_in)))
    buFont = pPr.makeelement(qn("a:buFont"), {"typeface": font_typeface})
    buChar = pPr.makeelement(qn("a:buChar"), {"char": char})
    pPr.append(buFont)
    pPr.append(buChar)


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------


def add_rect(slide, x, y, w, h, fill_color):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def add_textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    return box, tf


def fit_contain(content_w, content_h, box_w, box_h):
    """Largest (w, h) that fits content_w x content_h inside box_w x box_h preserving aspect ratio."""
    scale = min(box_w / content_w, box_h / content_h)
    return content_w * scale, content_h * scale


def image_pixel_size(path):
    with Image.open(path) as im:
        return im.size


# ---------------------------------------------------------------------------
# Slide content builders
# ---------------------------------------------------------------------------


def set_white_background(slide):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = WHITE


def add_bullets(tf, bullets):
    first = True
    for b in bullets:
        level = b.get("level", 1)
        text = b["text"]
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(PARA_SPACE_AFTER_PT)
        p.line_spacing = LINE_SPACING
        run = p.add_run()
        run.text = text
        if level == 1:
            set_bullet(p, "■", L1_INDENT_IN, L1_MARL_IN)
            set_run_font(run, size_pt=L1_FONT_PT, bold=True, color=TEXT_DARK)
        else:
            set_bullet(p, "・", L2_INDENT_IN, L2_MARL_IN)
            set_run_font(run, size_pt=L2_FONT_PT, bold=False, color=TEXT_DARK)


def add_image_grid(slide, images, x, y, w, h):
    n = len(images)
    if n == 0:
        return
    cols = 1 if n == 1 else 2
    rows = -(-n // cols)  # ceil division
    cell_w = (w - IMAGE_GAP_IN * (cols - 1)) / cols
    cell_h = (h - IMAGE_GAP_IN * (rows - 1)) / rows
    for i, img_path in enumerate(images):
        row, col = divmod(i, cols)
        cell_x = x + col * (cell_w + IMAGE_GAP_IN)
        cell_y = y + row * (cell_h + IMAGE_GAP_IN)
        iw, ih = image_pixel_size(img_path)
        draw_w, draw_h = fit_contain(iw, ih, cell_w, cell_h)
        draw_x = cell_x + (cell_w - draw_w) / 2
        draw_y = cell_y + (cell_h - draw_h) / 2
        slide.shapes.add_picture(str(img_path), Inches(draw_x), Inches(draw_y), Inches(draw_w), Inches(draw_h))


def add_header(slide, heading_text):
    add_rect(slide, 0, 0, SLIDE_W_IN, HEADER_H_IN, GREEN)
    _, tf = add_textbox(slide, MARGIN_IN, 0, SLIDE_W_IN - 2 * MARGIN_IN, HEADER_H_IN, anchor=MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = heading_text
    set_run_font(run, size_pt=HEADER_FONT_PT, bold=True, color=WHITE)


def add_content_slide(prs, heading, bullets, images):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    set_white_background(slide)
    add_header(slide, heading)

    body_x = MARGIN_IN
    body_y = HEADER_H_IN + 0.25
    body_w = SLIDE_W_IN - 2 * MARGIN_IN
    body_h = SLIDE_H_IN - body_y - MARGIN_IN

    if bullets and images:
        text_h = body_h * TEXT_IMAGE_SPLIT
        _, tf = add_textbox(slide, body_x, body_y, body_w, text_h)
        add_bullets(tf, bullets)
        img_y = body_y + text_h + 0.2
        img_h = body_h - text_h - 0.2
        add_image_grid(slide, images, body_x, img_y, body_w, img_h)
    elif images:
        add_image_grid(slide, images, body_x, body_y, body_w, body_h)
    else:
        _, tf = add_textbox(slide, body_x, body_y, body_w, body_h)
        add_bullets(tf, bullets)

    return slide


def add_front_matter_slide(prs, image_path, overlay_text=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    set_white_background(slide)

    iw, ih = image_pixel_size(image_path)
    draw_w, draw_h = fit_contain(iw, ih, SLIDE_W_IN, SLIDE_H_IN)
    draw_x = (SLIDE_W_IN - draw_w) / 2
    draw_y = (SLIDE_H_IN - draw_h) / 2
    slide.shapes.add_picture(str(image_path), Inches(draw_x), Inches(draw_y), Inches(draw_w), Inches(draw_h))

    if overlay_text:
        add_rect(slide, 0, SLIDE_H_IN - TITLE_OVERLAY_H_IN, SLIDE_W_IN, TITLE_OVERLAY_H_IN, GREEN)
        _, tf = add_textbox(
            slide, 0, SLIDE_H_IN - TITLE_OVERLAY_H_IN, SLIDE_W_IN, TITLE_OVERLAY_H_IN, anchor=MSO_ANCHOR.MIDDLE
        )
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = overlay_text
        set_run_font(run, size_pt=TITLE_OVERLAY_FONT_PT, bold=True, color=WHITE)

    return slide


# ---------------------------------------------------------------------------
# Spec assembly
# ---------------------------------------------------------------------------


def resolve_path(base_dir, path):
    p = Path(path)
    return p if p.is_absolute() else (base_dir / p)


def build(spec, output_path, base_dir):
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)

    overlay_text = f"Journal Club {spec.get('date_label', '●月●日')} {spec.get('presenter', '')}".strip()

    for item in spec.get("front_matter", []):
        img = resolve_path(base_dir, item["image"])
        if not img.exists():
            raise FileNotFoundError(f"front_matter image not found: {img}")
        text = overlay_text if item.get("type") == "title" else None
        add_front_matter_slide(prs, img, overlay_text=text)

    for section in spec.get("sections", []):
        heading = section["heading"]
        for i, slide_spec in enumerate(section.get("slides", [])):
            images = []
            for img in slide_spec.get("images", []):
                resolved = resolve_path(base_dir, img)
                if not resolved.exists():
                    raise FileNotFoundError(f"image not found: {resolved} (section '{heading}', slide {i + 1})")
                images.append(resolved)
            add_content_slide(prs, heading, slide_spec.get("bullets", []), images)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)
    print(f"Saved {output_path} ({len(prs.slides)} slides)")


def main():
    if len(sys.argv) != 3:
        print("Usage: python build_pptx.py <content_spec.json> <output.pptx>", file=sys.stderr)
        sys.exit(1)

    spec_path, output_path = sys.argv[1], sys.argv[2]
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to read {spec_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        build(spec, output_path, base_dir=Path(spec_path).resolve().parent)
    except (FileNotFoundError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
