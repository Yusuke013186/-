#!/usr/bin/env python3
"""Build the journal-club (抄読会) PPTX from a JSON content spec.

Usage:
    python build_pptx.py content_spec.json output.pptx

Full JSON schema
-----------------
{
  "presenter": "堀内裕介",
  "date_label": "12月10日",
  "front_matter": [
    {"type": "title", "image": "extracted/page_1.png"},
    {"type": "visual_abstract", "image": "extracted/page_2.png"}
  ],
  "sections": [
    {
      "heading": "背景",
      "slides": [
        {
          "subtitle": "シロスタゾールとCAS後の再狭窄",
          "subtitle_style": "bold",
          "bullets": [
            {"level": 1, "text": "...", "citation": "Yamagami et al, ..."},
            {"level": 2, "text": "..."},
            {"level": 1, "text": "→ ...", "marker": false}
          ],
          "box": "CAS後の再狭窄を予防する薬物療法については一定の見解を得られていない.",
          "images": [
            {"path": "extracted/figure_1.png", "caption": "optional small caption"}
          ],
          "columns": [
            {"heading": "...", "image": "...", "bullets": [...]},
            {"heading": "...", "bullets": [...]}
          ]
        }
      ]
    }
  ]
}

Notes:
- `bullets` levels: 0 = flush, no marker, larger plain text (subtitle-like
  inline use); 1 = "■"; 2 = "・"; 3 = "・" at a deeper indent. Set
  `"marker": false` on any item to suppress its glyph while keeping the
  level's indent (used for "→ ..." conclusion lines or flush paragraphs).
- Inline markup inside any `text` / `box` / `subtitle` string:
  `**bold**`, `__underline__`, `++red++`.
- A slide needs at least one of `bullets`, `box`, `images`, `columns`.
- If both `bullets` and `columns` are given, `bullets` renders as a short
  intro line above the column row. If both `bullets` and `images` are given
  (no `columns`), bullets render above the image grid. For side-by-side
  image+text (or text+text) pairs, use `columns` instead -- it is the
  general mechanism for left/right layouts.
- `images` entries may be a plain path string or `{"path", "caption"}`.
- All image paths are resolved relative to the JSON file's own directory
  (or pass absolute paths).

See SKILL.md for the authoring workflow this spec is meant to be produced by.
"""

import json
import re
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# ---------------------------------------------------------------------------
# Style configuration -- measured against 精読の例.pdf (the reference deck).
# Everything visual lives here; tune freely without touching the layout code
# below.
# ---------------------------------------------------------------------------

SLIDE_W_IN = 13.333  # 16:9
SLIDE_H_IN = 7.5

GREEN = RGBColor(0x3B, 0x7D, 0x23)  # measured exact match to the header band
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x00, 0x00, 0x00)
TEXT_DARK = RGBColor(0x1A, 0x1A, 0x1A)
TEXT_GRAY = RGBColor(0x55, 0x55, 0x55)
RED = RGBColor(0xFF, 0x00, 0x00)  # measured exact match to the emphasis red

FONT_EA = "Meiryo"  # East-Asian (Japanese) glyphs, regular weight
FONT_EA_BOLD = "Meiryo-Bold"  # East-Asian glyphs, bold weight (named typeface, not synthetic bold)
FONT_LATIN = "Calibri"  # Latin / numeral glyphs, both weights

MARGIN_IN = 0.6

HEADER_H_IN = 0.75
HEADER_FONT_PT = 28
HEADER_OUTLINE_PT = 1.25
HEADING_LABELS = ("背景", "方法", "結果", "考察", "Limitation")

# Title-slide overlay: plain text directly on the pasted page image -- the
# reference deck has no bar/box behind it, just dark text with a bottom
# margin sitting in whatever blank space the title page leaves.
TITLE_OVERLAY_FONT_PT = 26
TITLE_OVERLAY_H_IN = 0.7
TITLE_OVERLAY_BOTTOM_MARGIN_IN = 0.5

