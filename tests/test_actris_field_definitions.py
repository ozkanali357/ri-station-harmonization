import pytest
"""ACTRIS field definitions: API description and vocabulary candidates, all offline.

``tests/data/actris_openapi_facility_sample.json`` and ``tests/data/actris_vocab_search_facility_type_sample.json``
are reduced copies of the responses fetched on 2026-11-03; they hold property types, labels and URIs only. No
ACTRIS vocabulary definition text is stored anywhere in this repository (the vocabulary's licence is unknown).
"""

import json
from pathlib import Path

import pandas as pd

from scripts import actris_field_definitions as afd

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parents[1]
OPENAPI = json.loads((DATA / "actris_openapi_facility_sample.json").read_text(encoding="utf-8"))
SEARCH = json.loads((DATA / "actris_vocab_search_facility_type_sample.json").read_text(encoding="utf-8"))
URI = "https://vocabulary.actris.nilu.no/actris_vocab/facilitytype"
EMPTY = {"results": []}


def test_label_rule_reads_underscores_as_spaces():
    assert afd.label_for("facility_type") == "facility type"
    assert [h["uri"] for h in afd.exact_label_hits(SEARCH, "facility_type")] == [URI]
    assert afd.exact_label_hits(SEARCH, "facility") == []  # a prefix match is not a label match


def test_api_description_is_empty_when_the_schema_gives_none():
    assert afd.facility_property_description(OPENAPI, "name") == (True, "")
    assert afd.facility_property_description(OPENAPI, "wmo_region") == (False, "")


def test_a_label_equal_concept_is_a_candidate_not_a_field_definition():
    searches = {(v, f): (SEARCH if (v, f) == ("actris_vocab", "facility_type") else EMPTY)
                for v in afd.VOCABULARIES for f in ("facility_type", "name")}
    rows = afd.build_rows(["facility_type", "name"], OPENAPI, searches)
    by_field = {r["field"]: r for r in rows}
    ft = by_field["facility_type"]
    assert ft["vocabulary_concept_uri"] == URI and ft["vocabulary_label_match"] == "actris_vocab: facility type"
    assert ft["used_as_field_definition"] == "no" and ft["flagged"] == "yes"
    assert by_field["name"]["vocabulary_label_match"] == "" and by_field["name"]["flagged"] == "yes"


def test_an_api_description_would_unflag_the_field():
    api = json.loads(json.dumps(OPENAPI))
    api["components"]["schemas"]["Facility"]["properties"]["name"]["description"] = "Synthetic description"
    searches = {(v, "name"): EMPTY for v in afd.VOCABULARIES}
    row = afd.build_rows(["name"], api, searches)[0]
    assert row["flagged"] == "no" and row["used_as_field_definition"] == "yes"


def test_output_structure_holds_no_vocabulary_text_and_flags_every_field():
    """Checks the script's own output structure on synthetic input; it needs no file from outputs/."""
    fields = ["facility_type", "name", "identifier"]
    searches = {(v, f): (SEARCH if (v, f) == ("actris_vocab", "facility_type") else EMPTY)
                for v in afd.VOCABULARIES for f in fields}
    frame = pd.DataFrame(afd.build_rows(fields, OPENAPI, searches), columns=afd.OUTPUT_COLUMNS)
    assert list(frame.columns) == ["field", "api_description_present", "api_description", "vocabulary_label_match",
                                   "vocabulary_concept_uri", "used_as_field_definition", "flagged"]
    assert not any("definition" in c and c != "used_as_field_definition" for c in frame.columns)
    assert set(frame["field"]) == set(fields)
    assert (frame["flagged"] == "yes").all() and (frame["used_as_field_definition"] == "no").all()
    assert not frame.apply(lambda c: c.astype(str).str.contains(afd.EMAIL_RE)).any().any()
    assert not hasattr(afd, "concept_definition")  # the concept's definition text is never read


def test_committed_list_covers_the_16_fields_in_the_scripts_structure():
    frame = pd.read_csv(ROOT / "outputs" / "actris_field_definitions.csv", keep_default_na=False)
    assert list(frame.columns) == afd.OUTPUT_COLUMNS
    final = pd.read_csv(ROOT / "outputs" / "final_field_comparison.csv")
    assert set(frame["field"]) == set(final.loc[final["ri"] == "ACTRIS", "field"])
    assert not (frame["used_as_field_definition"].eq("yes") & frame["api_description_present"].eq("no")).any()
