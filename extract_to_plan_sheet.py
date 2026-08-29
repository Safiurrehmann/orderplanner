#!/usr/bin/env python3
"""Build a multi-PO production plan workbook and place matched embroidery artwork."""

from __future__ import annotations

import io
import re
import shutil
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage
from pypdf import PdfReader

APP_DIR = Path(__file__).resolve().parent
FIRST_DATA_ROW = 4
INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")

# Each artwork source is a per-contract spec-sheet JPG/PNG (a Royce Apparel /
# Pressbox "tech pack" export) that contains, among other things, two garment
# mockup photos AND two separate bordered boxes lower on the page holding the
# actual isolated embroidery art -- a compact front/chest logo on the left and
# a wide back wordmark on the right. Those two boxes are what get cropped out;
# the mockup photos are not used. Box positions are calibrated as pixel
# offsets against ARTWORK_REF_SIZE (measured from real sample files) and then
# scaled to each upload's actual size, since exports vary by a few pixels.
# Confirmed identical across all three garment styles/workbook formats --
# every sample spec-sheet checked (Mocktail, Belvedere, Flannigan) is exactly
# ARTWORK_REF_SIZE with the front box on the left and the back box on the
# right, so one calibration serves every format.
ARTWORK_REF_SIZE = (1508, 1134)
FRONT_ART_BOX_REF = (37, 619, 498, 912)
BACK_ART_BOX_REF = (562, 619, 1473, 912)
_ARTWORK_REF_ASPECT = ARTWORK_REF_SIZE[0] / ARTWORK_REF_SIZE[1]


@dataclass(frozen=True)
class ImageSlot:
    """One artwork cell in a generated row: which column it lives in, the max
    (width, height) in px to fit the picture into (aspect preserved), and
    which of the two crops out of extract_artwork_crops() -- "front" or
    "back" -- feeds it. Belvedere's Head column also sources "front": Head
    almost always carries the same chest logo as Front, so it reuses that
    same crop rather than needing a third picture."""
    column: str
    box: tuple[int, int]
    source: str  # "front" or "back"


@dataclass(frozen=True)
class WorkbookFormat:
    """Everything that differs between the three garment-style plan-sheet
    layouts. quantity_column is always the column immediately right of the
    last image slot (verified across all three templates). The three formula
    columns after it -- buffer / fleece / rib -- aren't listed here because
    their multipliers differ per format (e.g. Mocktail buffers +10 and
    multiplies fleece by 0.933; Belvedere buffers +6 and multiplies fleece by
    1.04); they're read straight off each template's own blueprint sample row
    instead, see _capture_formula_templates()."""
    key: str
    label: str
    template_path: Path
    blueprint_sheet: str
    last_column: int
    print_last_column: str
    image_slots: tuple[ImageSlot, ...]
    quantity_column: int


WORKBOOK_FORMATS: dict[str, WorkbookFormat] = {
    "mocktail": WorkbookFormat(
        key="mocktail", label="Mocktail",
        template_path=APP_DIR / "PLAN SHEET.xlsx", blueprint_sheet="WS72823",
        last_column=15, print_last_column="M",
        image_slots=(
            ImageSlot("F", (184, 49), "back"),
            ImageSlot("G", (81, 65), "front"),
        ),
        quantity_column=8,
    ),
    "flannigan": WorkbookFormat(
        key="flannigan", label="Flannigan",
        template_path=APP_DIR / "FLANNIGAN.xlsx", blueprint_sheet="WS73465",
        last_column=14, print_last_column="L",
        image_slots=(
            ImageSlot("F", (160, 65), "front"),
        ),
        quantity_column=7,
    ),
    "belvedere": WorkbookFormat(
        key="belvedere", label="Belvedere",
        template_path=APP_DIR / "BELVEDERE.xlsx", blueprint_sheet="WS72849",
        last_column=16, print_last_column="N",
        image_slots=(
            ImageSlot("F", (184, 49), "back"),
            ImageSlot("G", (81, 65), "front"),
            ImageSlot("H", (81, 65), "front"),
        ),
        quantity_column=9,
    ),
}


def pdf_text(pdf_path: Path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf_path)).pages)