SUBTITLE_FONT_PT = 22
SUBTITLE_H_IN = 0.5

L0_FONT_PT = 20
L1_FONT_PT = 20
L2_FONT_PT = 18
L3_FONT_PT = 16
CITATION_FONT_PT = 13

L_INDENT_IN = 0.32  # hanging indent (bullet glyph to text gap), same at every level
L_MARL_IN = {0: 0.0, 1: 0.32, 2: 0.72, 3: 1.12}
L_BULLET_CHAR = {1: "■", 2: "・", 3: "・"}

LINE_SPACING = 1.15
PARA_SPACE_AFTER_PT = 10
CITATION_SPACE_AFTER_PT = 12

BOX_BORDER_PT = 1.0
BOX_PAD_IN = 0.18
BOX_FONT_PT = 18
BOX_LINE_H_IN = 0.4

COLUMN_GAP_IN = 0.35
COLUMN_HEADING_FONT_PT = 18
COLUMN_HEADING_H_IN = 0.4
IMAGE_CAPTION_FONT_PT = 12
IMAGE_CAPTION_H_IN = 0.3

TEXT_IMAGE_GAP_IN = 0.25
TEXT_IMAGE_SPLIT = 0.4  # fraction of body height given to bullets when a slide mixes bullets (no columns) + images
IMAGE_GAP_IN = 0.3

# ---------------------------------------------------------------------------
# Inline markup: **bold** / __underline__ / ++red++
# ---------------------------------------------------------------------------

_INLINE_RE = re.compile(r"(\*\*.+?\*\*|__.+?__|\+\+.+?\+\+)")


def parse_inline(text):
    """Split text into (text, overrides) fragments per the inline markup."""
    fragments = []
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            fragments.append((part[2:-2], {"bold": True}))
        elif part.startswith("__") and part.endswith("__"):
            fragments.append((part[2:-2], {"underline": True}))
        elif part.startswith("++") and part.endswith("++"):
            fragments.append((part[2:-2], {"color": RED}))
        else:
            fragments.append((part, {}))
    return fragments


# ---------------------------------------------------------------------------
# Low-level OOXML helpers
# ---------------------------------------------------------------------------


def set_run_font(run, size_pt=None, bold=None, italic=None, underline=None, color=None, latin=FONT_LATIN, ea=None):
    """Set size/weight/color via the public API, then split Latin vs.
    East-Asian typeface so Japanese text renders in `ea` and Latin/numerals
    in `latin` within the same run (the public python-pptx API only sets one
    font name for everything, which is wrong for mixed Japanese/English
    text). Bold runs default to the FONT_EA_BOLD named typeface rather than
    synthetic bold, per the house style."""
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if underline is not None:
        run.font.underline = underline
    if color is not None:
        run.font.color.rgb = color
    if ea is None:
        ea = FONT_EA_BOLD if bold else FONT_EA
    rPr = run._r.get_or_add_rPr()
    for tag, typeface in (("a:latin", latin), ("a:ea", ea), ("a:cs", latin)):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", typeface)


def add_text_outline(run, color=BLACK, width_pt=HEADER_OUTLINE_PT):
    """Add a WordArt-style outline stroke to a run (used for the green
    header captions, which are white-fill-on-black-outline in the
    reference deck). Must run after the run's fill color is already set
    (e.g. via set_run_font), since <a:ln> must precede <a:solidFill> in
    OOXML's CT_TextCharacterProperties sequence -- inserting at index 0
    here puts it there regardless of call order."""
    rPr = run._r.get_or_add_rPr()
    ln = rPr.makeelement(qn("a:ln"), {"w": str(Pt(width_pt))})
    fill = ln.makeelement(qn("a:solidFill"), {})
    srgb = fill.makeelement(qn("a:srgbClr"), {"val": str(color)})
    fill.append(srgb)
    ln.append(fill)
    rPr.insert(0, ln)


