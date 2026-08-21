#!/usr/bin/env python3
"""Extract purchase-order styles and write a PLAN SHEET workbook."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from copy import copy
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pypdf import PdfReader

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
FIRST_DATA_ROW = 4
SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["styles"],
    "properties": {"styles": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["style_number", "color_code", "quantity"],
        "properties": {"style_number": {"type": "string"}, "color_code": {"type": "string"},
                       "quantity": {"type": "integer", "minimum": 0}}
    }}}
}
SYSTEM_PROMPT = (
    "You extract garment purchase-order line items. Return every distinct style/color line exactly once. "
    "style_number is the printed style number or code, color_code is the printed short color code before "
    "the color name (for example LTB in 'LTB - Light Blue'), and quantity "
    "is that line's actual quantity. Do not invent values, calculate quantities, or include headings, totals, "
    "size breakdowns, or non-style rows. Unavailable text is an empty string; unavailable quantity is 0."
)

def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()

def pdf_images(pdf_path: Path) -> list[str]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Install PyMuPDF to use vision fallback.") from exc
    document = fitz.open(pdf_path)
    result = []
    for page in document:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        result.append("data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode("ascii"))
    return result

def groq_request(messages: list[dict[str, Any]], model: str, strict: bool) -> dict[str, Any]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or api_key == "replace_me":
        raise RuntimeError("Set GROQ_API_KEY in your environment or .env file.")
    response_format: dict[str, Any]
    if strict:
        response_format = {"type": "json_schema", "json_schema": {
            "name": "purchase_order_styles", "strict": True, "schema": SCHEMA}}
    else:
        response_format = {"type": "json_object"}
    payload = json.dumps({"model": model, "temperature": 0, "messages": messages,
                          "response_format": response_format}).encode("utf-8")
    request = urllib.request.Request(GROQ_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Groq API returned HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not contact Groq: {exc.reason}") from exc
    try:
        return json.loads(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Groq returned an unexpected response: {body}") from exc

def abbreviation(value: str) -> str:
    return "".join(char for char in str(value).upper() if char.isalpha())[:3]

def validate_styles(raw_styles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    styles, seen = [], set()
    for index, raw in enumerate(raw_styles, 1):
        style, color = str(raw.get("style_number", "")).strip(), str(raw.get("color_code", "")).strip()
        try:
            quantity = int(raw.get("quantity", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Row {index} has an invalid quantity.") from exc
        if not abbreviation(style) or not abbreviation(color) or quantity < 0:
            raise RuntimeError(f"Row {index} is missing style, color, or valid quantity: {raw}")
        key = (style.upper(), color.upper())
        if key in seen:
            raise RuntimeError(f"Duplicate style/color returned: {style} / {color}")
        seen.add(key)
        styles.append({"emb": abbreviation(style), "main_body": abbreviation(color), "quantity": quantity})
    if not styles:
        raise RuntimeError("No style rows were returned. Try --vision or review the PDF.")
    return styles

# Disabled Groq implementation, retained for a later model-powered extractor.
# Neither the command-line tool nor the web server calls this function.
def extract_styles(pdf_path: Path, force_vision: bool = False) -> list[dict[str, Any]]:
    text = "" if force_vision else pdf_text(pdf_path)
    if len(text) >= 100:
        result = groq_request([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract styles from this purchase-order text:\n\n{text}"}],
            os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"), strict=True)
    else:
        content: list[dict[str, Any]] = [{"type": "text", "text": "Extract all styles from these PO pages."}]
        content.extend({"type": "image_url", "image_url": {"url": image}} for image in pdf_images(pdf_path))
        result = groq_request([{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": content}],
                              os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.6-27b"), strict=False)
    return validate_styles(result.get("styles", []))

def extract_local_styles(pdf_path: Path) -> list[dict[str, Any]]:
    """Deterministic fallback for this PO format when API access is unavailable."""
    text = pdf_text(pdf_path)
    pattern = re.compile(
        r"^OS\n(\d+)\n[\d.]+\nReplace:\n([A-Z]{3})65999FGN\s*(?:[A-Z]{2,3}\s*)?([A-Z]{3}) -",
        re.MULTILINE,
    )
    rows = [
        {"style_number": match.group(2), "color_code": match.group(3), "quantity": int(match.group(1))}
        for match in pattern.finditer(text)
    ]
    return validate_styles(rows)

def apply_row_style(sheet: Any, row: int, styles: list[Any], height: float | None) -> None:
    for column, cell_style in enumerate(styles, start=1):
        if cell_style is not None:
            sheet.cell(row, column)._style = copy(cell_style)
    sheet.row_dimensions[row].height = height

def build_workbook(template_path: Path, output_path: Path, styles: list[dict[str, Any]]) -> None:
    shutil.copy2(template_path, output_path)
    workbook = load_workbook(output_path)
    sheet = workbook.active
    # Keep the format of the first sample row before removing sample data.
    row_styles = [copy(sheet.cell(FIRST_DATA_ROW, column)._style) for column in range(1, 15)]
    row_height = sheet.row_dimensions[FIRST_DATA_ROW].height
    # Existing rows 4 through the last row are only example rows and their old total.
    sheet.delete_rows(FIRST_DATA_ROW, sheet.max_row - FIRST_DATA_ROW + 1)
    for offset, style in enumerate(styles):
        row = FIRST_DATA_ROW + offset
        apply_row_style(sheet, row, row_styles, row_height)
        for column in range(1, 15):
            sheet.cell(row, column).value = None
        adjusted = style["quantity"] + 4
        sheet.cell(row, 3).value = style["emb"]
        sheet.cell(row, 4).value = style["main_body"]
        sheet.cell(row, 7).value = style["quantity"]
        sheet.cell(row, 8).value = adjusted
        sheet.cell(row, 9).value = round(adjusted * 0.933, 3)
        sheet.cell(row, 10).value = round(adjusted * 0.13, 3)
    sheet.cell(3, 7).value = None
    sheet.cell(3, 8).value = "QUANTITY"
    total_row = FIRST_DATA_ROW + len(styles)
    apply_row_style(sheet, total_row, row_styles, row_height)
    for column in range(1, 15):
        sheet.cell(total_row, column).value = None
    sheet.cell(total_row, 7).value = f"=SUM(G{FIRST_DATA_ROW}:G{total_row - 1})"
    sheet.cell(total_row, 8).value = f"=SUM(H{FIRST_DATA_ROW}:H{total_row - 1})"
    workbook.save(output_path)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Purchase-order PDF")
    parser.add_argument("--template", type=Path, default=Path("PLAN SHEET.xlsx"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.pdf.is_file() or not args.template.is_file():
        parser.error("PDF or template path does not exist.")
    styles = extract_local_styles(args.pdf)
    print(json.dumps(styles, indent=2))
    if args.dry_run:
        return 0
    output = args.output or Path("../output") / f"{args.pdf.stem}_output.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(args.template, output, styles)
    print(f"Wrote {len(styles)} styles to {output.resolve()}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
