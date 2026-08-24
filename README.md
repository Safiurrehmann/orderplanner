# PDF to Plan Sheet v2

This app makes a production plan workbook through a two-station guided flow in the browser
(`http://localhost:8000`) -- Station 2 only unlocks once Station 1 finishes, and the
matching results are shown inline on the page, not as a separate download.

1. **Station 1 -- Purchase order.** Add one or more Royce purchase-order PDFs. Each produces
   its own worksheet, named `WS<PO number>`, containing every line item from that PO.
2. **Station 2 -- Artwork.** Add the folder of per-contract spec-sheet images (JPG/PNG). The
   app matches each filename to the full contract code (column B), crops the isolated
   front/back embroidery art out of the spec sheet, and drops it into that contract's row --
   for every row that shares the contract, including duplicate styles in different colours
   and across POs. A manifest (matched / needs artwork / uploaded twice / couldn't read /
   didn't match anything) renders right there on the page when it's done.

Every worksheet is cloned from the `WS72823` sheet in `PLAN SHEET.xlsx`, so its formatting,
column widths, print settings, and the `H+10` / fleece / rib formulas all come straight from
the blueprint. Each generated row contains the full contract code, short EMB code, colour
code, original quantity, and those formulas; the print area is stretched to cover however
many rows (plus totals) that PO actually has.

## Artwork rules

- Each spec-sheet image is a Royce Apparel / Pressbox "tech pack" export: garment mockup
  photos up top, and two bordered boxes lower on the page holding the *actual* isolated
  embroidery art -- a compact front/chest logo on the left, a wide back wordmark on the
  right. The app crops those two boxes specifically; the mockup photos are ignored.
- Filenames must contain the full contract code somewhere (case-insensitive), e.g.
  `CAL65393FGE_FlanniganMocksville_IVR.jpg` matches `CAL65393FGE`. The same crop is reused
  for every row that shares that contract code, including duplicate styles in different
  colours and across different POs in the same upload.
- The crop boxes are calibrated pixel positions scaled to each image's own size, so they
  only work reliably against this template's layout. A file whose aspect ratio is too far
  off the expected page proportions is reported under `unreadable` instead of guessing.
- Missing, unused, duplicate, or unreadable artwork is left blank on the sheet and shown
  inline in Station 2's manifest (matched / needs artwork / uploaded twice / couldn't read /
  didn't match anything) once matching finishes -- there's a "Print this report" action if
  you want a paper copy, but nothing to download separately.

## Run

```bash
cd pdf_to_plan_sheet
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and follow the two stations in order -- Station 2 stays locked
until Station 1 logs a purchase order.
