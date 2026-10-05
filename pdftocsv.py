import pdfplumber, re, csv, statistics
from collections import defaultdict

PDF = "SEM-I__I_T__WINTER_2025.pdf"        # <-- change to your PDF's path
OUT_REGULAR = "results_regular.csv"        # <-- change to where you want this CSV
OUT_REPEATER = "results_repeater.csv"      # <-- change to where you want this CSV

STATUS_WORDS = {"Regular", "Repeater", "ATKT", "Fresh", "New"}
GENDER_WORDS = {"MALE", "FEMALE"}
COMPONENT_LABELS = ["T1", "O1", "E1", "I1"]   # order matters — fixed column order below
NAME_STOP_WORDS = {"External", "Internal", "TOT", "GP", "TOTAL", "RESUL", "REMAR"}
NAME_STOP_PATTERN = re.compile(r'^\(\d+/\d+\)$')


def group_rows(words, tol=2.5):
    """Cluster words into visual rows by y-position (top), tolerating small jitter."""
    rows = defaultdict(list)
    for w in words:
        placed = False
        for top in list(rows.keys()):
            if abs(top - w['top']) <= tol:
                rows[top].append(w)
                placed = True
                break
        if not placed:
            rows[w['top']].append(w)
    return {top: sorted(ws, key=lambda x: x['x0']) for top, ws in rows.items()}


def nearest_code(x0, code_positions, tol=8):
    best, bestd = None, 1e9
    for code, cx in code_positions.items():
        d = abs(cx - x0)
        if d < bestd:
            best, bestd = code, d
    return best if bestd <= tol else None


def parse_mark(text):
    """Strip '+' (carried-forward flag) and treat '...'/'AB' etc as no mark."""
    t = text.rstrip('+')
    if re.fullmatch(r'\d+(\.\d+)?', t):
        return float(t)
    return None


def find_header_row(rows, sorted_tops):
    """Find the row containing the subject-code numbers (e.g. 10411, 10412...)."""
    for top in sorted_tops:
        codes = [w for w in rows[top] if re.fullmatch(r'\d{5}', w['text'])]
        if len(codes) >= 8:
            return top, {w['text']: w['x0'] for w in codes}
    return None, {}


def build_subject_names(rows, sorted_tops, code_row_top, code_positions):
    """Read the subject title (e.g. 'Applied Physics (THEORY)') out of the
    header block above the code row, using each subject's column x-range."""
    cutoff_top = None
    for top in sorted_tops:
        if top <= code_row_top:
            continue
        if any(t['text'] in NAME_STOP_WORDS or NAME_STOP_PATTERN.match(t['text'])
               for t in rows[top]):
            cutoff_top = top
            break
    if cutoff_top is None:
        return {c: c for c in code_positions}

    ordered = sorted(code_positions.items(), key=lambda kv: kv[1])
    gaps = [b[1] - a[1] for a, b in zip(ordered, ordered[1:])]
    median_gap = statistics.median(gaps) if gaps else 70
    boundaries = [x for _, x in ordered] + [ordered[-1][1] + median_gap]

    names = {}
    for idx, (code, x0) in enumerate(ordered):
        lo, hi = x0 - 5, boundaries[idx + 1] - 5
        parts = []
        for top in sorted_tops:
            if top < code_row_top or top >= cutoff_top:
                continue
            for w in rows[top]:
                if lo <= w['x0'] < hi and w['text'] not in (code, ':') and w['text'] not in NAME_STOP_WORDS:
                    parts.append((top, w['x0'], w['text']))
        parts.sort()
        full_name = " ".join(p[2] for p in parts).strip()
        # Drop the trailing grading-scheme tag, e.g. "(THEORY)" / "(TERM WORK AND ORAL)"
        clean_name = re.sub(r'\s*\([^)]*\)\s*$', '', full_name).strip()
        names[code] = clean_name or full_name or code

    # Two subjects can share the same title once the grading-scheme tag is
    # stripped (e.g. a theory course and its practical/term-work counterpart).
    # Keep the first occurrence as-is; prefix "Lab " on any repeat so columns
    # stay distinguishable.
    seen_names = set()
    for code, _x0 in ordered:
        name = names[code]
        if name in seen_names:
            names[code] = f"Lab {name}"
        else:
            seen_names.add(name)
    return names


