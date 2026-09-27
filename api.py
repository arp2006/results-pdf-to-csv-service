from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import tempfile
import csv
import io

from pdftocsv import extract

app = FastAPI(
    title="Mumbai University PDF Result API",
    description="Upload a Mumbai University result-register PDF and extract student results.",
    version="1.0.0",
)

# Allows your frontend (React/HTML/etc.) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "PDF Result API is running",
        "docs": "/docs",
        "endpoint": "POST /extract",
    }


@app.post("/extract")
async def extract_results(file: UploadFile = File(...)):
    """Upload a result-register PDF and receive extracted records as JSON."""
    if not file.filename.lower().endswith(".pdf"):
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

        return {
            "filename": file.filename,
            "total_students": len(records),
            "columns": fieldnames,
            "data": records,
        }

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


@app.post("/extract/csv")
async def extract_results_csv(file: UploadFile = File(...)):
    """Upload a result-register PDF and download the extracted data as CSV."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await file.read()
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp:
            temp.write(pdf_bytes)
            temp_path = temp.name

        records, fieldnames = extract(temp_path)

        if not records:
            raise HTTPException(
                status_code=422,
                detail="No student records were extracted from the PDF.",
            )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for record in records:
            writer.writerow({field: record.get(field, "") for field in fieldnames})

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="results.csv"'
            },
        )

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
