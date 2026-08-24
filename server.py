"""Two-stage FastAPI application for multi-PO purchase-order plan sheets."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import load_workbook

from extract_to_plan_sheet import (
    FIRST_DATA_ROW,
    add_artwork_to_row,
    build_workbook,
    extract_artwork_crops,
    extract_purchase_order,
    find_known_code,
)

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = APP_DIR / "PLAN SHEET.xlsx"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PO_FILES = 25
MAX_ARTWORK_FILES = 200
IMAGE_MAGIC_BYTES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")  # JPEG, PNG
REPORT_KEYS = ("matched", "missing", "unused", "duplicate", "unreadable")
sessions: dict[str, Path] = {}

app = FastAPI(title="PDF to Plan Sheet", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def safe_name(value: str, suffix: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 ._+-]", "_", Path(value.strip()).name).strip(" .") or "plan_sheet"
    return (name if name.lower().endswith(suffix) else name + suffix)[:180]


async def save_upload(upload: UploadFile, directory: Path, name: str, magic_bytes: tuple[bytes, ...], kind: str) -> Path:
    if not upload.filename:
        raise HTTPException(status_code=400, detail=f"Every {kind} upload needs a filename.")
    contents = await upload.read()
    if not any(contents.startswith(magic) for magic in magic_bytes):
        raise HTTPException(status_code=400, detail=f"{upload.filename} is not a valid {kind} file.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the 25 MB limit.")
    path = directory / name
    path.write_bytes(contents)
    return path


async def save_pdf(upload: UploadFile, directory: Path, name: str) -> Path:
    return await save_upload(upload, directory, name, (b"%PDF",), "PDF")


async def save_image(upload: UploadFile, directory: Path, name: str) -> Path:
    return await save_upload(upload, directory, name, IMAGE_MAGIC_BYTES, "JPG/PNG")


def get_session(session_id: str) -> Path:
    directory = sessions.get(session_id)
    if not directory or not directory.is_dir():
        raise HTTPException(status_code=404, detail="This workbook session has expired. Create the plan sheet again.")
    return directory


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html", media_type="text/html")


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    """Liveness/readiness check for the host (e.g. Render) -- cheap, no session state involved."""
    if not TEMPLATE_PATH.is_file():
        raise HTTPException(status_code=503, detail="The workbook blueprint is missing from the server.")
    return {"status": "ok"}


def default_workbook_name(sheet_titles: list[str]) -> str:
    label = " + ".join(sheet_titles) if len(sheet_titles) <= 3 else f"{sheet_titles[0]} + {len(sheet_titles) - 1} more"
    return safe_name(f"Plan Sheet - {label}", ".xlsx")


@app.post("/api/convert")
async def convert_pdf(pdfs: list[UploadFile] = File(...)) -> dict[str, object]:
    if not TEMPLATE_PATH.is_file():
        raise HTTPException(status_code=500, detail="The workbook blueprint is missing from the server.")
    if not pdfs:
        raise HTTPException(status_code=400, detail="Add at least one purchase-order PDF.")
    if len(pdfs) > MAX_PO_FILES:
        raise HTTPException(status_code=413, detail=f"Add at most {MAX_PO_FILES} purchase-order PDFs at once.")
    session_id = uuid.uuid4().hex
    workdir = Path(tempfile.mkdtemp(prefix="plan-sheet-"))
    try:
        purchase_orders: list[tuple[str, list[dict]]] = []
        seen_po_numbers: dict[str, str] = {}
        for index, upload in enumerate(pdfs):
            source = await save_pdf(upload, workdir, f"po_{index}.pdf")
            po_number, rows = extract_purchase_order(source)
            if po_number in seen_po_numbers:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Purchase Order {po_number} showed up twice — in "
                        f"{seen_po_numbers[po_number]} and {upload.filename}. "
                        "Combine them into one PDF, or remove one, then try again."
                    ),
                )
            seen_po_numbers[po_number] = upload.filename or source.name
            purchase_orders.append((po_number, rows))
        output = workdir / "plan_sheet.xlsx"
        result = build_workbook(TEMPLATE_PATH, output, purchase_orders)
        sheet_rows = result["sheets"]
        workbook_name = default_workbook_name(list(sheet_rows.keys()))
        (workdir / "meta.json").write_text(
            json.dumps({
                "name": workbook_name,
                "sheets": sheet_rows,
                "artwork_box": result["artwork_box"],
            }),
            encoding="utf-8",
        )
        sessions[session_id] = workdir
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except RuntimeError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Could not create the Excel workbook.") from exc
    return {
        "session_id": session_id,
        "download_url": f"/api/session/{session_id}/workbook",
        "workbook_name": workbook_name,
        "sheets": [
            {"title": title, "po_number": po_number, "row_count": len(rows)}
            for (po_number, rows), title in zip(purchase_orders, sheet_rows.keys())
        ],
        "row_count": sum(len(rows) for rows in sheet_rows.values()),
    }


@app.post("/api/enrich")
async def enrich_workbook(session_id: str = Form(...), artwork: list[UploadFile] = File(...)) -> dict[str, object]:
    if not artwork:
        raise HTTPException(status_code=400, detail="Add at least one spec-sheet image before matching.")
    if len(artwork) > MAX_ARTWORK_FILES:
        raise HTTPException(status_code=413, detail=f"Add at most {MAX_ARTWORK_FILES} artwork files at once.")

    workdir = get_session(session_id)
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    known_contracts = {
        str(row["contract"]).upper()
        for rows in meta["sheets"].values()
        for row in rows
        if row.get("contract")
    }
    back_box = tuple(meta["artwork_box"]["back"])
    front_box = tuple(meta["artwork_box"]["front"])
    report: dict[str, list[str]] = {key: [] for key in REPORT_KEYS}

    # Each upload is one contract's spec-sheet image (JPG/PNG), matched by the
    # full contract code embedded in its filename -- not a per-side batch, since
    # one file holds both the front and back art (see extract_artwork_crops).
    upload_dir = workdir / "artwork"
    upload_dir.mkdir(exist_ok=True)
    by_contract: dict[str, list[tuple[str, Path]]] = {}
    for index, item in enumerate(artwork):
        filename = item.filename or f"artwork_{index}.jpg"
        path = await save_image(item, upload_dir, f"{index}.jpg")
        contract = find_known_code(filename, known_contracts)
        if not contract:
            report["unused"].append(filename)
            continue
        by_contract.setdefault(contract, []).append((filename, path))

    resolved: dict[str, tuple[bytes, bytes]] = {}
    accounted: set[str] = set()
    for contract, matches in sorted(by_contract.items()):
        accounted.add(contract)
        if len(matches) > 1:
            report["duplicate"].append(f"{contract}: " + ", ".join(name for name, _ in matches))
            continue
        filename, path = matches[0]
        crops = extract_artwork_crops(path)
        if crops is None:
            report["unreadable"].append(f"{contract} ({filename})")
            continue
        resolved[contract] = crops
        report["matched"].append(contract)
    report["missing"].extend(sorted(known_contracts - accounted))

    workbook = load_workbook(workdir / "plan_sheet.xlsx")
    for sheet in workbook.worksheets:
        for row in range(FIRST_DATA_ROW, sheet.max_row):
            contract = sheet.cell(row, 2).value
            if not contract:
                continue
            contract = str(contract).upper()
            if contract in resolved:
                front_bytes, back_bytes = resolved[contract]
                add_artwork_to_row(sheet, row, "F", back_bytes, back_box)
                add_artwork_to_row(sheet, row, "G", front_bytes, front_box)
    workbook.save(workdir / "completed_plan_sheet.xlsx")
    contract_count = len(known_contracts)
    return {
        "download_url": f"/api/session/{session_id}/completed",
        "report": report,
        "matched_count": len(report["matched"]),
        "contract_count": contract_count,
    }


@app.get("/api/session/{session_id}/workbook")
def download_workbook(session_id: str, name: Optional[str] = None) -> FileResponse:
    workdir = get_session(session_id)
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    filename = safe_name(name, ".xlsx") if name else meta["name"]
    return FileResponse(workdir / "plan_sheet.xlsx", filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/session/{session_id}/completed")
def download_completed(session_id: str, name: Optional[str] = None) -> FileResponse:
    workdir = get_session(session_id)
    path = workdir / "completed_plan_sheet.xlsx"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Add artwork before downloading the completed workbook.")
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    filename = safe_name(name, ".xlsx") if name else meta["name"]
    return FileResponse(path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
