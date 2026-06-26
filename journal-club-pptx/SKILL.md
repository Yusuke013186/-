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
"そのまま" — don't crop these):

```bash
python scripts/extract_images.py render paper.pdf work/front/ --dpi 300 --pages 1
```

Re-render at 300 DPI for the actual deck (150 DPI was just for inspection).
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
          "bullets": [
            {"level": 1, "text": "..."},
            {"level": 2, "text": "..."}
          ],
          "images": []
        }
      ]
    },
    {
      "heading": "結果",
      "slides": [
        {"bullets": [{"level": 1, "text": "..."}], "images": ["work/figures/figure_1.png"]}
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
- Each slide has `bullets` (can be empty) and `images` (can be empty), but not
  both empty. A slide with both bullets and images splits the slide
  bullets-on-top / images-below. A slide with only images lays them out in a
  grid (1 column if there's one image, 2 columns otherwise).
- All image paths are resolved relative to the JSON file's own directory (or
  pass absolute paths).
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
it on a throwaway one-slide deck first to tell the difference). If a working
PDF rasterizer isn't available, fall back to the renderer already in this
skill instead of trying to install one:

```bash
python scripts/extract_images.py render output_as_pdf.pdf work/qa/ --dpi 150
```

If visual rendering isn't available at all, do structural QA instead with
python-pptx: re-open `output.pptx`, walk `slide.shapes`, and confirm each
shape's `(left, top, width, height)` stays within the slide bounds and that
text boxes and pictures don't unintentionally overlap (the title slide's
overlay bar intentionally sits on top of the picture — that one's expected).
Fix anything found and rebuild; one fix-and-verify pass is normally enough
unless the fix reveals a new problem.

## Scripts

- **`scripts/extract_images.py`** — `render` (whole pages to PNG) and `crop`
  (single figure/table region, re-rendered straight from the PDF, with
  whitespace autotrim). Run `--help` on either subcommand for all flags.
- **`scripts/build_pptx.py`** — turns the JSON spec into the final .pptx. Full
  schema is also documented in its module docstring.

## Visual style — defaults in force, pending the real template

This skill was written from a detailed text specification. The reference
template the user mentioned placing alongside it (精読の例.pdf, i.e. an actual
example of the target slide design) was **not present** when this skill was
built, so the constants below are reasonable defaults, not a measured match to
that file. They all live in one block at the top of `scripts/build_pptx.py` —
if the real template shows up later, compare against it and tune that block
rather than restructuring the script:

- 16:9 slides (13.333" × 7.5")
- Header bar `#3B7D23` green, white bold 26pt text, 0.85" tall
- Body text dark gray (`#262626`); level-1 bullets 20pt bold, level-2 16pt
  regular; Meiryo for Japanese glyphs, Calibri for Latin/numerals in the same
  run
- Title-slide overlay: a 0.55"-tall green bar across the bottom of the
  full-bleed title image, with the "Journal Club ●月●日 〈presenter〉" text
  centered in white bold 16pt

If the user supplies the actual reference file, re-render a sample deck and
compare side-by-side before changing these — don't guess a second time.
