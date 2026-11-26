"""Step 4 (Table C) of site_terms_plan.md: deterministic HTML view of Tables A & B."""
import argparse
import html
from pathlib import Path
import re
import sys
import pandas as pd

DEFAULT_TABLE_A = Path("outputs/site_terms_fields.csv")
DEFAULT_TABLE_B = Path("outputs/site_terms_values.csv")
DEFAULT_HTML = Path("outputs/site_terms_view.html")
FORBIDDEN_SUBSTRINGS = ("deims.org/api", "deims-sdr", "_local.csv")
WKT_RE = re.compile(r"(POINT|POLYGON|LINESTRING|MULTIPOLYGON|MULTILINESTRING)\s*\(", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+")
COUNT_ONLY_RE = re.compile(r"^n=\d+ distinct=\d+$")
RI_ORDER = ("DEIMS", "ICOS", "ACTRIS")

LICENCE_LINES = [
    ("DEIMS", "DEIMS site metadata, CC BY-NC 4.0, https://deims.org/terms"),
    ("ACTRIS", "CC0 1.0 (confirmed, scheme file + TTL) for vocabularies; ACTRIS facilities API, cached response; facility-record licence not verified"),
    ("ICOS", "ontology CC0 (cc:license, ICOS ERIC 2024); per-concept licence not stated; ICOS licence page not verified by us"),
    ("EnvThes", "CC BY 4.0 per scheme file; LICENSE file 404; third-party source tags (Henderson's / GEMET / NCIT) require provenance checks"),
]

HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 28px; background-color: #f9f9f9; color: #222; }}
  h1 {{ color: #2c3e50; margin-bottom: 8px; }}
  h2 {{ color: #2c3e50; margin-top: 28px; border-bottom: 2px solid #2980b9; padding-bottom: 4px; }}
  .note {{ background-color: #eef6fc; padding: 10px 14px; border-left: 4px solid #2980b9; margin: 12px 0; font-size: 13px; }}
  .licence {{ background-color: #fff3cd; padding: 10px 14px; border-left: 4px solid #ffc107; margin: 12px 0; font-size: 12px; }}
  .licence ul {{ margin: 6px 0 0 18px; padding: 0; }}
  .licence li {{ margin-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; background-color: #fff; margin-bottom: 16px; }}
  th {{ background-color: #2980b9; color: #fff; padding: 8px 10px; text-align: left; position: sticky; top: 0; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #ddd; vertical-align: top; word-break: break-word; }}
  tr:hover {{ background-color: #f3f7fa; }}
  table.summary {{ width: auto; min-width: 620px; }}
  details {{ background-color: #fff; border: 1px solid #d5dce0; border-radius: 4px; margin-bottom: 8px; padding: 6px 12px; }}
  summary {{ cursor: pointer; font-weight: bold; color: #2c3e50; padding: 4px 0; font-size: 13px; }}
  .badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: bold; color: #fff; margin-right: 6px; }}
  .badge-DEIMS {{ background-color: #2e7d32; }}
  .badge-ICOS {{ background-color: #1565c0; }}
  .badge-ACTRIS {{ background-color: #6a1b9a; }}
  .muted {{ color: #555; font-weight: normal; font-size: 12px; }}
</style>
</head>
<body>
<h1>{title}</h1>
"""
HTML_TAIL = "</body>\n</html>\n"

def esc(val) -> str:
    return html.escape(str(val), quote=True)

def compute_table_a_stats(df_a: pd.DataFrame) -> list[dict]:
    stats = []
    for ri in RI_ORDER:
        sub = df_a[df_a["ri"].astype(str).str.strip().str.upper() == ri]
        in_scope_mask = sub["in_scope"].astype(str).str.strip().str.lower() == "true"
        status_s = sub["status"].astype(str).str.strip()
        filled = int((status_s == "populated").sum())
        stats.append({
            "ri": ri, "total": int(len(sub)), "in_scope": int(in_scope_mask.sum()),
            "filled": filled, "empty": int(len(sub) - filled),
            "not_in_cached_response": int((status_s == "not_in_cached_response").sum()),
            "excluded_by_rule": int((status_s == "excluded_by_rule").sum()),
        })
    stats.append({
        "ri": "TOTAL",
        "total": sum(s["total"] for s in stats),
        "in_scope": sum(s["in_scope"] for s in stats),
        "filled": sum(s["filled"] for s in stats),
        "empty": sum(s["empty"] for s in stats),
        "not_in_cached_response": sum(s["not_in_cached_response"] for s in stats),
        "excluded_by_rule": sum(s["excluded_by_rule"] for s in stats),
    })
    return stats

def validate_inputs(df_b: pd.DataFrame):
    non_actris_b = df_b[df_b["ri"].astype(str).str.strip().str.upper() != "ACTRIS"]
    bad_b = non_actris_b[~non_actris_b["value"].astype(str).str.match(COUNT_ONLY_RE)]
    if len(bad_b):
        sys.exit("refusing to render HTML: non-count DEIMS/ICOS rows in Table B")

def render_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["<table>\n<thead><tr>"]
    lines.extend(f"  <th>{esc(c)}</th>" for c in cols)
    lines.append("</tr></thead>\n<tbody>")
    for _, row in df.iterrows():
        lines.append("<tr>")
        lines.extend(f"  <td>{esc(row[c])}</td>" for c in cols)
        lines.append("</tr>")
    lines.append("</tbody>\n</table>")
    return "\n".join(lines)

def render_html(table_a_path: Path, table_b_path: Path, html_path: Path, title: str):
    df_a = pd.read_csv(table_a_path, keep_default_na=False)
    df_b = pd.read_csv(table_b_path, keep_default_na=False)
    validate_inputs(df_b)
    stats = compute_table_a_stats(df_a)
    b_counts = df_b["ri"].astype(str).str.strip().str.upper().value_counts().to_dict()
    lic_items = "\n".join(f"  <li><strong>{esc(ri)}:</strong> {esc(t)}</li>" for ri, t in LICENCE_LINES)
    note_html = (
        '<div class="note"><strong>Scope & Pairing Note:</strong> '
        "Covers 20 Finnish DEIMS sites (<code>outputs/deims_networks_finland.csv</code>) "
        "plus paired ICOS/ACTRIS records in <code>outputs/finland_candidates_labelled.csv</code>. "
        "<strong>The pairing is proposed, not confirmed (#4).</strong> "
        "Table B restricts ICOS/ACTRIS to <code>same_place == 'yes'</code> pairs (proposed labels, 30 rows) "
        "and keeps DEIMS/ICOS as aggregate count rows.</div>"
    )
    lic_html = f'<div class="licence"><strong>Per-RI Licence State (§9):</strong>\n<ul>\n{lic_items}\n</ul>\n</div>'
    summary_head = (
        '<table class="summary">\n<thead><tr>'
        "<th>RI</th><th>Total rows</th><th>In-scope</th><th>Filled (populated)</th>"
        "<th>Empty</th><th>not_in_cached_response</th><th>excluded_by_rule</th><th>Table B rows</th>"
        "</tr></thead>\n<tbody>"
    )
    parts = [HTML_HEAD.format(title=esc(title)), note_html, lic_html, "<h2>Summary Counts per RI</h2>", summary_head]
    for s in stats:
        ri = s["ri"]
        b_n = len(df_b) if ri == "TOTAL" else int(b_counts.get(ri, 0))
        parts.append(
            f"<tr><td><strong>{esc(ri)}</strong></td><td>{s['total']}</td><td>{s['in_scope']}</td>"
            f"<td>{s['filled']}</td><td>{s['empty']}</td><td>{s['not_in_cached_response']}</td>"
            f"<td>{s['excluded_by_rule']}</td><td>{b_n}</td></tr>"
        )
    parts.append("</tbody>\n</table>")
    parts.append(f"<h2>Table A — Field Specification ({len(df_a)} fields)</h2>")
    parts.append(render_table(df_a))
    parts.append(f"<h2>Table B — Per-Site Values & Aggregate Counts ({len(df_b)} rows)</h2>")
    ordered_keys, seen_keys = [], set()
    for df_src in (df_a, df_b):
        for _, row in df_src.iterrows():
            k = (str(row["ri"]).strip().upper(), str(row["canonical_concept"]).strip())
            if k not in seen_keys:
                seen_keys.add(k)
                ordered_keys.append(k)
    df_b_idx = df_b.assign(_ri_u=df_b["ri"].astype(str).str.strip().str.upper(), _cc=df_b["canonical_concept"].astype(str).str.strip())
    detail_cols = ["site_id", "field_path", "value", "value_source"]
    for ri, concept in ordered_keys:
        sub = df_b_idx[(df_b_idx["_ri_u"] == ri) & (df_b_idx["_cc"] == concept)]
        if len(sub) == 0:
            continue
        parts.append(f'<details>\n<summary><span class="badge badge-{esc(ri)}">{esc(ri)}</span>{esc(concept)} <span class="muted">({len(sub)} rows)</span></summary>')
        parts.append(render_table(sub[detail_cols]))
        parts.append("</details>")
    parts.append(HTML_TAIL)
    full_html = "\n".join(parts)
    low = full_html.lower()
    if any(b in low for b in FORBIDDEN_SUBSTRINGS) or WKT_RE.search(full_html) or EMAIL_RE.search(full_html):
        sys.exit(f"refusing to write {html_path}: forbidden token")
    html_path.write_text(full_html, encoding="utf-8")
    print(f"wrote {html_path}: Table A={len(df_a)} rows, Table B={len(df_b)} rows")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--table-a", type=Path, default=DEFAULT_TABLE_A)
    p.add_argument("--table-b", type=Path, default=DEFAULT_TABLE_B)
    p.add_argument("--html", type=Path, default=DEFAULT_HTML)
    p.add_argument("--title", default="Site and Facility Terms Across DEIMS, ICOS, and ACTRIS (Tables A and B)")
    args = p.parse_args()
    render_html(args.table_a, args.table_b, args.html, args.title)

if __name__ == "__main__":
    main()
