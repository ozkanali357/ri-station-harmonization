"""Definition-backed input: which fields receive a definition and which never do, all offline."""

from pathlib import Path

import pandas as pd
import pytest

from scripts import build_definition_backed_input as bdi

ROOT = Path(__file__).resolve().parents[1]
FLAG = bdi.FLAG_TEXT

FIELDS = pd.DataFrame([
    ("DEIMS", "general.siteName", FLAG, "yes"),
    ("DEIMS", "general.status.label", FLAG, "yes"),
    ("DEIMS", "general.citation", FLAG, "yes"),
    ("DEIMS", "environmentalCharacteristics.airTemperature.referencePeriod", FLAG, "yes"),
    ("DEIMS", "geographic.country", FLAG, "yes"),
    ("ICOS", "hasLatitude", "Decimal degrees", "no"),
    ("ICOS", "hasName", FLAG, "yes"),
    ("ACTRIS", "name", FLAG, "yes"),
], columns=["ri", "field", "definition", "flagged"])

MODEL = pd.DataFrame([
    ("General/Site Name", "field_name", "Name of the site.", "yes"),
    ("Status and History/Site Status", "field_status", "Status of the site.", "yes"),
    ("Climatic Characteristics/Standard Reference Period", "field_standard_reference_period", bdi.FLAG_TEXT, "no"),
    ("Geographic/Country", "field_country", bdi.FLAG_TEXT, "no"),
], columns=["page_path", "page_field_name", "definition", "definition_published"])
MODEL["model_version"] = "1.43"

MAPPING = pd.DataFrame([
    ("General/Site Name", "field_name", "general.siteName", "direct"),
    ("Status and History/Site Status", "field_status", "general.status.label", "component"),
    ("Climatic Characteristics/Standard Reference Period", "field_standard_reference_period",
     "environmentalCharacteristics.airTemperature.referencePeriod", "candidate"),
    ("Geographic/Country", "field_country", "geographic.country", "curated"),
], columns=["page_path", "page_field_name", "api_field", "relation"])


def built():
    return bdi.build_input(FIELDS, MODEL, MAPPING).set_index(["ri", "field"])


def test_a_direct_mapping_copies_the_definition_verbatim_and_records_where_it_came_from():
    row = built().loc[("DEIMS", "general.siteName")]
    assert row["definition"] == "Name of the site." and row["flagged"] == "no"
    assert row["definition_source"] == "DEIMS-SDR Site Metadata Model v1.43, Definition"
    assert (row["model_page_path"], row["mapping_relation"]) == ("General/Site Name", "direct")


def test_component_and_candidate_rows_never_transfer_a_definition():
    out = built()
    for field in ("general.status.label", "environmentalCharacteristics.airTemperature.referencePeriod"):
        assert out.loc[("DEIMS", field), "flagged"] == "yes"
        assert out.loc[("DEIMS", field), "definition"] == FLAG
        assert out.loc[("DEIMS", field), "mapping_relation"] == ""


def test_a_mapped_field_whose_model_entry_has_no_definition_stays_flagged():
    row = built().loc[("DEIMS", "geographic.country")]
    assert row["flagged"] == "yes" and row["definition"] == FLAG
    assert row["mapping_relation"] == "curated"  # the link is recorded, the text is not invented


def test_unmapped_icos_and_actris_fields_are_unchanged():
    out = built()
    assert out.loc[("DEIMS", "general.citation"), "flagged"] == "yes"
    assert out.loc[("ICOS", "hasLatitude"), "definition"] == "Decimal degrees"
    assert out.loc[("ICOS", "hasLatitude"), "definition_source"].startswith("rdfs:comment")
    assert out.loc[("ICOS", "hasName"), "flagged"] == "yes"
    assert out.loc[("ACTRIS", "name"), "flagged"] == "yes"


