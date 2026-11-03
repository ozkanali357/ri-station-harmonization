"""Definition-backed tables: text rule, separation of pairs and input check, offline.

A character-trigram hashing embedder stands in for MiniLM. These tests check structure and rules; they say
nothing about MiniLM scores.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import compare_fields as cf
from scripts import compare_fields_definition_backed as cdb
from test_compare_fields import FIELDS, trigram_embedder

ROOT = Path(__file__).resolve().parents[1]
DEFINED = FIELDS.copy()
DEFINED.loc[DEFINED["field"] == "geographic.coordinates", "definition"] = "Point coordinates as GeoJSON."


def test_text_is_the_definition_alone_where_one_exists_else_the_field_name():
    prepared = cdb.prepare_definition_backed(DEFINED)
    text = dict(zip(prepared["field"], prepared["text"]))
    assert text["geographic.coordinates"] == "Point coordinates as GeoJSON."
    assert text["hasLatitude"] == "Decimal degrees in WGS84/GRS80"
    assert text["title"] == "title" and text["name"] == "name"
    assert not prepared["field"].str.startswith("contact.").any()
    assert dict(zip(prepared["field"], prepared["name_text"]))["geographic.coordinates"] == "geographic.coordinates"


def test_three_separate_tables_and_name_scores_equal_the_name_only_scores(tmp_path):
    prepared = cdb.prepare_definition_backed(DEFINED)
    outputs = cdb.write_tables(prepared, trigram_embedder, tmp_path)
    assert set(outputs) == {"DEIMS-ICOS", "DEIMS-ACTRIS", "ICOS-ACTRIS"}
    first = pd.read_csv(cdb.pair_file("DEIMS", "ICOS", tmp_path))
    assert list(first.columns) == cf.OUTPUT_COLUMNS
    assert set(first["ri_a"]) == {"DEIMS"} and set(first["ri_b"]) == {"ICOS"}
    name_only = cf.rank_pair(cf.prepare_fields(DEFINED), "DEIMS", "ICOS", trigram_embedder)
    cols = ["field_a", "field_b", "tfidf_name_sim", "minilm_name_sim"]
    pd.testing.assert_frame_equal(first[cols], name_only[cols])
    row = first.set_index(["field_a", "field_b"]).loc[("geographic.coordinates", "hasLatitude")]
    assert row["definition_used_a"] and row["definition_used_b"]
    assert row["minilm_text_sim"] != row["minilm_name_sim"]


def test_file_names_do_not_collide_with_the_name_only_tables():
    for ri_a, ri_b in cf.PAIR_ORDER:
        assert cdb.pair_file(ri_a, ri_b) != cf.pair_file(ri_a, ri_b)
    assert cdb.RUN_FILE != cf.RUN_FILE and cdb.IN_FILE != cf.IN_FILE


def test_input_check_catches_a_changed_input_file(tmp_path):
    data = tmp_path / "in.csv"
    data.write_text("a\n1\n", encoding="utf-8")
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"output": {"sha256": cf._sha256_file(data)}}), encoding="utf-8")
    assert cdb.input_matches_recorded_hash(data, run)[0]
    data.write_text("a\n2\n", encoding="utf-8")
    ok, message = cdb.input_matches_recorded_hash(data, run)
    assert not ok and "does not match" in message
    assert not cdb.input_matches_recorded_hash(data, tmp_path / "missing.json")[0]


LOCAL_ONLY = pytest.mark.skipif(not cdb.IN_FILE.exists(),
                                reason="the definition-backed input holds the DEIMS text and is produced locally")


@LOCAL_ONLY
def test_local_input_matches_its_recorded_hash():
    assert cdb.input_matches_recorded_hash()[0]


@LOCAL_ONLY
def test_manifest_records_text_rule_pin_and_working_tree_state():
    fields = cdb.prepare_definition_backed(pd.read_csv(cdb.IN_FILE))
    pin = cf.load_pin()
    manifest = cdb.build_manifest(
        fields=fields, outputs={}, pin=pin, installed=cf.installed_versions(), drift={}, loaded_commit=None,
        verification="not run in this test", weights_verified=False, allow_unverified=True,
        git={"head": "abc", "working_tree_clean": False, "uncommitted_paths": ["x"]},
        now=__import__("datetime").datetime(2026, 11, 3))
    assert manifest["model"]["revision_pinned"] == pin["revision"]
    assert manifest["git_working_tree_clean"] is False and manifest["git_uncommitted_paths"] == ["x"]
    assert "definition verbatim" in manifest["text_rule"]
    assert manifest["field_counts"] == {"DEIMS": 81, "ICOS": 20, "ACTRIS": 16}
    assert manifest["fields_with_definition"]["ACTRIS"] == 3
    assert manifest["definition_sources"]["DEIMS"]["version"] == 1.43
