"""Tests for scripts/render_site_terms_html.py — Table C of the site-terms plan."""
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "render_site_terms_html.py"
TABLE_A = REPO / "outputs" / "site_terms_fields.csv"
TABLE_B = REPO / "outputs" / "site_terms_values.csv"
CANDIDATES = REPO / "outputs" / "finland_candidates_labelled.csv"
HTML_OUT = REPO / "outputs" / "site_terms_view.html"

WKT_TOKENS = ("POINT(", "POLYGON(", "LINESTRING(", "MULTIPOLYGON(")


def test_committed_html_matches_regenerated(tmp_path):
    assert HTML_OUT.exists(), f"missing committed HTML: {HTML_OUT}"
    regen = tmp_path / "site_terms_view.html"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--table-a",
            str(TABLE_A),
            "--table-b",
            str(TABLE_B),
            "--html",
            str(regen),
        ],
        check=True,
    )
    assert regen.read_text(encoding="utf-8") == HTML_OUT.read_text(encoding="utf-8")


def test_deterministic_repeated_runs(tmp_path):
    a = tmp_path / "a.html"
    b = tmp_path / "b.html"
    for out in (a, b):
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--table-a",
                str(TABLE_A),
                "--table-b",
                str(TABLE_B),
                "--html",
                str(out),
            ],
            check=True,
        )
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_header_per_ri_counts_and_notes():
    html_text = HTML_OUT.read_text(encoding="utf-8")

    # Header shows total rows / in-scope / filled / empty per RI
    assert "Total rows" in html_text
    assert "In-scope" in html_text
    assert "Filled" in html_text
    assert "Empty" in html_text

    # Per-RI counts from Table A (DEIMS 81/81/64/17, ICOS 20/20/7/13, ACTRIS 16/16/13/3)
    assert "<td><strong>DEIMS</strong></td><td>81</td><td>81</td><td>64</td><td>17</td>" in html_text
    assert "<td><strong>ICOS</strong></td><td>20</td><td>20</td><td>7</td><td>13</td>" in html_text
    assert "<td><strong>ACTRIS</strong></td><td>16</td><td>16</td><td>13</td><td>3</td>" in html_text

    # Header shows the "proposed, not confirmed (#4)" note
    assert "proposed, not confirmed (#4)" in html_text

    # Header shows the per-RI licence lines from site_terms_plan.md §9
    assert "DEIMS site metadata, CC BY-NC 4.0, https://deims.org/terms" in html_text
    assert "CC0 1.0 (confirmed, scheme file + TTL)" in html_text
    assert "ontology CC0 (cc:license, ICOS ERIC 2024); per-concept licence not stated; ICOS licence page not verified by us" in html_text
    assert "CC BY 4.0 per scheme file; LICENSE file 404; third-party source tags (Henderson&#x27;s / GEMET / NCIT) require provenance checks" in html_text


def test_collapsible_details_sections_present_for_table_b():
    html_text = HTML_OUT.read_text(encoding="utf-8")
    df_b = pd.read_csv(TABLE_B, keep_default_na=False)
    n_groups = len(df_b[["ri", "canonical_concept"]].drop_duplicates())
    assert html_text.count("<details>") == n_groups
    assert html_text.count("</details>") == n_groups


def test_no_forbidden_tokens_wkt_emails_or_deims_icos_values():
    html_text = HTML_OUT.read_text(encoding="utf-8")
    low = html_text.lower()

    assert "deims.org/api" not in low
    assert "deims-sdr" not in low
    assert "_local.csv" not in low

    for tok in WKT_TOKENS:
        assert tok not in html_text

    email_re = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+")
    assert not email_re.search(html_text)

    # No DEIMS UUIDs leaked
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
    assert not uuid_re.search(html_text)

    # No ICOS station URIs leaked
    assert "meta.icos-cp.eu/resources/stations/" not in html_text
