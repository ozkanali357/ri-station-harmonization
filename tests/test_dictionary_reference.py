"""Offline tests for the reference-vocabulary lookups (``scripts/dictionary_reference.py``).

``tests/data/dictionary_reference_sample.json`` holds real Skosmos / NERC responses retrieved on
2026-10-20, cut down: English labels only, no creator fields, a shortened ``skos:related`` list, and
index entries for a handful of concepts (EnvThes ``air temperature``, ``diffuse solar radiation
intensity`` with its alternative labels, ``soil temperature``, ``wind speed``; SO ``Meteorological
data``; eLTER_CL ``soil``; ACTRIS ``air temperature`` and ``air pressure``). The term tables below
are small hand-written frames in the shape of ``outputs/dictionary_terms_finland.csv``.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from scripts import dictionary_reference as dr

DATA = json.loads((Path(__file__).parent / "data" / "dictionary_reference_sample.json").read_text(encoding="utf-8"))
E = "http://vocabs.lter-europe.net/EnvThes/"
NERC = "https://vocab.nerc.ac.uk/collection/P07/current/CFSN0038/"
ICOS_WS = "http://meta.icos-cp.eu/resources/dcat/var/WS"
ACTRIS_AT = "https://vocabulary.actris.nilu.no/actris_vocab/airtemperature"


def _terms(rows):
    cols = ["ri", "term_label", "term_uri", "published_match_uri"]
    return pd.DataFrame([{**dict.fromkeys(cols, ""), **r} for r in rows], columns=cols)


@pytest.fixture()
def label_index():
    return {v: dr.build_label_index(e) for v, e in DATA["index"].items()}


# --- parsing ----------------------------------------------------------------------------------

def test_label_index_separates_pref_and_alt_labels_and_ignores_case(label_index):
    hits = label_index["EnvThes"]["diffuse radiation intensity"]
    assert hits == [(E + "22106", "diffuse solar radiation intensity", "altLabel")]
    assert label_index["EnvThes"]["air temperature"] == [(E + "22035", "air temperature", "prefLabel")]
    assert label_index["EnvThes"]["temperature of air"][0][2] == "altLabel"


def test_concept_facts_reads_label_alts_definition_and_broader_label():
    facts = dr.concept_facts(DATA["concepts"][E + "22035"], E + "22035")
    assert facts["pref"] == "air temperature" and facts["alt"] == ["temperature of air"]
    assert facts["definition"].startswith("[GEMET] The temperature of the atmosphere")
    assert facts["broader"] == [f"variable ({E}20935)"]
    assert facts["deprecated"] is False and facts["replaced_by"] == ""


def test_deprecated_concept_keeps_its_replacement():
    facts = dr.concept_facts(DATA["concepts"][E + "10039"], E + "10039")
    assert facts["deprecated"] is True and facts["replaced_by"] == E + "22281"
    assert dr.concept_facts(DATA["concepts"][E + "10333"], E + "10333")["replaced_by"] == ""


def test_concept_facts_is_none_when_the_response_has_no_node_for_the_uri():
    assert dr.concept_facts(DATA["concepts"][E + "22035"], E + "99999") is None


def test_nerc_facts_read_the_flat_json_ld():
    facts = dr.nerc_facts(DATA["nerc"][NERC])
    assert facts["pref"] == "wind_speed" and facts["deprecated"] is False
    assert facts["definition"].startswith("Speed is the magnitude of velocity")
    assert "http://vocab.nerc.ac.uk/standard_name/wind_speed/" in facts["exact"]


# --- lookups ----------------------------------------------------------------------------------

def test_deims_term_gets_a_uri_lookup_and_no_label_hit_on_its_own_concept(label_index):
    terms = _terms([{"ri": "eLTER", "term_label": "air temperature", "term_uri": E + "22035"}])
    plan = dr.plan_lookups(terms, label_index)
    assert [(p["lookup"], p["vocab"], p["uri"]) for p in plan] == [("uri_resolves", "EnvThes", E + "22035")]


def test_published_label_match_is_pref_alt_or_neither():
    facts = {("EnvThes", E + "22106"): dr.concept_facts(DATA["concepts"][E + "22106"], E + "22106"),
             ("EnvThes", E + "22125"): dr.concept_facts(DATA["concepts"][E + "22125"], E + "22125")}
    plan = [{"ri": "eLTER", "term_label": label, "term_uri": uri, "lookup": "uri_resolves", "vocab": "EnvThes", "uri": uri, "kind": ""}
            for label, uri in (("diffuse solar radiation intensity", E + "22106"), ("diffuse radiation intensity", E + "22106"),
                               ("leaf nutrient", E + "22125"))]
    table = dr.assemble(plan, facts, {})
    got = dict(zip(table.term_label, table.published_label_matches))
    assert got == {"diffuse solar radiation intensity": "prefLabel", "diffuse radiation intensity": "altLabel", "leaf nutrient": "neither"}
    assert table[table.term_label == "leaf nutrient"].iloc[0].reference_pref_label == "global radiation irradiance"


def test_unresolvable_uri_is_a_not_found_row_not_a_guess():
    plan = [{"ri": "eLTER", "term_label": "wind speed", "term_uri": E + "22319", "lookup": "uri_resolves",
             "vocab": "EnvThes", "uri": E + "22319", "kind": ""}]
    row = dr.assemble(plan, {("EnvThes", E + "22319"): None}, {}).iloc[0]
    assert row.status == "not_found" and row.reference_pref_label == "" and row.reference_deprecated == ""


def test_icos_term_gets_label_hits_and_the_published_nerc_match(label_index):
    terms = _terms([{"ri": "ICOS", "term_label": "wind speed", "term_uri": ICOS_WS, "published_match_uri": NERC}])
    plan = dr.plan_lookups(terms, label_index)
    kinds = {(p["lookup"], p["vocab"]) for p in plan}
    assert kinds == {("published_match_uri", "NERC_P07"), ("label_equals_prefLabel", "EnvThes")}


def test_icos_close_match_to_an_unknown_vocabulary_is_not_followed(label_index):
    terms = _terms([{"ri": "ICOS", "term_label": "no such label", "term_uri": "u", "published_match_uri": "http://example.org/x"}])
    assert dr.plan_lookups(terms, label_index) == []


def test_actris_terms_are_also_looked_up_in_their_own_vocabulary_but_others_are_not(label_index):
    actris = _terms([{"ri": "ACTRIS", "term_label": "air temperature"}])
    icos = _terms([{"ri": "ICOS", "term_label": "air temperature", "term_uri": "http://meta.icos-cp.eu/resources/dcat/var/AT"}])
    assert {p["vocab"] for p in dr.plan_lookups(actris, label_index)} == {"EnvThes", "actris_vocab"}
    assert {p["vocab"] for p in dr.plan_lookups(icos, label_index)} == {"EnvThes"}


def test_label_hit_in_a_controlled_list_is_a_string_match_only(label_index):
    terms = _terms([{"ri": "ICOS", "term_label": "soil", "term_uri": "x"}])
    plan = dr.plan_lookups(terms, label_index)
    assert [(p["vocab"], p["uri"]) for p in plan] == [("elter_cl", "http://vocabs.lter-europe.net/elter_cl/10051")]


def test_assemble_columns_and_source_url(label_index):
    terms = _terms([{"ri": "ACTRIS", "term_label": "air temperature"}])
    plan = dr.plan_lookups(terms, label_index)
    facts = {("EnvThes", E + "22035"): dr.concept_facts(DATA["concepts"][E + "22035"], E + "22035"),
             ("actris_vocab", ACTRIS_AT): dr.concept_facts(DATA["concepts"][ACTRIS_AT], ACTRIS_AT)}
    table = dr.assemble(plan, facts, {("actris_vocab", ACTRIS_AT): "2026-10-20T01:00:00+00:00"})
    assert list(table.columns) == dr.COLUMNS
    own = table[table.reference_vocabulary == "actris_vocab"].iloc[0]
    assert own.lookup == "label_equals_prefLabel" and own.fetched_at.startswith("2026-10-20")
    assert own.source_url.startswith("https://vocabulary.actris.nilu.no/skosmos/rest/v1/actris_vocab/data?uri=https%3A%2F%2F")


def test_coverage_counts_terms_not_rows(label_index):
    terms = _terms([{"ri": "ICOS", "term_label": "air temperature", "term_uri": "a"},
                    {"ri": "ICOS", "term_label": "air temperature", "term_uri": "b"},
                    {"ri": "ICOS", "term_label": "no hit", "term_uri": "c"}])
    plan = dr.plan_lookups(terms, label_index)
    facts = {(p["vocab"], p["uri"]): dr.concept_facts(DATA["concepts"][E + "22035"], E + "22035") for p in plan}
    cov = dr.coverage(terms, dr.assemble(plan, facts, {}))["ICOS"]
    assert cov["terms"] == 3 and cov["terms_with_any_hit"] == 2 and cov["terms_with_label_hit_in_EnvThes"] == 2
    assert cov["terms_with_label_hit_in_elter_cl"] == 0


def test_scope_inventory_counts_prefLabel_entries_only():
    entries = DATA["index"]["EnvThes"]
    inv = dr.scope_inventory(entries)
    assert inv["concepts_in_index"] == 4                    # four concepts, ten index entries
    assert inv["meteorology"] == 3 and inv["soil"] == 1     # air temperature, diffuse radiation, wind speed; soil temperature


# --- cache ------------------------------------------------------------------------------------

class _Reply:
    status_code = 200
    url = "https://example.test/final"

    def __init__(self, content=b'{"indexConcepts": []}'):
        self.content = content

    def raise_for_status(self):
        pass


def test_cache_writes_verbatim_records_a_checksum_and_then_serves_offline(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dr.requests, "get", lambda url, **k: calls.append(url) or _Reply())
    cache = dr.Cache(tmp_path, offline=False)
    raw = cache.get("EnvThes/index_A.json", "https://example.test/index/A", {"lang": "en"})
    assert raw == b'{"indexConcepts": []}'
    page = cache.pages[f"{dr.REF_DIR}/EnvThes/index_A.json"]
    assert page["sha256"] == dr.hashlib.sha256(raw).hexdigest() and page["retrieved_at"] and page["url"] == "https://example.test/final"
    cache.write_manifest()
    again = dr.Cache(tmp_path, offline=True)
    assert again.get("EnvThes/index_A.json", "https://example.test/index/A") == raw
    assert again.retrieved_at("EnvThes/index_A.json") == page["retrieved_at"]
    assert len(calls) == 1
    with pytest.raises(FileNotFoundError):
        again.get("EnvThes/index_B.json", "https://example.test/index/B")


def test_cache_404_is_recorded_so_an_offline_rerun_gives_the_same_answer(tmp_path, monkeypatch):
    class Missing(_Reply):
        status_code = 404
        content = b"404 Bad Request : no concept found with given uri"

    calls = []
    monkeypatch.setattr(dr.requests, "get", lambda url, **k: calls.append(url) or Missing())
    cache = dr.Cache(tmp_path, offline=False)
    assert cache.get("EnvThes/concept_x.json", "https://example.test/data", allow_404=True) is None
    assert cache.not_found == ["https://example.test/final"]
    assert not (tmp_path / dr.REF_DIR / "EnvThes" / "concept_x.json").exists()
    cache.write_manifest()
    again = dr.Cache(tmp_path, offline=True)
    assert again.get("EnvThes/concept_x.json", "https://example.test/data", allow_404=True) is None
    assert again.not_found == ["https://example.test/final"] and len(calls) == 1


def test_a_404_that_is_not_allowed_raises(tmp_path, monkeypatch):
    class Missing(_Reply):
        status_code = 404

        def raise_for_status(self):
            raise dr.requests.HTTPError("404")

    monkeypatch.setattr(dr.requests, "get", lambda url, **k: Missing())
    with pytest.raises(dr.requests.HTTPError):
        dr.Cache(tmp_path, offline=False).get("EnvThes/index_A.json", "https://example.test/index/A")
