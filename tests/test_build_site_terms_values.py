"""Tests for scripts/build_site_terms_values.py — Table B of the site-terms plan."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build_site_terms_values.py"
ALLOWLIST = REPO / "outputs" / "site_terms_field_allowlist.csv"
CANDIDATES = REPO / "outputs" / "finland_candidates_labelled.csv"
OUT_REL = Path("outputs/site_terms_values.csv")
OUT = REPO / OUT_REL
REPORT = REPO / "outputs" / "site_terms_values_run.json"

EXPECTED_COLS = ["ri", "site_id", "canonical_concept", "field_path", "value", "value_source"]
WKT_TOKENS = ("POINT(", "POLYGON(", "LINESTRING(", "MULTIPOLYGON(")


def _load():
    return pd.read_csv(OUT, keep_default_na=False)


def test_schema_columns_exact():
    df = _load()
    assert list(df.columns) == EXPECTED_COLS
    assert len(df) > 0


def test_all_field_paths_in_allowlist():
    df = _load()
    allow = pd.read_csv(ALLOWLIST, keep_default_na=False)
    allowed_pairs = {
        (str(r["ri"]).strip().upper(), str(r["field_path"]).strip())
        for _, r in allow[allow["in_allowlist"] == True].iterrows()
    }
    for _, row in df.iterrows():
        ri = str(row["ri"]).strip().upper()
        fp = str(row["field_path"]).strip()
        base_fp = fp.removesuffix(".lat").removesuffix(".lon")
        assert (ri, base_fp) in allowed_pairs, f"non-allowlisted path in Table B: {(ri, fp)}"


def test_max_value_length_80():
    df = _load()
    too_long = df[df["value"].astype(str).str.len() > 80]
    assert len(too_long) == 0, f"values > 80 chars: {too_long.to_dict('records')}"


def test_public_licence_scope_actris_values_deims_icos_counts_only():
    df = _load()
    count_re = re.compile(r"^n=\d+ distinct=\d+$")
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

    non_actris = df[df["ri"].isin(["DEIMS", "ICOS"])]
    assert len(non_actris) > 0
    for _, row in non_actris.iterrows():
        val = str(row["value"])
        assert count_re.match(val), f"DEIMS/ICOS row must be count-only, got {val!r}"
        assert not uuid_re.search(str(row["site_id"]))
        assert not uuid_re.search(val)

    actris = df[df["ri"] == "ACTRIS"]
    assert len(actris) > 0
    assert (~actris["value"].astype(str).str.match(count_re)).any()


def test_actris_restricted_to_confirmed_same_place_yes_pairs():
    df = _load()
    cand = pd.read_csv(CANDIDATES, keep_default_na=False)
    yes = cand[cand["same_place"].astype(str).str.strip() == "yes"]
    expected_actris_ids = (
        {str(r["record_id_a"]).strip() for _, r in yes.iterrows() if str(r["ri_a"]).strip().upper() == "ACTRIS"}
        | {str(r["record_id_b"]).strip() for _, r in yes.iterrows() if str(r["ri_b"]).strip().upper() == "ACTRIS"}
    )
    actual_actris_ids = set(df[df["ri"] == "ACTRIS"]["site_id"].astype(str).str.strip())
    assert actual_actris_ids == expected_actris_ids


def test_coordinates_emitted_as_numeric_lat_lon_rows():
    df = _load()
    coord_rows = df[df["field_path"].str.endswith((".lat", ".lon"))]
    assert len(coord_rows) > 0
    for _, row in coord_rows.iterrows():
        float(row["value"])  # must parse cleanly as a float string


def test_no_literal_none_in_gawid_uri():
    df = _load()
    gaw = df[(df["ri"] == "ACTRIS") & (df["field_path"] == "gawid_uri")]
    assert not (gaw["value"].astype(str).str.strip() == "None").any()


def test_row_uniqueness():
    df = _load()
    key_cols = ["ri", "site_id", "canonical_concept", "field_path", "value"]
    assert len(df) == len(df.drop_duplicates(subset=key_cols))


def test_no_wkt_or_emails_in_any_cell():
    df = _load()
    email_re = r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+"
    for col in df.columns:
        s = df[col].astype(str)
        for tok in WKT_TOKENS:
            assert not s.str.contains(tok, regex=False).any(), f"{tok!r} in {col!r}"
        assert not s.str.contains(email_re, regex=True).any(), f"email in {col!r}"


def test_skip_report_exists_and_logs_over_80_and_containers():
    assert REPORT.exists()
    rep = json.loads(REPORT.read_text())
    skipped = rep["skipped_values_by_rule"]
    assert any(k.endswith(":over_80_chars") and v > 0 for k, v in skipped.items())
    assert any("container" in k and v > 0 for k, v in skipped.items())


def test_clean_clone_does_not_touch_output(tmp_path):
    out = tmp_path / OUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "sentinel-content-do-not-overwrite\n"
    out.write_text(sentinel)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "missing" in (result.stderr + result.stdout).lower()
    assert out.read_text() == sentinel
