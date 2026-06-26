---
name: journal-club-pptx
description: Generate a Japanese 抄読会 (journal club) PowerPoint deck from a single academic paper PDF. Pastes in the paper's title page and Visual Abstract as full-page images, extracts and includes every figure/table from the Results section, and writes editable 背景/方法/結果/考察/Limitation bullet slides in a green-header house style. Use this whenever the user asks to turn a paper or PDF into a journal club, 抄読会, lab-meeting, or paper-presentation deck, or asks to "summarize this paper as slides" / "make a PPTX from this PDF" — even if they don't say "journal club" explicitly and just hand over a paper PDF asking for a presentation.
---

# Journal Club PPTX Generator

Turns one academic paper PDF into a fully formatted, editable .pptx deck following
a fixed Japanese journal-club house style. The input is always exactly one paper
PDF. The output slide count is *not* fixed — it flexes with how much the paper
actually contains (a dense RCT with 6 figures needs more Results slides than a
short correspondence piece).

## Why this skill is structured the way it is

Building the deck is a two-stage process on purpose:

1. **Claude does the reading and judgment** — finding the title page, spotting
   every figure/table, deciding what counts as Background vs. Discussion,
   writing concise bullet Japanese.
2. **A deterministic script does the layout** — exact colors, fonts, margins,
   bullet glyphs. This is OOXML-level work (mixed Japanese/Latin typefaces,
   custom bullet characters) that is fiddly and easy to get subtly wrong by hand,
   so it is fully delegated to `scripts/build_pptx.py`. Never hand-write slide
   XML or call low-level python-pptx font APIs directly for this skill — express
   everything as the JSON spec below and let the script render it.

This split means the same script reliably reproduces the house style no matter
how the content varies paper to paper.

## Workflow

### 1. Render the PDF for inspection

```bash
pip install -r scripts/requirements.txt   # python-pptx, pymupdf, Pillow
python scripts/extract_images.py render paper.pdf work/pages/ --dpi 150
```

This drops one PNG per page (`work/pages/page_1.png`, `page_2.png`, ...). Use a
lower DPI (150) for the inspection pass — it's faster and Read still shows
figures/tables clearly enough to find them. Look at every single page; figures
referenced in the Results text are sometimes placed several pages later than
where they're discussed, and supplementary figures embedded in the main PDF
must still be included if the spec calls for "every figure/table."

### 2. Identify front matter and every figure/table

While reading the pages, work out:

- **Title page**: almost always page 1 — the page showing the paper's title,
  authors, and journal. Some PDFs have a journal-branded cover page before
  this; if so, use the page that actually shows the title, not the cover.
- **Visual Abstract**: a standalone graphical-abstract page or panel, if the
  paper has one. *Many papers do not have one* — in that case skip this
  front-matter slide entirely (front_matter can have just 1 entry). Don't
  invent one.
- **Every figure and table**, with: page number, and a normalized bounding box
  `(x0, y0, x1, y1)` as fractions (0.0-1.0) of that page's width/height. Eyeball
  these from the rendered PNG. Err on the generous side (include the caption if
  unsure) — `crop`'s autotrim will tighten whitespace, but it can't add back
  content you cropped out.

All figures/tables that support the Results section must end up in the deck —
this skill exists specifically so none get skipped. If the paper's Results
section describes a finding only in text with no associated figure, that's
fine; just don't omit a figure that exists.

### 3. Extract the images