def set_bullet(paragraph, level):
    pPr = paragraph._p.get_or_add_pPr()
    marl = L_MARL_IN.get(level, L_MARL_IN[3])
    pPr.set("marL", str(Inches(marl)))
    char = L_BULLET_CHAR.get(level)
    if level == 0 or char is None:
        pPr.set("indent", "0")
        pPr.append(pPr.makeelement(qn("a:buNone"), {}))
        return
    pPr.set("indent", str(-Inches(L_INDENT_IN)))
    buFont = pPr.makeelement(qn("a:buFont"), {"typeface": FONT_EA})
    buChar = pPr.makeelement(qn("a:buChar"), {"char": char})
    pPr.append(buFont)
    pPr.append(buChar)


def set_no_bullet_but_indent(paragraph, level):
    """Same indent as `level` but no glyph -- for flush paragraphs / "→"
    conclusion lines that should line up with a level without a marker."""
    pPr = paragraph._p.get_or_add_pPr()
    marl = L_MARL_IN.get(level, L_MARL_IN[3])
    pPr.set("marL", str(Inches(marl)))
    pPr.set("indent", "0")
    pPr.append(pPr.makeelement(qn("a:buNone"), {}))


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------


def add_rect(slide, x, y, w, h, fill_color=None, line_color=None, line_pt=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill_color is not None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
    else:
        shape.fill.background()
    if line_color is not None:
        shape.line.color.rgb = line_color
        shape.line.width = Pt(line_pt or 1.0)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def add_textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP, autofit=True):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    if autofit:
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    return box, tf


def fit_contain(content_w, content_h, box_w, box_h):
    """Largest (w, h) that fits content_w x content_h inside box_w x box_h preserving aspect ratio."""
    scale = min(box_w / content_w, box_h / content_h)
    return content_w * scale, content_h * scale


def image_pixel_size(path):
    with Image.open(path) as im:
        return im.size


def add_picture_contain(slide, path, x, y, w, h):
    iw, ih = image_pixel_size(path)
    draw_w, draw_h = fit_contain(iw, ih, w, h)
    draw_x = x + (w - draw_w) / 2
    draw_y = y + (h - draw_h) / 2
    return slide.shapes.add_picture(str(path), Inches(draw_x), Inches(draw_y), Inches(draw_w), Inches(draw_h))


# ---------------------------------------------------------------------------
# Text-content builders
# ---------------------------------------------------------------------------


def set_white_background(slide):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = WHITE


def add_run_with_markup(p, text, size_pt, base_bold, base_color):
    for frag_text, overrides in parse_inline(text):
        run = p.add_run()
        run.text = frag_text
        set_run_font(
            run,
            size_pt=size_pt,
            bold=overrides.get("bold", base_bold),
            underline=overrides.get("underline", False),
            color=overrides.get("color", base_color),
        )


def font_pt_for_level(level):
    return {0: L0_FONT_PT, 1: L1_FONT_PT, 2: L2_FONT_PT}.get(level, L3_FONT_PT)


def add_bullets(tf, bullets, first=True):
    for b in bullets:
        level = b.get("level", 1)
        text = b["text"]
        marker = b.get("marker", level != 0)
        size_pt = b.get("size_pt", font_pt_for_level(level))

        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(PARA_SPACE_AFTER_PT)
        p.line_spacing = LINE_SPACING
        add_run_with_markup(p, text, size_pt, base_bold=False, base_color=TEXT_DARK)
        if marker and level >= 1:
            set_bullet(p, level)
        else:
            set_no_bullet_but_indent(p, level)

        citation = b.get("citation")
        if citation:
            cp = tf.add_paragraph()
            cp.space_after = Pt(CITATION_SPACE_AFTER_PT)
            cp.alignment = PP_ALIGN.RIGHT
            set_no_bullet_but_indent(cp, 0)
            crun = cp.add_run()
            crun.text = citation
            set_run_font(crun, size_pt=CITATION_FONT_PT, italic=True, color=TEXT_GRAY)
    return first


