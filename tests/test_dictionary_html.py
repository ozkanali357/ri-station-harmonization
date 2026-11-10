import subprocess, sys
from pathlib import Path
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "dictionary_html.py"
DEFINITION_COL = "Definition (if published)"
DEIMS_MARKER = "[FLAGGED: pending licence provenance - EnvThes scheme: http://vocabs.lter-europe.net/EnvThes/]"

FIXTURES = [
    ("dictionary_actris_terms", "ACTRIS Data Dictionary (Meteorology & Soil)",
     "ACTRIS vocabulary CC0 1.0 (confirmed); definitions from ACTRIS_vocabulary.ttl by exact prefLabel match"),
    ("dictionary_icos_terms", "ICOS Data Dictionary (Meteorology & Soil)",
     "ontology CC0 (cc:license, ICOS ERIC 2024); per-concept licence not stated; ICOS licence page not verified by us"),
    ("dictionary_deims_terms", "DEIMS Data Dictionary (Meteorology & Soil)",
     "definitions withheld for licence provenance (EnvThes CC BY 4.0 with third-party source tags); no definition text included"),
]


@pytest.mark.parametrize("stem,title,licence", FIXTURES)
def test_committed_html_matches_regenerated(stem, title, licence, tmp_path):
    csv = REPO / "outputs" / f"{stem}.csv"
    html = REPO / "outputs" / f"{stem}.html"
    out = tmp_path / "regen.html"
    subprocess.run([sys.executable, str(SCRIPT),
                    "--csv", str(csv), "--html", str(out),
                    "--title", title, "--licence", licence], check=True)
    assert out.read_text(encoding="utf-8") == html.read_text(encoding="utf-8"), \
        f"{html.name} is stale vs {csv.name}"


@pytest.mark.parametrize("stem,title,licence", FIXTURES)
def test_header_counts_match_csv(stem, title, licence):
    sys.path.insert(0, str(REPO))
    from scripts.dictionary_html import count_states
    df = pd.read_csv(REPO / "outputs" / f"{stem}.csv", keep_default_na=False)
    filled, marked = count_states(df)
    html = (REPO / "outputs" / f"{stem}.html").read_text(encoding="utf-8")
    assert f"Total terms: {len(df)}" in html
    assert f"Filled: {filled}" in html
    assert f"Marked: {marked}" in html


@pytest.mark.parametrize("stem,title,licence", FIXTURES)
def test_no_deims_text_in_any_html(stem, title, licence):
    text = (REPO / "outputs" / f"{stem}.html").read_text(encoding="utf-8").lower()
    assert "deims.org/api" not in text
    assert "deims-sdr" not in text


def test_deims_csv_all_rows_marked_exactly():
    df = pd.read_csv(REPO / "outputs" / "dictionary_deims_terms.csv", keep_default_na=False)
    s = df[DEFINITION_COL].astype(str).str.strip()
    assert (s == DEIMS_MARKER).all(), f"{int((s != DEIMS_MARKER).sum())} rows differ"


def test_deims_html_definition_cells_only_contain_marker():
    df = pd.read_csv(REPO / "outputs" / "dictionary_deims_terms.csv", keep_default_na=False)
    html = (REPO / "outputs" / "dictionary_deims_terms.html").read_text(encoding="utf-8")
    assert html.count(DEIMS_MARKER) == len(df)


def test_dictionary_html_deterministic(tmp_path):
    csv = REPO / "outputs" / "dictionary_actris_terms.csv"
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    for out in (a, b):
        subprocess.run([sys.executable, str(SCRIPT), "--csv", str(csv), "--html", str(out),
                        "--title", "T", "--licence", "L"], check=True)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
