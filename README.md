# PDF to Plan Sheet v2

This app makes a production plan workbook through a two-station guided flow in the browser
(`http://localhost:8000`) -- Station 2 only unlocks once Station 1 finishes, and the
matching results are shown inline on the page, not as a separate download.

1. **Station 1 -- Purchase order.** Add one or more Royce purchase-order PDFs. Each produces
   its own worksheet, named `WS<PO number>`, containing every line item from that PO.
2. **Station 2 -- Artwork package.** Upload the complete artwork package as one ZIP. The app
   safely unpacks it, searches every folder, matches PDF/PSD/raster artwork to each team and
   embroidery position, and places it into every row sharing that contract. Full spec-sheet
   JPG/PNG files remain available as a fallback. A position-level manifest shows exactly
   what was inserted, missing, ambiguous, unreadable, or handled through JPG fallback.

Every worksheet is cloned from the `WS72823` sheet in `PLAN SHEET.xlsx`, so its formatting,
column widths, print settings, and the `H+10` / fleece / rib formulas all come straight from
the blueprint. Each generated row contains the full contract code, short EMB code, colour
code, original quantity, and those formulas; the print area is stretched to cover however
many rows (plus totals) that PO actually has.

## Artwork package rules

- Upload one `.zip` containing the package exactly as received. Folders do not need to be
  renamed or reorganized. Names such as `Back`, `Chest`, `Hood`, or `Artwork` are matching
  hints rather than a rigid directory structure.
- Team matching accepts a full contract code or a unique three-letter team code embedded
  in a filename such as `APFGNUNC`, `EMLNFUNC`, or `EMBLUNC`.
- Source preference is a decodable PSD composite, then PDF, then isolated raster artwork.
  If a PSD cannot be decoded, its corresponding PDF is tried automatically.
- Flannigan requires one Front position; Mocktail requires Back and Front; Belvedere
  requires Back, Front/Chest, and Hood.
- Full spec-sheet JPG/PNG files are the fallback. The app detects the two lower artwork
  panel borders rather than relying on fixed coordinates. This supports the different
  Belvedere and Flannigan layouts without cutting off artwork or leaking the neighbouring
  panel into the crop. Files whose borders cannot be found are reported as unreadable.
- Missing, unused, duplicate, or unreadable artwork is left blank on the sheet and shown
  inline in Station 2's manifest (matched / needs artwork / uploaded twice / couldn't read /
  didn't match anything) once matching finishes -- there's a "Print this report" action if
  you want a paper copy, but nothing to download separately.
- ZIP limits are 75 MB compressed, 300 MB expanded, and 500 archive entries. Unsafe,
  encrypted, malformed, or nested archives are rejected.

## Run

```bash
cd pdf_to_plan_sheet
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and follow the two stations in order -- Station 2 stays locked
until Station 1 logs a purchase order, then accepts the complete artwork ZIP.
