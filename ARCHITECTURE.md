# How This Service Works

This service takes a **Mumbai University semester result PDF** (the kind the university officially publishes — called an "Office Register") and converts it into a clean, structured **CSV file** where every student is one row and every subject is a column.

---

## The Big Picture

```
PDF Upload
    │
    ▼
┌─────────────┐     POST /extract        ┌──────────────────────────────┐
│   api.py    │ ◄──────────────────────► │  Any HTTP client             │
│  (FastAPI)  │     POST /extract/csv    │  (Postman, frontend, etc.)   │
│             │     POST /extract/zip    └──────────────────────────────┘
└──────┬──────┘
       │ calls extract(pdf_path)
       ▼
┌─────────────┐
│ pdftocsv.py │  ◄── the brain of the whole thing
└──────┬──────┘
       │
       ▼
  records + fieldnames
       │
       ▼
  JSON / CSV / ZIP  (returned to caller)
```

There are two files doing all the work:

| File | Role |
|---|---|
| `pdftocsv.py` | Reads and parses the PDF, extracts all student data |
| `api.py` | Wraps the parser in a web API so it can be called over HTTP |

---

## Part 1: Parsing the PDF (`pdftocsv.py`)

### Why not just read it as text?

The PDF's columns are **position-based**, not whitespace-delimited. A simple text extraction would smash everything into an unstructured blob. So instead, we use **`pdfplumber`** to extract every word along with its exact X/Y coordinates on the page — essentially treating the PDF like a visual table.

---

### Step 1 — Group words into rows

```
group_rows(words, tol=2.5)
```

Words at nearly the same Y position (within 2.5 points) are grouped into the same visual row. This handles slight vertical jitter in PDF rendering.

**Result:** a dict of `{ y_position → [list of words sorted left-to-right] }`

---

### Step 2 — Find the subject code row

```
find_header_row(rows, sorted_tops)
```

The PDF's header has a row containing **5-digit subject codes** like `10411`, `10412`, `10413`, ...

This function scans all rows until it finds one with 8 or more such codes. Once found, it records each code's **X position** (which column it lives in).

```
10411   10412   10413   10414   ...
  │       │       │       │
  X=142  X=210  X=278  X=346  ...  ← these X positions are stored
```

---

### Step 3 — Read subject names

```
build_subject_names(rows, sorted_tops, code_row_top, code_positions)
```

Above the code row, the PDF has the **full subject names** (e.g. `Applied Physics`, `Engineering Mechanics`). This function reads those header rows and matches each word to the nearest subject column using the X positions from Step 2.

It also:
- **Strips grading tags** like `(THEORY)` or `(TERM WORK AND ORAL)` from the name, since those get added back later per-component anyway
- **Deduplicates names** — if two subjects have the same name after stripping (e.g. a theory + its lab), the second one gets prefixed with `"Lab "`

> This only runs once, from the first page. The header is identical on every page, so there's no need to re-parse it.

---

### Step 4 — Parse each student's data

For each page, the script scans rows top-to-bottom looking for a **seat number** (a 6–8 digit number in the leftmost column). When found, that's the start of a student block.

**From the seat row itself**, it reads:
- `seat_no` — the seat number
- `name` — words between X=100 and X=260
- `status` — one of `Regular`, `Repeater`, `ATKT`, etc.
- `gender` — `MALE` or `FEMALE`
- `mu_code` — the enrollment code like `MU0341120YY0212345` (sometimes split across two lines — the script handles rejoining it)

