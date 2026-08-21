"""Single-server FastAPI application for PDF-to-Excel conversion."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from extract_to_plan_sheet import build_workbook, extract_local_styles

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = APP_DIR / "PLAN SHEET.xlsx"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="PDF to Plan Sheet", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def download_filename(value: str) -> str:
    """Convert an entered name into a safe attachment filename."""
    name = Path(value.strip()).name
    name = re.sub(r"[^A-Za-z0-9 ._-]", "_", name).strip(" .")
    if not name:
        name = "plan_sheet"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return name[:180]


def remove_workdir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html", media_type="text/html")


@app.post("/api/convert")
async def convert_pdf(
    background_tasks: BackgroundTasks,
    pdf: UploadFile = File(...),
    download_name: str = Form("plan_sheet"),
) -> FileResponse:
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    contents = await pdf.read()
    if not contents.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF must be 25 MB or smaller.")
    if not TEMPLATE_PATH.is_file():
        raise HTTPException(status_code=500, detail="PLAN SHEET.xlsx template is missing from the server.")

    workdir = Path(tempfile.mkdtemp(prefix="plan-sheet-"))
    source_pdf = workdir / "source.pdf"
    result_xlsx = workdir / "result.xlsx"
    try:
        source_pdf.write_bytes(contents)
        styles = extract_local_styles(source_pdf)
        build_workbook(TEMPLATE_PATH, result_xlsx, styles)
    except RuntimeError as exc:
        remove_workdir(workdir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        remove_workdir(workdir)
        raise HTTPException(status_code=500, detail="Could not create the Excel workbook.") from exc

    background_tasks.add_task(remove_workdir, workdir)
    return FileResponse(
        result_xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_filename(download_name),
        background=background_tasks,
    )
