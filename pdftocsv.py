import pdfplumber, re, csv, statistics
from collections import defaultdict

PDF = "/home/arp/Downloads/s1w25.pdf"
OUT_REGULAR = "results_regular.csv"        # <-- change to where you want this CSV
OUT_REPEATER = "results_repeater.csv"      # <-- change to where you want this CSV

STATUS_WORDS = {"Regular", "Repeater", "ATKT", "Fresh", "New"}
COMPONENT_LABELS = {"T1", "O1", "E1", "I1"}
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
        names[code] = " ".join(p[2] for p in parts).strip() or code
    return names


def extract(pdf_path):
    all_codes_seen = []       # first-seen order, across the whole document
    code_to_name = {}
    records = []
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

                    subject_totals = defaultdict(float)
                    subject_seen = set()
                    gpa = ""
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
                                        subject_totals[code] += val
                                        subject_seen.add(code)
                        elif label == 'TOT' and r2[0]['x0'] < 60:
                            decimals = [w for w in r2 if re.fullmatch(r'\d+\.\d+', w['text'])]
                            if decimals:
                                gpa = max(decimals, key=lambda w: w['x0'])['text']
                            k += 1
                            break
                        k += 1

                    rec = {"seat_no": seat_word['text'], "name": name, "status": status_word,
                           "mu_code": mu_code, "gpa": gpa}
                    for c in code_positions:
                        rec[code_to_name.get(c, c)] = subject_totals[c] if c in subject_seen else ""
                    records.append(rec)
                    i = k
                    continue
                i += 1

    fieldnames = ["seat_no", "name", "status", "mu_code", "gpa"] + [code_to_name.get(c, c) for c in all_codes_seen]
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