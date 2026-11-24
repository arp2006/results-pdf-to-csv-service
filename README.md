# Mumbai University Results PDF → CSV Service

A FastAPI microservice that takes a **Mumbai University semester result PDF** (Office Register format) and extracts every student's marks into a clean, structured CSV — with one row per student and one column per subject component.

> **Tested against:** I.T., Semester I, Winter 2025 Office Register layout.  
> Should work for other branches/semesters since parsing is position-based, but worth spot-checking any new register type.

---

## Features

- Parses text-based Mumbai University result PDFs (via `pdfplumber`)
- Extracts seat number, name, gender, MU code, status, SGPA, result, and per-subject marks
- Splits subjects into their components — `T1`, `O1`, `E1`, `I1` — plus a computed `TOT` column per subject
- Three response formats: **JSON**, **CSV download**, or **ZIP** (regular + repeater in separate files)
- Filter by student status: `all`, `regular`, or `repeater`
- Fully Dockerised; interactive API docs at `/docs`

---

## Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.x + Uvicorn |
| PDF parsing | pdfplumber |
| Containerisation | Docker + Docker Compose |
| Python | 3.12 (Alpine) |

---

## Quick Start

### With Docker (recommended)

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`.

### Without Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --reload
```

---

## API Endpoints

### `GET /`
Health check — returns a list of available endpoints.

---

### `POST /extract`
Upload a PDF and receive extracted results as **JSON**.

**Query params**

| Param | Values | Default |
|---|---|---|
| `status` | `all` · `regular` · `repeater` | `all` |

**Example**
```bash
curl -X POST "http://localhost:8000/extract?status=regular" \
  -F "file=@result.pdf"
```

**Response**
```json
{
  "filename": "result.pdf",
  "filter": "regular",
  "total_students": 120,
  "regular_students": 105,
  "repeater_students": 15,
  "columns": ["seat_no", "name", "status", "gender", "mu_code", "result", "sgpa", "Applied Physics (E1)", "..."],
  "data": [{ "seat_no": "1234567", "name": "JOHN DOE", ... }]
}
```

---

### `POST /extract/csv`
Upload a PDF and **download** the results as a CSV file.

**Query params** — same `status` filter as above.

**Example**
```bash
curl -X POST "http://localhost:8000/extract/csv?status=all" \
  -F "file=@result.pdf" \
  -o results.csv
```

Downloaded file is named `results.csv`, `results_regular.csv`, or `results_repeater.csv` depending on the filter.

---

### `POST /extract/zip`
Upload a PDF and **download a ZIP** containing two CSVs:
- `results_regular.csv` — regular students
- `results_repeater.csv` — repeater students

**Example**
```bash
curl -X POST "http://localhost:8000/extract/zip" \
  -F "file=@result.pdf" \
  -o results.zip
```

---

## CSV Output Format

| Column | Description |
|---|---|
| `seat_no` | Exam seat number |
| `name` | Student full name |
| `status` | `Regular` or `Repeater` |
| `gender` | `MALE` or `FEMALE` |
| `mu_code` | MU code (e.g. `(MU12345)`) |
| `result` | `PASS` or `FAIL` |
| `sgpa` | Semester GPA |
| `{Subject} (T1)` | Theory internal marks (if present) |
| `{Subject} (E1)` | Theory external / end-sem marks (if present) |
| `{Subject} (O1)` | Oral marks (if present) |
| `{Subject} (I1)` | Internal / TW marks (if present) |
| `{Subject} (TOT)` | Sum of all present components for that subject |

Only components that actually appear in the PDF get columns — no empty columns for absent components.

---

## Standalone CLI Usage

`pdftocsv.py` can also be run directly to produce a CSV on disk without the API:

```bash
python pdftocsv.py result.pdf output.csv
```

---

## Error Responses

| Code | Reason |
|---|---|
| `400` | File is not a PDF, or the uploaded file is empty |
| `422` | PDF parsed successfully but zero records extracted, or the parser crashed |

---

## Known Limitations

- **Scanned / image PDFs are not supported.** The service requires a text-based PDF; OCR is not included.
- Pass/fail-only subjects (e.g. Induction cum Universal Human Values) produce blank cells rather than a numeric score.
- Subject names are read from the first page only. A structurally different page later in the document would fall back to raw subject codes.

---

## Project Structure

```
.
├── api.py                  # FastAPI app and endpoints
├── pdftocsv.py             # Core PDF parsing logic
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── ARCHITECTURE.md         # Deep-dive into the parsing algorithm
├── postman_collection.json # Ready-to-import Postman collection
└── results_example.csv     # Sample output
```

---

## Interactive Docs

Once running, visit **http://localhost:8000/docs** for the auto-generated Swagger UI where you can upload PDFs and test all endpoints directly in the browser.
