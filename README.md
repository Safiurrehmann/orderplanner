# PDF to PLAN SHEET

Converts a garment purchase-order PDF to an Excel sheet with one style per row using the built-in parser for this PO layout.

| Column | Value |
| --- | --- |
| C — EMB | First three letters of the PDF style number, uppercase (`ARK`) |
| D — MAIN BODY | Printed color code (`CRI - Crimson` → `CRI`; `LTB - Light Blue` → `LTB`) |
| G — unlabeled | Actual PDF quantity |
| H — QUANTITY | Adjusted quantity: `G + 4` |
| I — FLEECE | `H × 0.933` |
| J — 2 X 1 RIB | `H × 0.13` |

All other style-row fields remain blank. Existing values in the template header remain unchanged.

## Setup

```bash
cd pdf_to_plan_sheet
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the website

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The homepage is served from `/`; upload a PDF, enter any download filename, and the resulting Excel sheet downloads directly.

## Run the script

```bash
python extract_to_plan_sheet.py '../PurchaseOrder 73491 Flannigan.pdf'
```

The workbook is written to `output/`. Use `--dry-run` to inspect rows first. The previous Groq implementation remains in the script but is deliberately disabled for both the website and command-line flow.
