# PDF Result-Register → CSV Extractor

## What this is
A Python script (`pdftocsv.py`) that parses a Mumbai University semester exam
result register PDF and outputs a CSV with one row per student:
seat number, name, MU enrollment code, per-subject marks, and SGPA.

The next step is to wrap this in an API so it can be called instead of run
by hand. This doc explains what the script does and what's safe to change.

## Input / Output
- **Input:** a text-based (non-scanned) PDF of this specific result-register
  format — one from the University of Mumbai's OFFICE REGISTER series
  (e.g. `SEM-I__I_T__WINTER_2025.pdf`). Each page has a header table
  listing subject codes/titles, followed by one block per student.
- **Output:** a CSV file, one row per student, with these columns:
  - `seat_no`, `name`, `mu_code`, `gpa`
  - one column per subject, named from the subject title found in the
    PDF's own header (e.g. `Applied Physics (THEORY)`), containing that
    student's total marks for that subject (blank if not applicable /
    pass-fail-only course)

## How it works (so you know what's safe to touch)
1. Extracts every word on every page with its (x, y) position using
   `pdfplumber` — this format doesn't parse reliably with plain text
   extraction because columns are position-based, not whitespace-delimited.
2. Groups words into visual rows by y-position, then finds the row
   listing the 5-digit subject codes to learn each subject's x-position
   (column).
3. Reads the subject *names* from the header rows above the code row,
   using the same x-position ranges (only done once, off the first page
   that has a table — the header repeats identically on every page).
4. For each student block (identified by a seat number in the leftmost
   column), it reads the `T1`/`O1`/`E1`/`I1` rows (term work / oral /
   external / internal marks) and sums whichever of those apply to each
   subject, matching each value to the nearest subject column.
5. GPA is read off the `TOT` row as the right-most decimal value on that
   line (this is the official SGPA field).
6. The MU enrollment code (`(MU##############)`) occasionally wraps
   across two lines in the source PDF — the script detects and rejoins
   this automatically.

## Known limitations
- Built and tested against one specific register layout (I.T., Semester I,
  Winter 2025, 53 pages, 100 students). Different branches/semesters
  *should* work unchanged since the parsing is entirely position-based,
  not hardcoded to specific subjects, but haven't been tested — worth
  spot-checking a few rows against the source PDF whenever an entirely
  new register is fed in.
- Scanned/image-only PDFs will not work — this needs OCR first, which
  isn't implemented here.
- Subjects that are pass/fail only with no numeric marks (in this PDF,
  "Induction cum Universal Human Values") come out blank, not zero.

## Dependencies
- Python 3.x
- `pip install pdfplumber` (only external dependency)

## Running it standalone
```bash
python3 pdftocsv.py
```
Edit the `PDF` and `OUT` variables at the top of the file to point at your
input PDF and desired output path. `extract()` can also be imported and
called directly — it returns `(records, fieldnames)` as a Python list of
dicts, without touching the filesystem, which is probably the easiest
entry point for wrapping this in an API (see below).

## For the API build — you have full flexibility here
There's no constraint on language, framework, or architecture for the API
layer. Whatever's fastest for you to build and easiest for us to
maintain is the right call. A few things worth knowing so you can decide:

- The core logic is the `extract(pdf_path)` function in `pdftocsv.py` — it
  takes a file path and returns `(records, fieldnames)` in memory, no
  disk writes required. That makes it easy to drop into any Python
  web framework (FastAPI, Flask, Django, whatever) as-is.
- If you'd rather build the API in another language entirely (Node,
  Go, etc.), the simplest integration is shelling out to this script
  (or a thin wrapper around `extract()`) as a subprocess and reading
  its CSV/JSON output — no need to port the parsing logic itself.
- Output doesn't have to be CSV — `records` is just a list of plain
  dicts, so returning JSON instead (or as well) is a trivial change,
  whichever suits the API's consumers better.
- Not opinionated on sync vs. async, file upload vs. path/URL input,
  auth, rate limiting, etc. — design the endpoint however fits the
  surrounding system.
- Only real requirement: whatever wraps this should surface a clear
  error if the input PDF doesn't match the expected register format
  (e.g. no subject-code header row found), rather than silently
  returning an empty/garbage CSV.

## Files
- `pdftocsv.py` — the extractor described above
- `results_example.csv` — example output from a sample run (for reference only)