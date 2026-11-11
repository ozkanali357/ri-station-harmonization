"""Tests for scripts/build_site_terms_fields.py — Table A of the site-terms plan."""
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build_site_terms_fields.py"
OUT_REL = Path("outputs/site_terms_fields.csv")
OUT = REPO / OUT_REL

STATUSES = {"populated", "not_in_cached_response", "excluded_by_rule"}
WKT_TOKENS = ("POINT(", "POLYGON(", "LINESTRING(", "MULTIPOLYGON(")


def _load():
    return pd.read_csv(OUT, keep_default_na=False)


def test_row_count_is_117():
    assert len(_load()) == 117


def test_status_values_are_exactly_three():
    assert set(_load()["status"].unique()) <= STATUSES


def test_in_scope_all_true():
    assert _load()["in_scope"].astype(str).str.lower().isin({"true"}).all()


def test_per_ri_licence_strings():
    df = _load()
    assert df[df["ri"] == "DEIMS"]["licence"].str.contains("CC BY-NC 4.0").all()
    assert df[df["ri"] == "DEIMS"]["licence"].str.contains("deims.org/terms").all()
    assert df[df["ri"] == "ICOS"]["licence"].str.contains("CC0").all()
    assert df[df["ri"] == "ACTRIS"]["licence"].str.contains("CC0 1.0").all()


def test_deims_definitions_are_marker_only():
    df = _load()
    marker = "[FLAGGED: pending licence provenance - EnvThes scheme: http://vocabs.lter-europe.net/EnvThes/]"
    assert (df[df["ri"] == "DEIMS"]["definition"] == marker).all()


def test_no_wkt_in_any_cell():
    df = _load()
    for col in ("canonical_concept", "ri_field_path", "definition", "controlled_values_observed"):
        for tok in WKT_TOKENS:
            bad = df[df[col].str.contains(tok, regex=False)]
            assert len(bad) == 0, f"{tok!r} in {col!r}: {bad.to_dict('records')}"


def test_no_emails_in_any_cell():
    df = _load()
    pattern = r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+"
    for col in df.columns:
        bad = df[df[col].astype(str).str.contains(pattern, regex=True)]
        assert len(bad) == 0, f"email in {col!r}"


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