def extract_purchase_order(pdf_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return the PO number and every printable line item in the Royce PO format.

    The same regex works across every garment style/workbook format -- verified
    directly against real Mocktail, Belvedere and Flannigan purchase orders."""
    text = pdf_text(pdf_path)
    po_match = re.search(r"Purchase\s+Order\s+ID\s*(\d+)", text, re.IGNORECASE)
    if not po_match:
        raise RuntimeError(f"Could not find a Purchase Order ID in {pdf_path.name}.")
    pattern = re.compile(
        r"^OS\s*\n\s*(?P<quantity>\d+)\s*\n.*?^Replace:\s*\n\s*"
        r"(?P<contract>[A-Z0-9-]+)\s*\n(?:\s*[A-Z]{2,4}\s*\n)?\s*"
        r"(?P<color>[A-Z]{3})\s*-", re.MULTILINE | re.DOTALL,
    )
    rows: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        contract = match.group("contract").strip().upper()
        emb = "".join(char for char in contract if char.isalpha())[:3]
        if emb:
            rows.append({"contract": contract, "emb": emb,
                         "color": match.group("color").strip().upper(),
                         "quantity": int(match.group("quantity"))})
    if not rows:
        raise RuntimeError(f"No purchase-order line items could be read from {pdf_path.name}.")
    return po_match.group(1), rows


def safe_sheet_title(base: str, existing: set[str]) -> str:
    """Sanitise a worksheet title, truncate to Excel's 31-char limit, and dedupe."""
    cleaned = INVALID_SHEET_CHARS.sub("_", base).strip()[:31] or "Sheet"
    title = cleaned
    suffix = 2
    while title in existing:
        trim = 31 - len(f" ({suffix})")
        title = f"{cleaned[:trim]} ({suffix})"
        suffix += 1
    existing.add(title)
    return title


def _copy_row_style(sheet: Any, row: int, styles: list[Any], height: float | None) -> None:
    for column, cell_style in enumerate(styles, start=1):
        sheet.cell(row, column)._style = copy(cell_style)
    sheet.row_dimensions[row].height = height


def _row_formula(template: str, row: int) -> str:
    """Re-point a same-row formula (e.g. "=H4+10") at a different row.

    Every buffer/fleece/rib formula we've seen only references cells in its
    own row, so swapping the FIRST_DATA_ROW digit for the target row is safe."""
    return re.sub(rf"(?<=[A-Z]){FIRST_DATA_ROW}\b", str(row), template)


def _capture_formula_templates(blueprint: Any, fmt: WorkbookFormat) -> dict[int, str | None]:
    """Read the buffer/fleece/rib formulas already sitting in the blueprint's
    own sample row (the three columns right of quantity_column), before that
    row gets cleared. Reusing whatever the template already has avoids
    hardcoding one format's business formula for the other two."""
    return {
        column: blueprint.cell(FIRST_DATA_ROW, column).value
        for column in (fmt.quantity_column + 1, fmt.quantity_column + 2, fmt.quantity_column + 3)
    }


def _populate_sheet(sheet: Any, po_number: str, rows: list[dict[str, Any]], row_styles: list[Any],
                     row_height: float | None, fmt: WorkbookFormat, formula_templates: dict[int, str | None]) -> None:
    """Fill one blueprint-derived sheet with one PO's line items."""
    sheet["D2"] = int(po_number) if po_number.isdigit() else po_number
    qty_col = fmt.quantity_column
    for offset, item in enumerate(rows):
        row = FIRST_DATA_ROW + offset
        _copy_row_style(sheet, row, row_styles, row_height)
        for column in range(1, fmt.last_column + 1):
            sheet.cell(row, column).value = None
        sheet.cell(row, 1).value = offset + 1
        sheet.cell(row, 2).value = item["contract"]
        sheet.cell(row, 3).value = item["emb"]
        sheet.cell(row, 4).value = item["color"]
        sheet.cell(row, qty_col).value = item["quantity"]
        for column, template in formula_templates.items():
            if template is not None:
                sheet.cell(row, column).value = _row_formula(template, row)
    total_row = FIRST_DATA_ROW + len(rows)
    _copy_row_style(sheet, total_row, row_styles, row_height)
    for column in range(1, fmt.last_column + 1):
        sheet.cell(total_row, column).value = None
    qty_letter = get_column_letter(qty_col)
    buffer_letter = get_column_letter(qty_col + 1)
    sheet.cell(total_row, qty_col).value = f"=SUM({qty_letter}{FIRST_DATA_ROW}:{qty_letter}{total_row - 1})"
    sheet.cell(total_row, qty_col + 1).value = f"=SUM({buffer_letter}{FIRST_DATA_ROW}:{buffer_letter}{total_row - 1})"
    # The blueprint's print area only ever covered its sample rows; stretch it to
    # cover every generated row (plus the totals row) so printing isn't cut off.
    sheet.print_area = f"A1:{fmt.print_last_column}{total_row}"


def build_workbook(fmt: WorkbookFormat, output_path: Path, purchase_orders: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """Create one blueprint-derived worksheet per uploaded PO, in the given workbook format.

    Returns {"sheets": {sheet_title: rows}}.
    """
    if not purchase_orders:
        raise RuntimeError("No purchase orders to build a workbook from.")
    shutil.copy2(fmt.template_path, output_path)
    workbook = load_workbook(output_path)
    if fmt.blueprint_sheet not in workbook.sheetnames:
        raise RuntimeError(f"The {fmt.label} workbook blueprint is missing its {fmt.blueprint_sheet} sheet.")
    blueprint = workbook[fmt.blueprint_sheet]
    for candidate in list(workbook.worksheets):
        if candidate is not blueprint:
            workbook.remove(candidate)

    formula_templates = _capture_formula_templates(blueprint, fmt)

    # The blueprint ships with its own sample back/front artwork anchored at
    # FIRST_DATA_ROW. Strip it -- it's sample data, not something every
    # generated sheet should carry forward -- before cloning, so no clone
    # inherits it either.
    blueprint._images = []

    row_styles = [copy(blueprint.cell(FIRST_DATA_ROW, column)._style) for column in range(1, fmt.last_column + 1)]
    row_height = blueprint.row_dimensions[FIRST_DATA_ROW].height
    blueprint.delete_rows(FIRST_DATA_ROW, blueprint.max_row - FIRST_DATA_ROW + 1)

    # Clone the now-blank, image-free blueprint once per extra PO (copy_worksheet
    # preserves styles, column widths, merges and page setup, but not print_area,
    # which _populate_sheet sets explicitly on every sheet below).
    sheets = [blueprint]
    for _ in purchase_orders[1:]:
        sheets.append(workbook.copy_worksheet(blueprint))

    existing_titles: set[str] = set()
    sheet_rows: dict[str, list[dict[str, Any]]] = {}
    for (po_number, rows), sheet in zip(purchase_orders, sheets):
        sheet.title = safe_sheet_title(f"WS{po_number}", existing_titles)
        _populate_sheet(sheet, po_number, rows, row_styles, row_height, fmt, formula_templates)
        sheet_rows[sheet.title] = rows
    workbook.save(output_path)
    return {"sheets": sheet_rows}


def find_known_code(filename: str, known_codes: set[str]) -> str | None:
    """Return the single known code (contract or EMB) contained in the filename, else None.

    Real artwork filenames embed the code with no delimiter (e.g. ``APFGNCAL``
    for ``CAL``), so this checks for containment against every known code
    rather than trying to tokenise the filename.
    """
    stem = re.sub(r"[^A-Z0-9]", "", Path(filename).stem.upper())
    matches = {code for code in known_codes if code and code in stem}
    return next(iter(matches)) if len(matches) == 1 else None


def _scale_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    ref_w, ref_h = ARTWORK_REF_SIZE
    x0, y0, x1, y1 = box
    return (round(x0 * width / ref_w), round(y0 * height / ref_h),
            round(x1 * width / ref_w), round(y1 * height / ref_h))


def extract_artwork_crops(image_path: Path) -> tuple[bytes, bytes] | None:
    """Crop the isolated front/back embroidery art out of a spec-sheet image.

    Returns (front_png_bytes, back_png_bytes), or None if the file isn't a
    readable image or doesn't look like this template (aspect ratio too far
    off ARTWORK_REF_SIZE for the calibrated boxes to be trustworthy). Callers
    that only need one side (e.g. Flannigan's front-only slot) simply ignore
    the other element of the tuple.
    """
    try:
        with PILImage.open(image_path) as source:
            image = source.convert("RGB")
    except Exception:
        return None
    width, height = image.size
    if width <= 0 or height <= 0:
        return None
    aspect = width / height
    if abs(aspect - _ARTWORK_REF_ASPECT) / _ARTWORK_REF_ASPECT > 0.08:
        return None
    front_buffer, back_buffer = io.BytesIO(), io.BytesIO()
    image.crop(_scale_box(FRONT_ART_BOX_REF, width, height)).save(front_buffer, format="PNG")
    image.crop(_scale_box(BACK_ART_BOX_REF, width, height)).save(back_buffer, format="PNG")
    return front_buffer.getvalue(), back_buffer.getvalue()


def _fit_within(data: bytes, max_width: int, max_height: int) -> tuple[int, int]:
    with PILImage.open(io.BytesIO(data)) as image:
        source_width, source_height = image.size
    if source_width <= 0 or source_height <= 0:
        return max_width, max_height
    scale = min(max_width / source_width, max_height / source_height)
    return max(1, round(source_width * scale)), max(1, round(source_height * scale))


def add_artwork_to_row(sheet: Any, row: int, column_letter: str, image_bytes: bytes, box: tuple[int, int]) -> None:
    """Place one artwork image in a row's cell, fit (aspect-preserved) into the slot's own box."""
    max_width, max_height = box
    width, height = _fit_within(image_bytes, max_width, max_height)
    image = ExcelImage(io.BytesIO(image_bytes))
    image.width, image.height = width, height
    sheet.add_image(image, f"{column_letter}{row}")
