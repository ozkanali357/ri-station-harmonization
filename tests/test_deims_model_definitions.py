"""DEIMS-SDR Site Metadata Model extraction: parsing, flagging, contact exclusion, all offline.

``tests/data/deims_model_sample.json`` is synthetic: it has the structure of the model JSON (``MODEL_URL``)
with invented text, because the DEIMS text itself is not committed. The Contact entries are synthetic too.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import deims_model_definitions as dmd

ROOT = Path(__file__).resolve().parents[1]
MODEL = json.loads((Path(__file__).parent / "data" / "deims_model_sample.json").read_text(encoding="utf-8"))


def test_definition_is_copied_verbatim_into_separate_columns():
    rows, excluded = dmd.extract_rows(MODEL)
    assert excluded == []
    row = {r["page_path"]: r for r in rows}["Group A/Alpha Name"]
    assert row["definition"] == "Synthetic definition of alpha."
    assert row["recommendation"] == "Synthetic hint with \u2018quotes\u2019 kept."  # typographic quotes kept
    assert (row["format"], row["multiplicity"], row["example"]) == ("Text(10)", "[1..1]", "Example alpha")
    assert row["definition_published"] == "yes"
    assert (row["model_version"], row["model_release_date"]) == ("9.9", "2000-01-01T00:00:00.000Z")


def test_nested_group_gives_a_full_path_and_numbers_stay_numbers_as_text():
    rows = {r["page_path"]: r for r in dmd.extract_rows(MODEL)[0]}
    row = rows["Group B/Sub/Beta (avg)"]
    assert row["page_group"] == "Group B" and row["page_label"] == "Beta (avg)"
    assert row["page_field_name"] == "field_beta_avg"
    assert row["example"] == "956"


def test_an_empty_definition_stays_flagged_and_is_not_filled_in():
    rows = {r["page_path"]: r for r in dmd.extract_rows(MODEL)[0]}
    row = rows["Group C/Gamma"]
    assert row["definition_published"] == "no"
    assert row["definition"] == dmd.FLAG_TEXT
    assert row["recommendation"] == "" and row["format"] == ""
    assert row["example"] == "1991-2020"  # an example is not a definition and is kept as its own column


def test_contact_entries_are_dropped_and_their_values_never_reach_the_rows():
    model = json.loads(json.dumps(MODEL))
    model["content"]["Contact"] = {"Site Manager": {
        "field_name": "field_site_manager", "Definition": "Hidden contact definition",
        "Example": "Doe, Jane", "Format": "x", "Multiplicity": "[1..n]"}}
    model["content"]["Group A"]["Contact point"] = {
        "field_name": "field_x", "Definition": "Hidden", "Example": "Roe, Richard"}
    rows, excluded = dmd.extract_rows(model)
    assert {e["page_path"] for e in excluded} == {"Contact/Site Manager", "Group A/Contact point"}
    blob = json.dumps(rows)
    assert "Doe, Jane" not in blob and "Roe, Richard" not in blob and "Hidden" not in blob
    assert len(rows) == 3


def test_an_email_address_in_a_row_stops_the_run():
    rows, _ = dmd.extract_rows(MODEL)
    rows[0]["example"] = "someone" + chr(64) + "example.org"
    with pytest.raises(SystemExit, match="e-mail"):
        dmd.check_no_emails(rows)


def test_duplicate_machine_names_stop_the_run():
    rows, _ = dmd.extract_rows(MODEL)
    rows[1]["page_field_name"] = rows[0]["page_field_name"]
    with pytest.raises(SystemExit, match="duplicate"):
        dmd.check_unique(rows)


def test_licence_sentence_is_found_in_a_terms_page_and_not_in_another():
    html = "<p>This work is licensed under a Creative Commons Attribution-Non\n Commercial 4.0 International License (CC BY-NC 4.0 International)</p>"
    assert dmd.licence_found(html)
    assert not dmd.licence_found("<p>All rights reserved</p>")


def test_field_list_holds_no_text_columns():
    rows, _ = dmd.extract_rows(MODEL)
    frame = pd.DataFrame(rows, columns=dmd.OUTPUT_COLUMNS)
    dmd.write_field_list(frame, tmp := Path(__import__("tempfile").mkdtemp()) / "list.csv")
    listed = pd.read_csv(tmp, keep_default_na=False)
    assert list(listed.columns) == dmd.FIELD_LIST_COLUMNS
    assert "Synthetic" not in tmp.read_text(encoding="utf-8")


def test_a_changed_model_response_is_refused_and_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr(dmd, "SOURCES", {"smm.json": ("https://example.invalid/smm.json", tmp_path)})

    class Response:
        status_code, headers, content = 200, {}, b'{"changed": true}'

        def raise_for_status(self):
            pass

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(SystemExit, match="CHECKSUM MISMATCH"):
        dmd.fetch_to_cache("smm.json", Session(), expected_sha256="0" * 64)
    assert not (tmp_path / "smm.json").exists()
    entry = dmd.fetch_to_cache("smm.json", Session(), expected_sha256=hashlib.sha256(Response.content).hexdigest())
    assert entry["sha256"] == hashlib.sha256(Response.content).hexdigest() and (tmp_path / "smm.json").exists()


def test_a_cached_file_that_differs_from_the_record_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(dmd, "SOURCES", {"smm.json": ("https://example.invalid/smm.json", tmp_path)})
    (tmp_path / "smm.json").write_bytes(b"{}")
    with pytest.raises(SystemExit, match="CHECKSUM MISMATCH"):
        dmd.cached_entry("smm.json", {"sha256": "0" * 64})


def test_committed_run_file_and_field_list_agree():
    run = json.loads((ROOT / "outputs" / "deims_model_definitions_run.json").read_text(encoding="utf-8"))
    listed = pd.read_csv(ROOT / "outputs" / "deims_model_field_list.csv", keep_default_na=False)
    assert list(listed.columns) == dmd.FIELD_LIST_COLUMNS
    assert run["counts"]["extracted"] == len(listed)
    assert run["counts"]["with_definition"] == int((listed["definition_published"] == "yes").sum())
    assert run["output"]["committed"] is False
    assert run["field_list"]["sha256"] == hashlib.sha256((ROOT / "outputs" / "deims_model_field_list.csv").read_bytes()).hexdigest()
    assert not listed["page_path"].str.contains("contact", case=False).any()


@pytest.mark.skipif(not dmd.OUT_CSV.exists(), reason="outputs/deims_model_definitions.csv is produced locally (git-ignored)")
def test_local_csv_matches_the_committed_record_and_has_no_email():
    run = json.loads((ROOT / "outputs" / "deims_model_definitions_run.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(dmd.OUT_CSV.read_bytes()).hexdigest() == run["output"]["sha256"]
    frame = pd.read_csv(dmd.OUT_CSV, keep_default_na=False)
    assert list(frame.columns) == dmd.OUTPUT_COLUMNS
    assert not frame.apply(lambda col: col.astype(str).str.contains(dmd.EMAIL_RE)).any().any()