def estimate_bullets_height(bullets, avail_w_in):
    """Rough pre-render estimate of a bullet block's natural height. Used so
    a slide with only 1-2 short bullet lines next to an image doesn't
    reserve a fixed fraction of the body for text and starve the image of
    space it could otherwise use -- see TEXT_IMAGE_SPLIT in add_content_slide."""
    total_in = 0.0
    for b in bullets:
        level = b.get("level", 1)
        text = re.sub(r"\*\*|__|\+\+", "", b["text"])
        size_pt = b.get("size_pt", font_pt_for_level(level))
        line_w_in = max(1.0, avail_w_in - L_MARL_IN.get(level, L_MARL_IN[3]))
        chars_per_line = max(1, int(line_w_in / (size_pt / 72.0)))
        lines = max(1, -(-len(text) // chars_per_line))
        total_in += lines * (size_pt / 72.0) * LINE_SPACING + PARA_SPACE_AFTER_PT / 72.0
        if b.get("citation"):
            total_in += (CITATION_FONT_PT / 72.0) * LINE_SPACING + CITATION_SPACE_AFTER_PT / 72.0
    return total_in


def add_box(slide, text, x, y, w):
    lines = text if isinstance(text, list) else [text]
    h = 2 * BOX_PAD_IN + BOX_LINE_H_IN * len(lines)
    add_rect(slide, x, y, w, h, fill_color=None, line_color=BLACK, line_pt=BOX_BORDER_PT)
    _, tf = add_textbox(
        slide, x + BOX_PAD_IN, y + BOX_PAD_IN, w - 2 * BOX_PAD_IN, h - 2 * BOX_PAD_IN, anchor=MSO_ANCHOR.MIDDLE
    )
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.line_spacing = LINE_SPACING
        set_no_bullet_but_indent(p, 0)
        add_run_with_markup(p, line, BOX_FONT_PT, base_bold=False, base_color=TEXT_DARK)
    return h


def estimate_box_height(text):
    lines = text if isinstance(text, list) else [text]
    return 2 * BOX_PAD_IN + BOX_LINE_H_IN * len(lines)


def normalize_images(images):
    out = []
    for img in images:
        if isinstance(img, dict):
            out.append({"path": img["path"], "caption": img.get("caption")})
        else:
            out.append({"path": img, "caption": None})
    return out


def add_image_grid(slide, images, x, y, w, h):
    images = normalize_images(images)
    n = len(images)
    if n == 0:
        return
    cols = 1 if n == 1 else 2
    rows = -(-n // cols)  # ceil division
    cell_w = (w - IMAGE_GAP_IN * (cols - 1)) / cols
    cell_h = (h - IMAGE_GAP_IN * (rows - 1)) / rows
    for i, img in enumerate(images):
        row, col = divmod(i, cols)
        cell_x = x + col * (cell_w + IMAGE_GAP_IN)
        cell_y = y + row * (cell_h + IMAGE_GAP_IN)
        pic_h = cell_h - (IMAGE_CAPTION_H_IN if img["caption"] else 0)
        add_picture_contain(slide, img["path"], cell_x, cell_y, cell_w, pic_h)
        if img["caption"]:
            _, tf = add_textbox(slide, cell_x, cell_y + pic_h, cell_w, IMAGE_CAPTION_H_IN, anchor=MSO_ANCHOR.TOP)
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            set_no_bullet_but_indent(p, 0)
            add_run_with_markup(p, img["caption"], IMAGE_CAPTION_FONT_PT, base_bold=False, base_color=TEXT_GRAY)


def add_columns(slide, columns, x, y, w, h):
    n = len(columns)
    if n == 0:
        return
    col_w = (w - COLUMN_GAP_IN * (n - 1)) / n
    for i, col in enumerate(columns):
        col_x = x + i * (col_w + COLUMN_GAP_IN)
        cy = y
        remaining_h = h
        if col.get("heading"):
            _, tf = add_textbox(slide, col_x, cy, col_w, COLUMN_HEADING_H_IN, anchor=MSO_ANCHOR.MIDDLE)
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            set_no_bullet_but_indent(p, 0)
            add_run_with_markup(p, col["heading"], COLUMN_HEADING_FONT_PT, base_bold=True, base_color=TEXT_DARK)
            cy += COLUMN_HEADING_H_IN
            remaining_h -= COLUMN_HEADING_H_IN

        image = col.get("image")
        bullets = col.get("bullets")
        if image and bullets:
            img_h = remaining_h * 0.55
            add_picture_contain(slide, image, col_x, cy, col_w, img_h)
            _, tf = add_textbox(slide, col_x, cy + img_h + TEXT_IMAGE_GAP_IN, col_w, remaining_h - img_h - TEXT_IMAGE_GAP_IN)
            add_bullets(tf, bullets)
        elif image:
            add_picture_contain(slide, image, col_x, cy, col_w, remaining_h)
        elif bullets:
            _, tf = add_textbox(slide, col_x, cy, col_w, remaining_h)
            add_bullets(tf, bullets)


def add_header(slide, heading_text):
    add_rect(slide, 0, 0, SLIDE_W_IN, HEADER_H_IN, GREEN)
    _, tf = add_textbox(
        slide, MARGIN_IN, 0, SLIDE_W_IN - 2 * MARGIN_IN, HEADER_H_IN, anchor=MSO_ANCHOR.MIDDLE, autofit=False
    )
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = heading_text
    set_run_font(run, size_pt=HEADER_FONT_PT, bold=True, color=WHITE)
    add_text_outline(run, color=BLACK)


def add_subtitle(slide, text, style, x, y, w):
    _, tf = add_textbox(slide, x, y, w, SUBTITLE_H_IN, anchor=MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]
    set_no_bullet_but_indent(p, 0)
    underline = style == "underline"
    bold = style != "underline"
    add_run_with_markup(p, text, SUBTITLE_FONT_PT, base_bold=bold, base_color=TEXT_DARK)
    if underline:
        for run in p.runs:
            run.font.underline = True


def add_content_slide(prs, heading, slide_spec):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    set_white_background(slide)
    add_header(slide, heading)

    body_x = MARGIN_IN
    body_y = HEADER_H_IN + 0.3
    body_w = SLIDE_W_IN - 2 * MARGIN_IN
    body_bottom = SLIDE_H_IN - MARGIN_IN

    cursor_y = body_y
    subtitle = slide_spec.get("subtitle")
    if subtitle:
        add_subtitle(slide, subtitle, slide_spec.get("subtitle_style", "bold"), body_x, cursor_y, body_w)
        cursor_y += SUBTITLE_H_IN + 0.15

    box_text = slide_spec.get("box")
    box_h = (estimate_box_height(box_text) + 0.2) if box_text else 0
    content_bottom = body_bottom - box_h

    bullets = slide_spec.get("bullets") or []
    images = slide_spec.get("images") or []
    columns = slide_spec.get("columns")

    if columns:
        intro_h = 0.0
        if bullets:
            intro_h = min(1.2, 0.45 * len(bullets) + 0.3)
            _, tf = add_textbox(slide, body_x, cursor_y, body_w, intro_h)
            add_bullets(tf, bullets)
        add_columns(slide, columns, body_x, cursor_y + intro_h, body_w, content_bottom - cursor_y - intro_h)
    elif bullets and images:
        max_text_h = (content_bottom - cursor_y) * TEXT_IMAGE_SPLIT
        min_text_h = font_pt_for_level(1) / 72.0 * LINE_SPACING + 0.15
        text_h = min(max_text_h, max(min_text_h, estimate_bullets_height(bullets, body_w) + 0.15))
        _, tf = add_textbox(slide, body_x, cursor_y, body_w, text_h)
        add_bullets(tf, bullets)
        img_y = cursor_y + text_h + TEXT_IMAGE_GAP_IN
        img_h = content_bottom - img_y
        add_image_grid(slide, images, body_x, img_y, body_w, img_h)
    elif images:
        add_image_grid(slide, images, body_x, cursor_y, body_w, content_bottom - cursor_y)
    elif bullets:
        _, tf = add_textbox(slide, body_x, cursor_y, body_w, content_bottom - cursor_y)
        add_bullets(tf, bullets)

    if box_text:
        add_box(slide, box_text, body_x, body_bottom - box_h + 0.2, body_w)

    return slide


def add_front_matter_slide(prs, image_path, overlay_text=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    set_white_background(slide)
    add_picture_contain(slide, image_path, 0, 0, SLIDE_W_IN, SLIDE_H_IN)

    if overlay_text:
        y = SLIDE_H_IN - TITLE_OVERLAY_BOTTOM_MARGIN_IN - TITLE_OVERLAY_H_IN
        _, tf = add_textbox(slide, 0, y, SLIDE_W_IN, TITLE_OVERLAY_H_IN, anchor=MSO_ANCHOR.MIDDLE)
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        set_no_bullet_but_indent(p, 0)
        run = p.add_run()
        run.text = overlay_text
        set_run_font(run, size_pt=TITLE_OVERLAY_FONT_PT, bold=False, color=BLACK)

    return slide


# ---------------------------------------------------------------------------
# Spec assembly
# ---------------------------------------------------------------------------


def resolve_path(base_dir, path):
    p = Path(path)
    return p if p.is_absolute() else (base_dir / p)


def collect_image_paths(slide_spec):
    paths = []
    for img in slide_spec.get("images") or []:
        paths.append(img["path"] if isinstance(img, dict) else img)
    for col in slide_spec.get("columns") or []:
        if col.get("image"):
            paths.append(col["image"])
    return paths


def build(spec, output_path, base_dir):
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)

    presenter = spec.get("presenter", "堀内裕介")
    date_label = spec.get("date_label", "●月●日")
    overlay_text = f"Journal Club {date_label} {presenter}".strip()

    front_matter = spec.get("front_matter")
    if not front_matter:
        raise KeyError("front_matter")

    for item in front_matter:
        img = resolve_path(base_dir, item["image"])
        if not img.exists():
            raise FileNotFoundError(f"front_matter image not found: {img}")
        text = overlay_text if item.get("type") == "title" else None
        add_front_matter_slide(prs, img, overlay_text=text)

    for section in spec.get("sections", []):
        heading = section["heading"]
        for i, slide_spec in enumerate(section.get("slides", [])):
            if not any(slide_spec.get(k) for k in ("bullets", "box", "images", "columns")):
                raise KeyError(f"section '{heading}', slide {i + 1}: needs bullets, box, images, or columns")

            resolved_spec = dict(slide_spec)
            resolved_images = []
            for img in slide_spec.get("images") or []:
                path = img["path"] if isinstance(img, dict) else img
                resolved = resolve_path(base_dir, path)
                if not resolved.exists():
                    raise FileNotFoundError(f"image not found: {resolved} (section '{heading}', slide {i + 1})")
                if isinstance(img, dict):
                    resolved_images.append({**img, "path": resolved})
                else:
                    resolved_images.append(str(resolved))
            resolved_spec["images"] = resolved_images

            if slide_spec.get("columns"):
                resolved_columns = []
                for col in slide_spec["columns"]:
                    col = dict(col)
                    if col.get("image"):
                        resolved = resolve_path(base_dir, col["image"])
                        if not resolved.exists():
                            raise FileNotFoundError(
                                f"image not found: {resolved} (section '{heading}', slide {i + 1}, column)"
                            )
                        col["image"] = str(resolved)
                    resolved_columns.append(col)
                resolved_spec["columns"] = resolved_columns

            add_content_slide(prs, heading, resolved_spec)

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
