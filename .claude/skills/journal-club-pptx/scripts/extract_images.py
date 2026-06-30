#!/usr/bin/env python3
"""Render PDF pages and crop figure/table regions as standalone images.

Used to pull artwork out of a paper PDF for pasting into the journal-club
deck: full pages (title page, visual abstract) via `render`, and individual
figures/tables via `crop`.

Usage:
    # Render every page (or a subset) to a full-page PNG for visual inspection
    # and for direct use as title / visual-abstract slide images.
    python extract_images.py render paper.pdf out_dir/ [--dpi 300] [--pages 1,2,5-7]

    # Crop a single figure/table out of one page. x0,y0,x1,y1 are fractions
    # (0.0-1.0) of the page width/height -- estimate them by eye from the
    # full-page PNG produced by `render`. The crop is re-rendered directly
    # from the PDF (not from the PNG) so it stays crisp at any DPI, and by
    # default the surrounding whitespace is trimmed to the figure's content.
    python extract_images.py crop paper.pdf 4 0.08 0.12 0.55 0.48 figure_1.png
"""

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


def parse_page_spec(spec: str | None, page_count: int) -> list[int]:
    if not spec:
        return list(range(1, page_count + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    out_of_range = [p for p in pages if not (1 <= p <= page_count)]
    if out_of_range:
        raise ValueError(f"page(s) {sorted(out_of_range)} out of range 1-{page_count}")
    return sorted(pages)


def autotrim(img: Image.Image, bg_threshold: int = 248, pad_px: int = 10) -> Image.Image:
    """Crop uniform near-white margins down to the actual content bounding box."""
    gray = img.convert("L")
    mask = gray.point(lambda p: 255 if p < bg_threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - pad_px)
    top = max(0, top - pad_px)
    right = min(img.width, right + pad_px)
    bottom = min(img.height, bottom + pad_px)
    return img.crop((left, top, right, bottom))


def render_pages(pdf_path: str, output_dir: str, dpi: int, page_spec: str | None) -> None:
    doc = fitz.open(pdf_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = parse_page_spec(page_spec, doc.page_count)
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    for page_num in pages:
        page = doc[page_num - 1]
        pix = page.get_pixmap(matrix=matrix)
        out_path = out_dir / f"page_{page_num}.png"
        pix.save(str(out_path))
        print(f"page={page_num} path={out_path} width={pix.width} height={pix.height}")
    doc.close()


def crop_region(
    pdf_path: str,
    page_number: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    output_path: str,
    dpi: int,
    do_autotrim: bool,
    pad_px: int,
) -> None:
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("x0,y0,x1,y1 must satisfy 0<=x0<x1<=1 and 0<=y0<y1<=1")

    doc = fitz.open(pdf_path)
    if not (1 <= page_number <= doc.page_count):
        raise ValueError(f"page {page_number} out of range 1-{doc.page_count}")
    page = doc[page_number - 1]
    rect = page.rect
    clip = fitz.Rect(
        rect.x0 + x0 * rect.width,
        rect.y0 + y0 * rect.height,
        rect.x0 + x1 * rect.width,
        rect.y0 + y1 * rect.height,
    )
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, clip=clip)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))
    width, height = pix.width, pix.height
    doc.close()

    if do_autotrim:
        img = Image.open(out_path)
        trimmed = autotrim(img, pad_px=pad_px)
        trimmed.save(out_path)
        width, height = trimmed.size

    print(f"path={out_path} width={width} height={height}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="Render full PDF pages to PNG")
    p_render.add_argument("pdf_path")
    p_render.add_argument("output_dir")
    p_render.add_argument("--dpi", type=int, default=300)
    p_render.add_argument("--pages", default=None, help="e.g. '1,2,5-7' (default: all pages)")

    p_crop = sub.add_parser("crop", help="Crop one figure/table region out of a page")
    p_crop.add_argument("pdf_path")
    p_crop.add_argument("page", type=int, help="1-indexed page number")
    p_crop.add_argument("x0", type=float, help="left edge, fraction of page width (0-1)")
    p_crop.add_argument("y0", type=float, help="top edge, fraction of page height (0-1)")
    p_crop.add_argument("x1", type=float, help="right edge, fraction of page width (0-1)")
    p_crop.add_argument("y1", type=float, help="bottom edge, fraction of page height (0-1)")
    p_crop.add_argument("output_path")
    p_crop.add_argument("--dpi", type=int, default=300)
    p_crop.add_argument("--no-autotrim", action="store_true", help="keep the bbox as given; skip whitespace trim")
    p_crop.add_argument("--pad-px", type=int, default=10, help="padding kept around trimmed content")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "render":
            render_pages(args.pdf_path, args.output_dir, args.dpi, args.pages)
        elif args.command == "crop":
            crop_region(
                args.pdf_path,
                args.page,
                args.x0,
                args.y0,
                args.x1,
                args.y1,
                args.output_path,
                args.dpi,
                not args.no_autotrim,
                args.pad_px,
            )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
