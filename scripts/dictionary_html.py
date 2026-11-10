"""CSV -> HTML renderer for dictionary tables.

Contract:
- Input is one CSV file (no network, no TTL, no environment deps).
- Output is deterministic: same CSV -> byte-identical HTML.
- Header shows total rows, filled count, marked count, plus a licence line.
- Refuses to write if output contains 'deims.org/api' or 'deims-sdr'.
"""
import argparse
from pathlib import Path

import pandas as pd

MARKER_PREFIXES = ("[NO DEFINITION PUBLISHED", "[FLAGGED", "[AMBIGUOUS")
DEFINITION_COL = "Definition (if published)"
FORBIDDEN = ("deims.org/api", "deims-sdr")

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
    <p>Total terms: {total} &nbsp;|&nbsp; Filled: {filled} &nbsp;|&nbsp; Marked: {marked} (definitions per RI, first version)</p>
    <div class="licence"><strong>Licence:</strong> {licence}</div>
"""
TAIL = "</body>\n</html>\n"


def count_states(df, col=DEFINITION_COL):
    s = df[col].astype(str).str.strip()
    marked = int(s.str.startswith(MARKER_PREFIXES).sum())
    filled = int((s != "").sum() - marked)
    return filled, marked


def render(csv_path, html_path, title, licence):
    df = pd.read_csv(csv_path, keep_default_na=False)
    filled, marked = count_states(df)
    body = df.to_html(index=False, escape=True, border=1, classes="dataframe")
    html = HEAD.format(title=title, total=len(df), filled=filled,
                       marked=marked, licence=licence) + body + "\n" + TAIL
    low = html.lower()
    for bad in FORBIDDEN:
        if bad in low:
            raise SystemExit(f"refusing to write {html_path}: contains {bad!r}")
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"{html_path}: rows={len(df)} filled={filled} marked={marked}")
    return filled, marked


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
