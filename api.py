from enum import Enum
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import tempfile
import csv
import io
import zipfile

from pdftocsv import extract

app = FastAPI(
    title="Mumbai University PDF Result API",
    description="Upload a Mumbai University result-register PDF and extract student results.",
    version="1.1.0",
)

# Allows your frontend (React/HTML/etc.) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResultStatus(str, Enum):
    ALL = "all"
    REGULAR = "regular"
    REPEATER = "repeater"


def generate_csv_string(records, fieldnames) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        writer.writerow({field: record.get(field, "") for field in fieldnames})
    return output.getvalue()


async def parse_pdf_upload(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp:
            temp.write(pdf_bytes)
            temp_path = temp.name

        records, fieldnames = extract(temp_path)

        if not records:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No student records were extracted. "
                    "Make sure the PDF matches the expected Mumbai University "
                    "OFFICE REGISTER format and is text-based, not scanned."
                ),
            )
        return records, fieldnames
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse the PDF: {str(e)}",
        )
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


@app.get("/")
def root():
    return {
        "message": "PDF Result API is running",
        "docs": "/docs",
        "endpoints": {
            "extract_json": "POST /extract?status=[all|regular|repeater]",
            "extract_csv": "POST /extract/csv?status=[all|regular|repeater]",
            "extract_zip": "POST /extract/zip",
        },
    }


@app.post("/extract")
async def extract_results(
    file: UploadFile = File(...),
    status: ResultStatus = Query(
        ResultStatus.ALL,
        description="Filter records: 'all', 'regular', or 'repeater'",
    ),
):
    """Upload a result-register PDF and receive extracted records as JSON."""
    records, fieldnames = await parse_pdf_upload(file)

    regular = [r for r in records if r.get("status") != "Repeater"]
    repeater = [r for r in records if r.get("status") == "Repeater"]

    if status == ResultStatus.REGULAR:
        data = regular
    elif status == ResultStatus.REPEATER:
        data = repeater
    else:
        data = records

    return {
        "filename": file.filename,
        "filter": status.value,
        "total_students": len(records),
        "regular_students": len(regular),
        "repeater_students": len(repeater),
        "columns": fieldnames,
        "data": data,
    }


@app.post("/extract/csv")
async def extract_results_csv(
    file: UploadFile = File(...),
    status: ResultStatus = Query(
        ResultStatus.ALL,
        description="Filter CSV results: 'all', 'regular', or 'repeater'",
    ),
):
    """Upload a result-register PDF and download the extracted data as CSV."""
    records, fieldnames = await parse_pdf_upload(file)

    regular = [r for r in records if r.get("status") != "Repeater"]
    repeater = [r for r in records if r.get("status") == "Repeater"]

    if status == ResultStatus.REGULAR:
        export_records = regular
        filename = "results_regular.csv"
    elif status == ResultStatus.REPEATER:
        export_records = repeater
        filename = "results_repeater.csv"
    else:
        export_records = records
        filename = "results.csv"

    csv_content = generate_csv_string(export_records, fieldnames)

    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.post("/extract/zip")
async def extract_results_zip(file: UploadFile = File(...)):
    """Upload a result-register PDF and download a ZIP containing both regular and repeater CSV files."""
    records, fieldnames = await parse_pdf_upload(file)

    regular = [r for r in records if r.get("status") != "Repeater"]
    repeater = [r for r in records if r.get("status") == "Repeater"]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("results_regular.csv", generate_csv_string(regular, fieldnames))
        zip_file.writestr("results_repeater.csv", generate_csv_string(repeater, fieldnames))

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="results.zip"'
        },
    )