def extract(pdf_path):
    all_codes_seen = []       # first-seen order, across the whole document
    code_to_name = {}
    raw_records = []          # seat_no/name/... + code -> {component: value}
    component_present = defaultdict(set)   # code -> set of components seen anywhere in the doc
    mu_re = re.compile(r'\(MU\d+\)')

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            rows = group_rows(words)
            sorted_tops = sorted(rows.keys())

            code_row_top, code_positions = find_header_row(rows, sorted_tops)
            if not code_positions:
                continue  # page without a student table (e.g. legend page)

            for c in code_positions:
                if c not in all_codes_seen:
                    all_codes_seen.append(c)
            if not code_to_name:
                code_to_name = build_subject_names(rows, sorted_tops, code_row_top, code_positions)

            name_col_start, status_col_start = 100, 260

            i = 0
            while i < len(sorted_tops):
                top = sorted_tops[i]
                row = rows[top]
                seat_word = next((w for w in row if re.fullmatch(r'\d{6,8}', w['text']) and w['x0'] < 90), None)
                if seat_word:
                    name_words = [w['text'] for w in row
                                  if name_col_start <= w['x0'] < status_col_start
                                  and w['text'] not in STATUS_WORDS]
                    name = " ".join(name_words)

                    status_word = next((w['text'] for w in row if w['text'] in STATUS_WORDS), "")

                    # MU code: may wrap — the closing ")" can sit alone on the next row
                    mu_code = ""
                    mu_word = next((w for w in row if w['text'].startswith('(MU')), None)
                    if mu_word:
                        piece = mu_word['text']
                        if piece.endswith(')'):
                            mu_code = piece
                        else:
                            for la in (1, 2):
                                if i + la >= len(sorted_tops):
                                    break
                                cont = rows[sorted_tops[i + la]]
                                closer = next((w for w in cont
                                               if w['text'].startswith(')')
                                               and abs(w['x0'] - mu_word['x0']) < 25), None)
                                if closer:
                                    piece += closer['text']
                                    break
                            mu_code = piece
                        mu_code = mu_code.strip("()")

                    status_x0 = next((w['x0'] for w in row if w['text'] in STATUS_WORDS), status_col_start)
                    gender = next(
                        (w['text'].upper() for w in row
                         if w['text'].upper() in GENDER_WORDS
                         and w['x0'] > status_x0
                         and (mu_word is None or w['x0'] < mu_word['x0'])),
                        ""
                    )

                    # code -> {"T1": 19.0, "E1": 15.0, "I1": 22.0, ...} — one dict per subject,
                    # keeping each component separate (no summing) so we can report exactly
                    # which fields apply to each subject.
                    subject_components = defaultdict(dict)
                    gpa = ""
                    total = ""
                    result = ""
                    k = i + 1
                    while k < len(sorted_tops):
                        r2 = rows[sorted_tops[k]]
                        if not r2:
                            k += 1
                            continue
                        label = r2[0]['text']
                        if re.fullmatch(r'\d{6,8}', label) and r2[0]['x0'] < 90:
                            break
                        if label in COMPONENT_LABELS:
                            for w in r2[1:]:
                                code = nearest_code(w['x0'], code_positions)
                                if code:
                                    val = parse_mark(w['text'])
                                    if val is not None:
                                        subject_components[code][label] = val
                                        component_present[code].add(label)
                        elif label == 'TOT' and r2[0]['x0'] < 60:
                            decimals = [w for w in r2 if re.fullmatch(r'\d+\.\d+', w['text'])]
                            if decimals:
                                gpa = max(decimals, key=lambda w: w['x0'])['text']

                        # On every row, scan for total marks and result if not yet found
                        if not total:
                            for w in r2:
                                # Total appears as (616) or (478) — a parenthesized integer
                                m = re.fullmatch(r'\((\d+)\)', w['text'])
                                if m:
                                    total = m.group(1)
                                    break
                        if not result:
                            for w in r2:
                                upper = w['text'].upper()
                                # Handle split words: FAILE(D), PASS, FAIL, etc.
                                if upper.startswith('PASS'):
                                    result = 'PASS'
                                    break
                                elif upper.startswith('FAIL'):
                                    result = 'FAILED'
                                    break
                        k += 1

                    raw_records.append({
                        "seat_no": seat_word['text'], "name": name, "gender": gender, "status": status_word,
                        "mu_code": mu_code, "gpa": gpa, "total": total, "result": result,
                        "subjects": subject_components,
                    })
                    i = k
                    continue
                i += 1

    # Build column list: for each subject, only the components that occurred *anywhere*
    # in the document for that subject, in T1/O1/E1/I1 order, plus a computed TOT.
    subject_columns = {}  # code -> ordered list of (field_key, "component_label_or_TOT")
    for code in all_codes_seen:
        present = [lbl for lbl in COMPONENT_LABELS if lbl in component_present.get(code, set())]
        name = code_to_name.get(code, code)
        cols = [(f"{name} ({lbl})", lbl) for lbl in present]
        cols.append((f"{name} (TOT)", "TOT"))
        subject_columns[code] = cols

    fieldnames = ["seat_no", "name", "gender", "status", "mu_code", "gpa", "total", "result"]
    for code in all_codes_seen:
        fieldnames += [col for col, _ in subject_columns[code]]

    records = []
    for r in raw_records:
        rec = {"seat_no": r["seat_no"], "name": r["name"], "gender": r["gender"],
               "status": r["status"], "mu_code": r["mu_code"], "gpa": r["gpa"],
               "total": r["total"], "result": r["result"]}
        for code in all_codes_seen:
            values = r["subjects"].get(code, {})
            for col, lbl in subject_columns[code]:
                if lbl == "TOT":
                    rec[col] = sum(values.values()) if values else ""
                else:
                    rec[col] = values.get(lbl, "")
        records.append(rec)

    return records, fieldnames


def write_csv(path, records, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({fn: r.get(fn, "") for fn in fieldnames})


if __name__ == "__main__":
    records, fieldnames = extract(PDF)

    regular = [r for r in records if r.get("status") != "Repeater"]
    repeater = [r for r in records if r.get("status") == "Repeater"]

    write_csv(OUT_REGULAR, regular, fieldnames)
    write_csv(OUT_REPEATER, repeater, fieldnames)

    print(f"Wrote {len(regular)} records to {OUT_REGULAR}")
    print(f"Wrote {len(repeater)} records to {OUT_REPEATER}")
    # for r in records[:3]:
    #     print(r)
    #     print(r)