@pytest.mark.parametrize("bad, message", [
    (lambda m: m.assign(api_field=["general.nope"] + m["api_field"].tolist()[1:]), "not in final_field_comparison"),
    (lambda m: m.assign(page_path=["General/Nope"] + m["page_path"].tolist()[1:]), "not extracted"),
    (lambda m: m.assign(relation=["maybe"] + m["relation"].tolist()[1:]), "unknown relation"),
    (lambda m: m.assign(page_field_name=["field_other"] + m["page_field_name"].tolist()[1:]), "does not match"),
    (lambda m: pd.concat([m, m.iloc[[0]].assign(page_path="Geographic/Country", page_field_name="field_country",
                                                relation="curated")]), "more than one direct/curated row"),
])
def test_an_inconsistent_mapping_is_refused(bad, message):
    with pytest.raises(ValueError, match=message):
        bdi.validate_mapping(bad(MAPPING.copy()), MODEL, FIELDS)


def test_unmapped_report_lists_both_sides():
    report = bdi.unmapped_report(FIELDS, MODEL, MAPPING)
    pairs = set(zip(report["side"], report["field"]))
    assert ("model", "Status and History/Site Status") in pairs  # only a component row
    assert ("api", "general.citation") in pairs  # no row at all
    assert ("api", "general.siteName") not in pairs and ("model", "General/Site Name") not in pairs


def test_committed_mapping_is_consistent_with_the_committed_field_lists():
    # the field list holds paths and machine names only, so this runs without the (git-ignored) model text
    fields = pd.read_csv(ROOT / "outputs" / "final_field_comparison.csv")
    listed = pd.read_csv(ROOT / "outputs" / "deims_model_field_list.csv", keep_default_na=False)
    mapping = pd.read_csv(bdi.IN_MAPPING, keep_default_na=False)
    bdi.validate_mapping(mapping, listed, fields)
    assert (mapping["basis"] != "").all()
    report = bdi.unmapped_report(fields, listed, mapping)
    committed = pd.read_csv(bdi.OUT_UNMAPPED, keep_default_na=False)
    pd.testing.assert_frame_equal(report.reset_index(drop=True), committed, check_dtype=False)


LOCAL_ONLY = pytest.mark.skipif(not (bdi.IN_MODEL.exists() and bdi.OUT_INPUT.exists()),
                                reason="the DEIMS model text is git-ignored and produced locally by "
                                       "scripts/build_definition_backed_input.py")


@LOCAL_ONLY
def test_local_definition_backed_input_is_what_the_script_builds():
    fields = pd.read_csv(ROOT / "outputs" / "final_field_comparison.csv")
    model = pd.read_csv(bdi.IN_MODEL, keep_default_na=False)
    mapping = pd.read_csv(bdi.IN_MAPPING, keep_default_na=False)
    rebuilt = bdi.build_input(fields, model, mapping)
    committed = pd.read_csv(bdi.OUT_INPUT, keep_default_na=False)
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True), committed, check_dtype=False)
    # the name-only input is not changed by this work: same fields in the same order
    assert list(rebuilt["field"]) == list(fields["field"])
    assert not committed.loc[committed["ri"] == "ACTRIS", "flagged"].eq("no").any()


def test_the_script_runs_the_extraction_when_the_model_csv_is_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bdi, "IN_MODEL", tmp_path / "missing.csv")
    monkeypatch.setattr(bdi.dmd, "main", lambda argv: calls.append(argv) or 0)
    assert bdi.ensure_model_definitions() == 0 and calls == [[]]


def test_a_local_model_csv_that_differs_from_the_record_stops_the_run(tmp_path, monkeypatch, capsys):
    local = tmp_path / "deims_model_definitions.csv"
    local.write_text("changed\n", encoding="utf-8")
    monkeypatch.setattr(bdi, "IN_MODEL", local)
    assert bdi.ensure_model_definitions() == 1
    assert "CHECKSUM MISMATCH" in capsys.readouterr().err
