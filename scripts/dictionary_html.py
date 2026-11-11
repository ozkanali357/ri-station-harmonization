"""CSV -> HTML renderer for dictionary tables.

Contract:
- Input is one CSV file (no network, no TTL, no environment deps).
- Output is deterministic: same CSV -> byte-identical HTML.
- Header shows total rows, filled count, per-state marked counts, plus a licence line.
- Refuses to write if output contains 'deims.org/api' or 'deims-sdr'.

Regeneration commands (identical to PR body):

  python scripts/dictionary_html.py \\
    --csv outputs/dictionary_actris_terms.csv \\
    --html outputs/dictionary_actris_terms.html \\
    --title "ACTRIS Data Dictionary (Meteorology & Soil)" \\
    --licence "ACTRIS vocabulary CC0 1.0 (confirmed); definitions from ACTRIS_vocabulary.ttl by exact prefLabel match"

  python scripts/dictionary_html.py \\
    --csv outputs/dictionary_icos_terms.csv \\
    --html outputs/dictionary_icos_terms.html \\
    --title "ICOS Data Dictionary (Meteorology & Soil)" \\
    --licence "ontology CC0 (cc:license, ICOS ERIC 2024); per-concept licence not stated; ICOS licence page not verified by us"

  python scripts/dictionary_html.py \\
    --csv outputs/dictionary_deims_terms.csv \\
    --html outputs/dictionary_deims_terms.html \\
    --title "DEIMS Data Dictionary (Meteorology & Soil)" \\
    --licence "definitions withheld for licence provenance (EnvThes CC BY 4.0 with third-party source tags); no definition text included"
"""
import argparse
from pathlib import Path

import pandas as pd

DEFINITION_COL = "Definition (if published)"
FORBIDDEN = ("deims.org/api", "deims-sdr")

# Ordered (state label, marker prefix). First match wins. Anything else non-empty is 'filled'.
STATE_ORDER = [
    ("no definition",       "[NO DEFINITION PUBLISHED"),
    ("no matching concept", "[NO MATCHING CONCEPT"),
    ("flagged",             "[FLAGGED"),
    ("ambiguous",           "[AMBIGUOUS"),
]

HEAD = """\
<html>
<head>
<style>
    body {{ font-family: Arial, sans-serif; margin: 30px; background-color: #f9f9f9; }}
    h1 {{ color: #2c3e50; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; background-color: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    th {{ background-color: #2980b9; color: white; padding: 10px; text-align: left; position: sticky; top: 0; }}
    td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
    tr:hover {{ background-color: #f1f1f1; }}
    .licence {{ background-color: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 15px 0; font-size: 12px; }}
</style>
</head>
<body>
    <h1>{title}</h1>
    <p>{header_line}</p>
    <div class="licence"><strong>Licence:</strong> {licence}</div>
"""
TAIL = "</body>\n</html>\n"


def count_states(df, col=DEFINITION_COL):
    s = df[col].astype(str).str.strip()
    counts = {}
    matched = pd.Series(False, index=df.index)
    for label, prefix in STATE_ORDER:
        m = s.str.startswith(prefix)
        counts[label] = int(m.sum())
        matched = matched | m
    counts["filled"] = int(((s != "") & (~matched)).sum())
    counts["empty"]  = int(((s == "") & (~matched)).sum())
    return counts


def header_line(counts, total):
    parts = [f"Total terms: {total}", f"Filled: {counts['filled']}"]
    for label, _ in STATE_ORDER:
        if counts[label]:
            parts.append(f"{label.capitalize()}: {counts[label]}")
    if counts.get("empty"):
        parts.append(f"Empty: {counts['empty']}")
    return " &nbsp;|&nbsp; ".join(parts) + " (definitions per RI, first version)"


def render(csv_path, html_path, title, licence):
    df = pd.read_csv(csv_path, keep_default_na=False)
    counts = count_states(df)
    body = df.to_html(index=False, escape=True, border=1, classes="dataframe")
    html = HEAD.format(title=title, header_line=header_line(counts, len(df)), licence=licence) + body + "\n" + TAIL
    low = html.lower()
    for bad in FORBIDDEN:
        if bad in low:
            raise SystemExit(f"refusing to write {html_path}: contains {bad!r}")
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"{html_path}: rows={len(df)} " + " ".join(f"{k}={v}" for k, v in counts.items() if v))
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--html", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--licence", required=True)
    args = p.parse_args()
    render(args.csv, args.html, args.title, args.licence)


if __name__ == "__main__":
    main()
