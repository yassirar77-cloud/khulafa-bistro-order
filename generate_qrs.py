#!/usr/bin/env python3
"""Generate printable QR codes for Khulafa Bistro tables.

Creates one PDF with a 2x2 grid per A4 page. Each tile contains:
- "Khulafa Bistro" header
- QR code (~5 cm x 5 cm when printed) pointing to the table's voice-order URL
- "MEJA T01" label in large type
- "Scan untuk order" footer
- A light border for cutting

Usage:
    python3 generate_qrs.py                       # defaults: T01..T20
    python3 generate_qrs.py --start 1 --end 20
    python3 generate_qrs.py --start 21 --end 40 --out qrs_T21_to_T40.pdf
"""
import argparse
import io

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

URL_TEMPLATE = "https://khulafa-bistro-order.onrender.com/table/T{num:02d}"

# A4 portrait: 210 mm x 297 mm. Margins 15 mm. Grid 2 cols x 2 rows.
PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
COLS, ROWS = 2, 2
TILE_W = (PAGE_W - 2 * MARGIN) / COLS
TILE_H = (PAGE_H - 2 * MARGIN) / ROWS
QR_SIZE = 55 * mm


def make_qr_png(url: str) -> io.BytesIO:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def draw_tile(c: canvas.Canvas, table_num: int, x: float, y: float) -> None:
    """Draw one QR tile with its bottom-left corner at (x, y)."""
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.5)
    c.rect(x, y, TILE_W, TILE_H)

    label = f"T{table_num:02d}"
    url = URL_TEMPLATE.format(num=table_num)

    cx = x + TILE_W / 2

    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(cx, y + TILE_H - 15 * mm, "Khulafa Bistro")

    qr_buf = make_qr_png(url)
    qr_y = y + TILE_H - 15 * mm - 8 * mm - QR_SIZE
    c.drawImage(
        ImageReader(qr_buf),
        cx - QR_SIZE / 2,
        qr_y,
        width=QR_SIZE,
        height=QR_SIZE,
        mask="auto",
    )

    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(cx, qr_y - 12 * mm, f"MEJA {label}")

    c.setFont("Helvetica", 10)
    c.drawCentredString(cx, y + 10 * mm, "Scan untuk order")


def generate(start: int, end: int, out_path: str) -> tuple[int, int]:
    """Generate the PDF. Returns (table_count, page_count)."""
    c = canvas.Canvas(out_path, pagesize=A4)
    c.setTitle(f"Khulafa Bistro QR codes T{start:02d}-T{end:02d}")

    per_page = COLS * ROWS
    tables = list(range(start, end + 1))
    page_count = 0

    for i, table_num in enumerate(tables):
        slot = i % per_page
        if slot == 0:
            page_count += 1
        col = slot % COLS
        row = slot // COLS  # 0 = top row, 1 = bottom
        x = MARGIN + col * TILE_W
        # y is bottom-left of tile; row 0 (top) sits at higher y
        y = MARGIN + (ROWS - 1 - row) * TILE_H
        draw_tile(c, table_num, x, y)
        if slot == per_page - 1 and i != len(tables) - 1:
            c.showPage()

    c.save()
    return len(tables), page_count


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=int, default=1, help="first table number (default 1)")
    p.add_argument("--end", type=int, default=20, help="last table number inclusive (default 20)")
    p.add_argument("--out", default=None, help="output PDF path")
    args = p.parse_args()

    if args.start < 1 or args.end < args.start:
        p.error("--start must be >= 1 and --end must be >= --start")

    out = args.out or f"qrs_T{args.start:02d}_to_T{args.end:02d}.pdf"
    n_tables, n_pages = generate(args.start, args.end, out)
    print(f"Wrote {out}  ({n_tables} tables, {n_pages} pages)")


if __name__ == "__main__":
    main()