**From the rows below** (until the next student's seat number), it reads:

| Row label | What it contains |
|---|---|
| `T1` | Term Work marks |
| `O1` | Oral marks |
| `E1` | External exam marks |
| `I1` | Internal marks |
| `TOT` | The GPA/SGPA (grabbed from the rightmost decimal on this row) |

Each mark value is matched to the nearest subject column using the X positions from Step 2 (with an 8-point tolerance). Pass/Fail result is also extracted by scanning for words starting with `PASS` or `FAIL` — stored as `PASS` or `FAILED`.

---

### Step 5 — Build the final columns

After parsing all students, the script figures out **which mark components actually appeared** for each subject across the whole document (e.g. some subjects only have `E1` + `I1`, others only have `T1`).

For each subject, it creates columns like:
```
Applied Physics (T1)   Applied Physics (E1)   Applied Physics (I1)   Applied Physics (TOT)
```

The `TOT` column is **computed** by summing whichever components were present for that student+subject combination.

---

### Output: `extract(pdf_path)` returns

```python
records   # list of dicts, one per student
fieldnames  # ordered list of column names for the CSV
```

A sample record looks like:
```python
{
    "seat_no": "1234567",
    "name": "LASTNAME MIDDLENAME FIRSTNAME",
    "gender": "MALE",
    "status": "Regular",
    "mu_code": "MU0341120YY0212345",
    "gpa": "9.00000",
    "total": "616",
    "result": "PASS",
    "Applied Physics (E1)": 59.0,
    "Applied Physics (I1)": 15.0,
    "Applied Physics (TOT)": 74.0,
    # ... all other subjects ...
}
```

---

## Part 2: The API (`api.py`)

Built with **FastAPI**. It accepts a PDF upload and returns the extracted data in three formats:

### Endpoints

| Endpoint | Returns |
|---|---|
| `POST /extract` | JSON with all student records |
| `POST /extract/csv` | Downloadable `.csv` file |
| `POST /extract/zip` | A `.zip` with two CSVs: `results_regular.csv` + `results_repeater.csv` |

All three endpoints accept an optional `?status=` query param:
- `all` (default) — every student
- `regular` — only Regular/Fresh students
- `repeater` — only Repeaters/ATKT students

### How it handles the upload

1. Validates that the uploaded file is a `.pdf`
2. Saves it to a **temp file** on disk (pdfplumber needs a file path, not raw bytes)
3. Calls `extract(temp_path)` from `pdftocsv.py`
4. **Deletes the temp file** immediately after (in a `finally` block, so it's always cleaned up)
5. Returns the data in the requested format

If no records are extracted (wrong PDF format, scanned image, etc.), it returns a `422` error with a clear message instead of an empty/garbage response.

---

## Function Reference (`pdftocsv.py`)

A detailed breakdown of every function — what it does, how it works, and why it's written that way.

---

### `group_rows(words, tol=2.5)`

**What:** Groups a flat list of words (each with an X/Y position) into visual rows.

**How:**
- Iterates over every word.
- For each word, checks if its `top` (Y coordinate) is within `tol` (2.5 points) of any already-seen row's Y.
- If yes → adds the word to that row. If no → starts a new row keyed at this word's Y.
- Finally, sorts each row's words left-to-right by `x0`.

**Why `tol=2.5`:** PDF renderers don't guarantee pixel-perfect Y alignment even for words on the "same line". A small tolerance absorbs that jitter without accidentally merging adjacent rows.

**Returns:** `{ y_position: [words sorted left→right] }`

---

### `nearest_code(x0, code_positions, tol=8)`

**What:** Given an X position of a mark value, finds which subject column it belongs to.

**How:**
- Iterates over all known subject codes and their X positions.
- Finds the code whose X is closest to `x0`.
- Only returns it if the distance is within `tol` (8 points) — otherwise returns `None` (the value doesn't belong to any known column).

**Why needed:** Mark values on `T1`/`E1`/etc. rows are not labeled — they're just numbers floating at an X position. This function is how we know "this `59.0` belongs to Applied Physics and not Engineering Mechanics".

**Returns:** The subject code string (e.g. `"10412"`), or `None` if no column is close enough.

---

### `parse_mark(text)`

**What:** Converts a raw text token from the PDF into a numeric mark value, or `None` if it's not a real mark.

**How:**
- Strips a trailing `+` character (which the PDF uses to flag carried-forward marks).
- Checks if what remains is a valid number (`digits` or `digits.digits`).
- If yes → returns it as a `float`. If no → returns `None`.

**Why:** The PDF contains non-numeric tokens on mark rows — things like `AB` (absent), `...`, or stray labels. Returning `None` for those lets the caller simply skip them rather than crashing or storing garbage.

**Returns:** `float` or `None`

---

### `find_header_row(rows, sorted_tops)`

**What:** Locates the row that lists all the 5-digit subject codes, and records each code's X position.

**How:**
- Scans rows top-to-bottom.
- For each row, counts words that are exactly 5 digits (`\d{5}`).
- The first row with **8 or more** such codes is considered the header row.

**Why 8+:** A threshold of 8 avoids false positives from rows that might coincidentally contain a few 5-digit numbers (seat numbers are 6–8 digits, so they're already excluded by the regex).

**Returns:** `(header_row_y, { "10411": x0, "10412": x0, ... })` — or `(None, {})` if no header row is found (e.g. a legend/cover page).

---

### `build_subject_names(rows, sorted_tops, code_row_top, code_positions)`

**What:** Reads the subject *names* from the header block sitting above the code row.

**How:**
1. **Finds the cutoff row** — scans rows *below* the code row until it hits one containing a known stop-word (`External`, `TOT`, `GP`, etc.) or a fraction pattern like `(25/25)`. That's where student data begins; everything between the code row and this cutoff is part of the header.
2. **Divides the page into column bands** — uses each subject code's X position to define a horizontal band. The band for subject N runs from its X to just before subject N+1's X. The band width is estimated using the **median gap** between consecutive codes (handles uneven spacing).
3. **Collects words** in each band that fall between the code row and the cutoff row, skipping the code itself, colons, and known stop-words.
4. **Joins the words** top-to-bottom, left-to-right into a full name string.
5. **Strips grading tags** using a regex: removes trailing `(THEORY)`, `(TERM WORK AND ORAL)`, etc. (they get re-added per-component in column names later).
6. **Deduplicates names** — if two subjects resolve to the same name after stripping (e.g. a theory course and its practical), the second one is prefixed with `"Lab "`.

**Why only run once:** The subject header is identical on every page. Running it once from the first page with a table is sufficient and avoids redundant work.

**Returns:** `{ "10411": "Applied Physics", "10412": "Engineering Mechanics", ... }`

---

### `extract(pdf_path)`

**What:** The main parser. Opens the PDF, reads every page, and returns all student records with their marks.

**How — high level:**
1. Opens the PDF with `pdfplumber`.
2. For each page:
   - Extracts all words with positions.
   - Groups them into rows (`group_rows`).
   - Finds the header row (`find_header_row`). Skips the page if none found.
   - Builds subject names on the first page that has a table (`build_subject_names`).
   - Scans rows top-to-bottom for student blocks.
3. After all pages, assembles the final column list and computes per-student totals.

**How — student block parsing:**

When a row has a **6–8 digit number at X < 90**, that's a seat number → start of a student block.

From the **seat row**, it reads:
- `seat_no` — the seat number token itself
- `name` — words between X=100 and X=260 that aren't status words
- `status` — first word matching `STATUS_WORDS` (`Regular`, `Repeater`, etc.)
- `gender` — first word matching `GENDER_WORDS` (`MALE`/`FEMALE`) that appears after the status word
- `result` — `PASS` or `FAILED`w
- `mu_code` — a token starting with `(MU`. Because MU codes sometimes wrap to the next line (the closing `)` appears on a separate row), the script looks ahead up to 2 rows to find and rejoin the closing paren.

From **subsequent rows** (until the next seat number):
- Rows starting with `T1`, `O1`, `E1`, or `I1` → mark rows. Each value on that row is matched to the nearest subject column via `nearest_code`, parsed via `parse_mark`, and stored in `subject_components[code][label]`.
- Row starting with `TOT` (at X < 60) → GPA row. The rightmost decimal number on this row is the SGPA.
- Any row → scanned for `(NNN)` (parenthesized integer) to extract the total marks, and for words starting with `PASS`/`FAIL` to extract the result.

**How — column assembly (after all pages):**

- For each subject code, checks which of `T1 / O1 / E1 / I1` actually appeared anywhere in the document for that subject (`component_present` dict). Only those get columns.
- Generates column names as `"{Subject Name} ({Component})"`, e.g. `Applied Physics (E1)`.
- Appends a `{Subject Name} (TOT)` column whose value is the **sum of all present components** for that student+subject. If the student has no data for a subject, `TOT` is left blank.

**Returns:** `(records, fieldnames)`
- `records` — list of dicts, one per student, keys = fieldnames
- `fieldnames` — ordered list of column names (seat_no, name, ... then all subject columns)

---

### `write_csv(path, records, fieldnames)`

**What:** Writes the extracted records to a CSV file on disk.

**How:** Standard Python `csv.DictWriter` — writes the header row, then one row per record. Missing fields default to `""` via `.get(fn, "")`.

**Note:** This is only used when running `pdftocsv.py` directly (standalone mode). The API (`api.py`) uses its own `generate_csv_string()` to produce CSV in memory instead of writing to disk.

---

## Function Reference (`api.py`)

---

### `generate_csv_string(records, fieldnames)`

**What:** Produces a CSV as an in-memory string (no disk I/O).

**How:** Writes into a `StringIO` buffer using `csv.DictWriter`, then returns `buffer.getvalue()`. The API streams this directly to the HTTP response.

---

### `parse_pdf_upload(file)`

**What:** Shared helper used by all three API endpoints. Handles validation, temp file management, and calling the parser.

**How:**
1. Checks the file has a `.pdf` extension — raises `HTTP 400` if not.
2. Reads all bytes from the upload — raises `HTTP 400` if empty.
3. Writes bytes to a **named temp file** (pdfplumber needs a path, not raw bytes).
4. Calls `extract(temp_path)`.
5. In the `finally` block, **always deletes the temp file** — even if parsing crashed.
6. If `extract()` returns zero records, raises `HTTP 422` with a descriptive message.
7. If any other exception is raised, wraps it in `HTTP 422`.

**Returns:** `(records, fieldnames)`

---

### `extract_results()` — `POST /extract`

Calls `parse_pdf_upload`, filters by `?status=`, returns a **JSON response** with:
- Summary counts (total / regular / repeater)
- The column list
- The full data array

---

### `extract_results_csv()` — `POST /extract/csv`

Calls `parse_pdf_upload`, filters by `?status=`, generates a CSV string via `generate_csv_string`, and returns it as a **streaming download** (`text/csv`) with an appropriate filename.

---

### `extract_results_zip()` — `POST /extract/zip`

Calls `parse_pdf_upload`, splits records into regular + repeater, generates **two CSVs**, packs them into a **ZIP archive** in memory (`BytesIO`), and returns that as a streaming download (`application/zip`).

---

## Known Limitations

- **Scanned PDFs won't work.** The service needs a text-based PDF. If the PDF is a scan (image-only), `pdfplumber` can't read the text — OCR would be needed first.
- **Pass/fail-only subjects come out blank**, not zero (e.g. "Induction cum Universal Human Values").
- **Subject name reading happens once** from the first page. If a later page has a genuinely different header structure, those subjects would just get their raw code as the name.
- **Tested against one layout** (I.T., Semester I, Winter 2025). Different branches/semesters should work since parsing is position-based — but worth spot-checking a few rows whenever a completely new type of register is used.