Title page and Visual Abstract are pasted **as-is, full page** (the spec says
"そのまま" — don't crop these) by default:

```bash
python scripts/extract_images.py render paper.pdf work/front/ --dpi 300 --pages 1
```

Re-render at 300 DPI for the actual deck (150 DPI was just for inspection).

The reference template's title page happened to be a clean 16:9 slide, so a
full-bleed paste of the whole page just works. Real paper PDFs are usually
portrait and far denser (running headers, DOI/copyright footers, multi-column
abstract text). `add_front_matter_slide` always letterboxes the page
on a 16:9 slide preserving aspect ratio, so a dense portrait page will paste
correctly but the title/author block can end up small enough to be illegible,
and the "Journal Club ●月●日" overlay always sits in a fixed band near the
bottom — if that band lands on top of existing footer text on a busy page,
use judgment: re-crop just the masthead/title/author region with
`extract_images.py crop` instead of the literal full page, so the pasted
image is legible and leaves clear space for the overlay. Use the full page
only when, like the reference template, it's already clean enough to read at
slide size.

Each figure/table gets its own crop, re-rendered straight from the PDF (sharper
than slicing the page PNG) and auto-trimmed of surrounding whitespace:

```bash
python scripts/extract_images.py crop paper.pdf 4 0.08 0.12 0.55 0.48 work/figures/figure_1.png
```

Page is 1-indexed. If a crop comes out wrong (clipped content, grabbed a
neighboring panel), re-run with adjusted coordinates — don't try to fix it in
an image editor.

### 4. Draft the content

Summarize the paper into exactly these five section headings, in this order —
this taxonomy is fixed by the house style, so map the paper's actual structure
onto it even if the paper uses different headings:

| Heading | Maps from |
|---|---|
| 背景 (Background) | Introduction, rationale, objective/aim |
| 方法 (Methods) | Study design, population, intervention, endpoints |
| 結果 (Results) | Findings — **every extracted figure/table goes here** |
| 考察 (Discussion) | Interpretation, comparison to prior literature |
| Limitation | Limitations |

For Limitation: if the paper doesn't spell out its limitations explicitly,
write a brief critical appraisal yourself (study design weaknesses, sample
size, generalizability, bias risks, confounding, etc.) — a journal club is
expected to critique the paper, not just relay it.

Each section can have **one or many slides** — split a section across multiple
slides rather than cramming everything onto one when there's a lot to cover,
and feel free to give a thin section (e.g. a short Limitation) just one slide
with a couple of bullets. Total deck length should track the paper's actual
content density, not a fixed slide count.

Within a slide, write bullets as a two-level hierarchy:
- **Level 1 (■)**: the main claim/point, terse, presentation-style (not a full
  sentence copied from the paper)
- **Level 2 (・)**: supporting detail, numbers, sub-points

Write in Japanese (the deck's audience), matching the register of the spec
example (e.g. "心房細動患者における抗凝固療法は..."). Keep bullets short —
these are projected slides, not a manuscript.

For Results slides specifically: pair each figure with the bullets that
explain what it shows / the key statistic, the same way you would describe a
figure to someone in the room.

### 5. Assemble the JSON content spec

Write a JSON file (anywhere, e.g. `work/content_spec.json`) matching this
schema:

```json
{
  "presenter": "堀内裕介",
  "date_label": "●月●日",
  "front_matter": [
    {"type": "title", "image": "work/front/page_1.png"},
    {"type": "visual_abstract", "image": "work/front/page_2.png"}
  ],
  "sections": [
    {
      "heading": "背景",
      "slides": [
        {
          "subtitle": "シロスタゾールとCAS後の再狭窄",
          "subtitle_style": "bold",
          "bullets": [
            {"level": 1, "text": "頸動脈ステント留置術(CAS)後の**再狭窄**は長期予後を悪化させる", "citation": "Yamagami et al, J Vasc Surg 2018"},
            {"level": 2, "text": "再狭窄率は報告により5-30%と幅がある"},
            {"level": 1, "text": "→ 再狭窄予防における薬物療法の意義は明らかでない", "marker": false}
          ],
          "box": "CAS後の再狭窄を予防する薬物療法については一定の見解を得られていない."
        }
      ]
    },
    {
      "heading": "結果",
      "slides": [
        {"bullets": [{"level": 1, "text": "..."}], "images": ["work/figures/figure_1.png"]},
        {
          "subtitle": "再狭窄率の群間比較",
          "columns": [
            {"heading": "シロスタゾール群", "image": "work/figures/fig_a.png", "bullets": [{"level": 2, "text": "12か月再狭窄率 ++8.2%++"}]},
            {"heading": "標準治療群", "image": "work/figures/fig_b.png", "bullets": [{"level": 2, "text": "12か月再狭窄率 ++15.6%++"}]}
          ]
        }
      ]
    }
  ]
}
```

Notes on the schema:
- `front_matter` is a list of 1-2 entries. Only an entry with `"type": "title"`
  gets the "Journal Club ●月●日 〈presenter〉" text overlay at the bottom; any
  other `type` value (e.g. `"visual_abstract"`) is shown as a plain full-page
  image with no overlay. Omit the visual-abstract entry if the paper has none.
- `sections` must use exactly the five headings from the table above, in order.
  Omit a section only if the paper genuinely has nothing for it (rare — even
  then, prefer writing at least a one-bullet slide over dropping a heading).
- Each slide needs at least one of `bullets`, `box`, `images`, `columns`
  (all optional, all can be combined). `bullets` + `images` (no `columns`)
  splits the slide bullets-on-top / images-below. `images` alone lays them
  out in a grid (1 column if there's one image, 2 columns otherwise). For
  side-by-side image+text or text+text panels (common in 結果/考察), use
  `columns` instead — it's the general left/right mechanism; if `bullets` is
  also given alongside `columns` it renders as a short intro line above the
  column row.
- `subtitle` (+ optional `subtitle_style: "bold"|"underline"`, default bold)
  renders a slide-level subtitle line under the header, above the body —
  use it for a named sub-topic within a section (mirrors the reference
  template's per-slide subtitles).
- `bullets[]` items: `level` 1 = "■", 2/3 = "・" at increasing indent, 0 =
  flush with no marker (for lead-in/plain-paragraph lines). Set
  `"marker": false` to suppress a level's glyph while keeping its indent —
  used for "→ ..." conclusion lines. Optional per-bullet `citation` renders
  a right-aligned, italic, gray reference line directly under that bullet.
- `box` (string, or list of strings for multiple lines) renders a thin
  bordered, unfilled takeaway box anchored at the bottom of the slide body —
  use it for a one-line "bottom line" conclusion, matching the reference
  template's boxed takeaways on 背景-type slides.
- `columns[]`: each column is `{"heading"?, "image"?, "bullets"?}` rendered
  side by side with equal width. A column can mix an image with bullets
  (image on top, bullets below) or have just one of the two.
- Inline markup works inside any `text` / `box` / `subtitle` string:
  `**bold**`, `__underline__`, `++red++` — use red sparingly, for the one
  number/phrase you'd point at on the projector (matches the reference
  template's emphasis style).
- `images` entries may be a plain path string or `{"path", "caption"}` for a
  small centered caption under that image (e.g. "Table 1. ...").
- All image paths (including inside `columns[].image`) are resolved relative
  to the JSON file's own directory, or pass absolute paths.
- `presenter` and `date_label` default to `堀内裕介` / `●月●日` if omitted —
  ask the user for the real date if they haven't given one, rather than
  leaving the placeholder in a deck that's actually going to be presented.

### 6. Build the deck

```bash
python scripts/build_pptx.py work/content_spec.json output.pptx
```

The script raises a clear, file-and-context-specific error (missing image,
bad JSON, missing required key) and exits non-zero rather than producing a
half-built deck — if it errors, fix the spec and re-run rather than patching
the .pptx afterward.

### 7. Visual QA

Ideally: convert the .pptx to images and look at every slide for overlap,
overflow, or contrast problems (e.g. `soffice --headless --convert-to pdf`,
then rasterize the PDF). **Check this pipeline actually works in your current
environment before relying on it** — some sandboxes have only
`libreoffice-core` installed without the Impress/filter packages, in which
case `soffice --convert-to pdf` fails on *any* input, not just this one (try
it on a throwaway one-slide deck first to tell the difference). If it fails
that way, `apt-get install -y libreoffice-impress` and retry before giving up
on the pipeline. Note the rendering host also needs real Meiryo to fully
verify Japanese font weight/spacing — without it LibreOffice substitutes a
fallback CJK font, so use the render to check *layout* (overlap, overflow,
image sizing, alignment) and trust the spec/XML for font-family correctness.
If a working PDF rasterizer isn't available at all, fall back to the
renderer already in this skill instead of trying to install one:

```bash
python scripts/extract_images.py render output_as_pdf.pdf work/qa/ --dpi 150
```

If visual rendering isn't available at all, do structural QA instead with
python-pptx: re-open `output.pptx`, walk `slide.shapes`, and confirm each
shape's `(left, top, width, height)` stays within the slide bounds and that
text boxes and pictures don't unintentionally overlap (the title slide's
overlay text box intentionally sits on top of the picture, and a box's
border intentionally sits at the bottom edge of the body — those are
expected). Fix anything found and rebuild; one fix-and-verify pass is
normally enough unless the fix reveals a new problem.

## Scripts

- **`scripts/extract_images.py`** — `render` (whole pages to PNG) and `crop`
  (single figure/table region, re-rendered straight from the PDF, with
  whitespace autotrim). Run `--help` on either subcommand for all flags.
- **`scripts/build_pptx.py`** — turns the JSON spec into the final .pptx. Full
  schema is also documented in its module docstring.

## Visual style — measured against the reference template

These constants were measured directly off `精読の例.pdf` (pixel-sampled
colors, cropped/zoomed text for weight and placement) rather than guessed from
the text spec alone. They all live in one block at the top of
`scripts/build_pptx.py` — if a different reference file shows up later,
re-render a sample deck (see Visual QA below) and compare side-by-side before
changing any of this, the same way this set of values was derived:

- 16:9 slides (13.333" × 7.5")
- Header bar `#3B7D23` green (exact pixel match), 0.75" tall; heading text is
  a WordArt-style **white fill with a black outline stroke**, bold 28pt —
  not plain white text. `add_text_outline()` implements the outline by
  inserting `<a:ln>` before the existing `<a:solidFill>`/`<a:latin>` elements
  in the run's `rPr`, per OOXML's `CT_TextCharacterProperties` element order.
- Body text near-black (`#1A1A1A`). Level-1 "■" bullets are **regular
  weight, not bold** (confirmed by zooming the reference deck — easy to get
  wrong by assumption). Level-2/3 "・" bullets are smaller (18pt/16pt vs.
  20pt). Citations are small (13pt), italic, gray, right-aligned under the
  bullet they support. Inline `++red++` emphasis is exactly `#FF0000`.
- Meiryo / Meiryo-Bold for Japanese glyphs, Calibri for Latin/numerals — set
  as separate `a:latin`/`a:ea`/`a:cs` typeface elements on the same run via
  `set_run_font()`, since python-pptx's public `run.font.name` only sets one
  typeface for everything, which renders Latin digits/punctuation in the
  wrong font when mixed into Japanese text.
- Title-slide overlay is **plain text directly on the page image — no bar or
  box behind it.** Dark, regular (non-bold) weight, ~26pt, centered
  horizontally, sitting with a bottom margin (not flush against the slide
  edge) in whatever blank space the title page leaves. This was the biggest
  correction versus an earlier, unmeasured draft of this skill, which had
  wrongly assumed a solid green bar + white bold text here.
- Subtitle lines under a slide's header are bold by default, or underlined
  (`subtitle_style: "underline"`) for a secondary look used elsewhere in the
  deck — both observed in the reference template's 背景/考察 slides.
- Boxed takeaways (`box` in the JSON spec) are a thin black-outline
  rectangle with **no fill**, text vertically centered inside.
- Side-by-side panels (`columns` in the JSON spec) are equal-width, each
  optionally with a centered bold heading, an image, bullets, or an
  image+bullets stack — this is how the reference template lays out
  side-by-side figure comparisons and two-column discussion points.

None of this needs to be touched to use the skill — it's documented here so
a future visual tweak has the measurement reasoning instead of starting from
scratch.
