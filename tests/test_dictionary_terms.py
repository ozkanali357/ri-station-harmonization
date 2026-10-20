"""Offline tests for the Finnish variable-term table (``scripts/dictionary_terms.py``).

Fixtures in ``tests/data/``:

* ``dictionary_icos_sample.json``: nine real bindings from the ICOS SPARQL response (retrieved
  2026-10-20) for the stations ``AS_SMR`` and ``ES_FI-Hyy``.
* ``dictionary_actris_counts_sample.json`` and ``dictionary_actris_examples_sample.json``: real
  ACTRIS ``/api/metadata/search`` responses (retrieved 2026-10-20), cut down to a few facilities and
  terms; the example datasets keep only the facility id, repository, PID and the variable fields.
* ``dictionary_deims_sample.json``: real ``observedProperties`` entries of four Finnish DEIMS sites.
  The ``contact`` block and the ``soils`` text are synthetic and exist to prove they are not read.
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from scripts import dictionary_terms as dt

DATA = Path(__file__).parent / "data"
SMR = "http://meta.icos-cp.eu/resources/stations/AS_SMR"
HYY = "http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy"
VAR = "http://meta.icos-cp.eu/resources/dcat/var/"
HYY_SITE = "663dac80-211d-4c19-a356-04ee0da0f0eb"
VIIKKI = "5d64b207-5a68-410f-a2ec-cf0e05d4c0ac"
KUMPULA = "5c41d138-7910-4827-a8ac-0273a5d09a74"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture()
def icos_payload():
    return _load("dictionary_icos_sample.json")


@pytest.fixture()
def deims_details():
    return _load("dictionary_deims_sample.json")


# --- ICOS -------------------------------------------------------------------------------------

def test_icos_terms_are_one_row_per_concept_with_verbatim_facts(icos_payload):
    records, _ = dt.icos_terms(icos_payload, {SMR, HYY})
    by_uri = {r["term_uri"]: r for r in records}
    assert len(records) == len(by_uri) == 9
    swc = by_uri[VAR + "SWC_n"]
    assert swc["term_label"] == "volumetric soil water content"
    assert swc["definition"] == "average across several sensors at same depth"
    assert swc["alt_label"] == r"^SWC_\d{1,2}$"            # a regular expression, kept as published
    assert swc["id_scheme"] == "ICOS variable concept URI"
    assert by_uri[VAR + "TS_n"]["definition"] == ""          # no rdfs:comment published, none invented


def test_icos_close_match_is_kept_as_published_and_labels_can_repeat(icos_payload):
    records, _ = dt.icos_terms(icos_payload, {SMR, HYY})
    wind = [r for r in records if r["term_label"] == "wind speed"]
    assert len(wind) == 3                                   # WS, ETC_WS, WS_F share one label
    assert {r["published_match_uri"] for r in wind} == {"https://vocab.nerc.ac.uk/collection/P07/current/CFSN0038/"}


def test_icos_records_using_a_term_are_only_the_stations_in_scope(icos_payload):
    records, coverage = dt.icos_terms(icos_payload, {HYY})
    by_uri = {r["term_uri"]: r for r in records}
    assert VAR + "AT" not in by_uri                          # only AS_SMR has it, and AS_SMR is out of scope
    assert all(r["record_ids"] == [HYY] for r in records)
    assert coverage["stations_in_response"] == 2 and coverage["stations_with_terms_in_scope"] == 1


def test_icos_term_used_by_two_stations_lists_both(icos_payload):
    extra = copy.deepcopy(icos_payload)
    row = copy.deepcopy(next(b for b in extra["results"]["bindings"] if b["theme"]["value"] == VAR + "TS_n"))
    row["station"]["value"] = SMR
    extra["results"]["bindings"].append(row)
    records, _ = dt.icos_terms(extra, {SMR, HYY})
    assert next(r for r in records if r["term_uri"] == VAR + "TS_n")["record_ids"] == sorted([HYY, SMR])


def test_icos_non_variable_themes_are_reported_not_kept(icos_payload):
    extra = copy.deepcopy(icos_payload)
    row = copy.deepcopy(extra["results"]["bindings"][0])
    row["theme"]["value"] = "http://example.org/not-a-variable"
    extra["results"]["bindings"].append(row)
    records, coverage = dt.icos_terms(extra, {SMR, HYY})
    assert all(r["term_uri"].startswith(VAR) for r in records)
    assert coverage["non_variable_themes_skipped"] == ["http://example.org/not-a-variable"]


def test_icos_query_that_hits_its_limit_is_refused(tmp_path, monkeypatch):
    cache = tmp_path / dt.DICT_DIR
    cache.mkdir()
    bindings = [{"station": {"value": "s"}, "theme": {"value": VAR + "x"}}] * 3
    (cache / dt.ICOS_CACHE_FILE).write_text(json.dumps({"results": {"bindings": bindings}}), encoding="utf-8")
    monkeypatch.setattr(dt, "ICOS_LIMIT", 3)
    with pytest.raises(RuntimeError, match="LIMIT"):
        dt.fetch_icos_themes(tmp_path, offline=True)


# --- ACTRIS -----------------------------------------------------------------------------------

@pytest.fixture()
def actris_counts():
    return _load("dictionary_actris_counts_sample.json")["response"]


@pytest.fixture()
def actris_examples():
    return {k: v["response"] for k, v in _load("dictionary_actris_examples_sample.json").items()}


def test_actris_counts_are_per_term_and_facility(actris_counts):
    counts = dt.actris_term_counts(actris_counts)
    assert counts["air temperature"] == {"4iaj": 1, "d23p": 1, "ko6m": 2, "p0ob": 1}
    assert sum(counts["precipitation accumulated volume flux"].values()) == 139
    assert counts["precipitation sulphate mass concentration"].keys() >= {"9w63"}


def test_actris_truncated_aggregation_is_refused(actris_counts):
    bad = copy.deepcopy(actris_counts)
    fac = next(v for k, v in bad["aggregations"].items() if k.endswith("#fac"))
    next(v for k, v in fac["buckets"][0].items() if k.endswith("#vn"))["sum_other_doc_count"] = 3
    with pytest.raises(RuntimeError, match="truncated"):
        dt.actris_term_counts(bad)


def test_actris_attributes_come_from_the_variable_with_that_name_only(actris_examples):
    combos, total, repos = dt.actris_attributes("air temperature", actris_examples["air temperature"])
    assert combos and all(c.get("matrix") for c in combos)
    assert total == 5 and repos
    # the example datasets list many other variables; none of their attributes may leak in
    assert not any("sulphate" in json.dumps(c) for c in combos)


def test_actris_terms_carry_counts_attributes_and_no_invented_identifiers(actris_counts, actris_examples):
    records, coverage = dt.actris_terms(dt.actris_term_counts(actris_counts), actris_examples)
    row = next(r for r in records if r["term_label"] == "air temperature")
    assert row["ri"] == "ACTRIS" and row["term_uri"] == "" and row["definition"] == ""
    assert row["n_datasets"] == 5 and row["record_ids"] == ["4iaj", "d23p", "ko6m", "p0ob"]
    assert json.loads(row["published_attributes"])
    assert coverage["count_mismatches"] == []


def test_actris_count_mismatch_between_aggregation_and_examples_is_reported(actris_counts, actris_examples):
    counts = dt.actris_term_counts(actris_counts)
    counts["air temperature"]["ko6m"] += 5
    _, coverage = dt.actris_terms(counts, actris_examples)
    assert coverage["count_mismatches"] == [{"term": "air temperature", "aggregation": 10, "example_query": 5}]


def test_actris_fetch_writes_bytes_verbatim_and_offline_needs_the_cache(tmp_path, monkeypatch):
    raw = b'{"response": {"hits": {"total": {"value": 0}, "hits": []}}}'

    class Reply:
        content = raw

        def raise_for_status(self):
            pass

    calls = []
    monkeypatch.setattr(dt.requests, "post", lambda *a, **k: calls.append(k["json"]) or Reply())
    with pytest.raises(FileNotFoundError):
        dt.fetch_actris_examples(tmp_path, ["ko6m"], ["air temperature"], offline=True)
    dt.fetch_actris_examples(tmp_path, ["ko6m"], ["air temperature"])
    cached = tmp_path / dt.DICT_DIR / dt._example_file("air temperature")
    assert cached.read_bytes() == raw
    assert calls[0]["search"]["query"]["bool"]["must"][1] == {"term": {"variables.variable_name.keyword": "air temperature"}}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    page = manifest["sources"]["dictionary_actris_examples"]["pages"][0]
    assert page["sha256"] == dt._sha256_bytes(raw) and page["term"] == "air temperature" and page["retrieved_at"]
    dt.fetch_actris_examples(tmp_path, ["ko6m"], ["air temperature"], offline=True)   # now served from cache
    assert len(calls) == 1


# --- DEIMS ------------------------------------------------------------------------------------

def test_deims_terms_are_label_uri_pairs_with_their_sites(deims_details):
    records, coverage = dt.deims_terms(deims_details)
    temp = next(r for r in records if r["term_label"] == "air temperature")
    assert temp["term_uri"] == "http://vocabs.lter-europe.net/EnvThes/22035"
    assert temp["record_ids"] == sorted([HYY_SITE, VIIKKI])
    assert temp["id_scheme"] == "EnvThes URI" and temp["field_path"].endswith("observedProperties[]")
    assert coverage["sites_with_observed_properties"] == 3     # the fourth site lists none


def test_deims_same_uri_under_two_labels_is_flagged_on_both_rows(deims_details):
    records, coverage = dt.deims_terms(deims_details)
    rows = [r for r in records if r["term_uri"].endswith("/22106")]
    assert {r["term_label"] for r in rows} == {"diffuse radiation intensity", "diffuse solar radiation intensity"}
    flags = {r["term_label"]: r["uri_label_variants"] for r in rows}
    assert flags["diffuse radiation intensity"] == "diffuse solar radiation intensity"
    assert coverage["uris_with_several_labels"] == 1
    # the same label under two URIs is two rows, not merged
    assert len([r for r in records if r["term_label"] == "diffuse radiation intensity"]) == 2


def test_deims_site_with_no_observed_properties_adds_nothing(deims_details):
    records, _ = dt.deims_terms(deims_details)
    assert KUMPULA not in {i for r in records for i in r["record_ids"]}


def test_deims_contact_block_and_soils_text_never_reach_the_table(deims_details):
    records, coverage = dt.deims_terms(deims_details)
    names = {("eLTER", u): d["title"] for u, d in deims_details.items()}
    table = dt.build_table(records, names, {"eLTER": "2026-10-20T00:00:00+00:00"})
    text = table.to_csv(index=False) + json.dumps(coverage)
    assert "example.invalid" not in text and "Test Person" not in text and "Podzol" not in text
    assert coverage["sites_with_free_text_soils_field"] == 1   # counted, text not copied


# --- scope pre-filter and table ---------------------------------------------------------------

@pytest.mark.parametrize("label, domain", [
    ("air temperature", "meteorology"), ("relative humidity", "meteorology"), ("wind speed", "meteorology"),
    ("air velocity magnitude", "meteorology"), ("atmospheric pressure", "meteorology"),
    ("precipitation (total)", "meteorology"), ("precipitation accumulated volume flux", "meteorology"),
    ("incoming shortwave radiation", "meteorology"), ("downward solar light flux density", "meteorology"),
    ("soil temperature", "soil"), ("volumetric soil water content", "soil"), ("soil heat flux", "soil"),
    # not matched: chemistry in precipitation, water temperature, unrelated terms
    ("precipitation sulphate mass concentration", ""), ("water temperature", ""), ("species richness", ""),
])
def test_scope_candidate_rules(label, domain):
    assert dt.scope_candidate(label)[0] == domain


def test_scope_candidate_names_the_rule_that_matched():
    assert dt.scope_candidate("wind speed") == ("meteorology", "wind")
    assert dt.scope_candidate("species richness") == ("", "")


def test_build_table_columns_counts_and_blank_domain(icos_payload):
    records, _ = dt.icos_terms(icos_payload, {SMR, HYY})
    names = {("ICOS", SMR): "Station A", ("ICOS", HYY): "Hyytiala"}
    table = dt.build_table(records, names, {"ICOS": "2026-10-20T00:00:00+00:00"})
    assert list(table.columns) == dt.COLUMNS
    assert (table.domain_published == "").all()              # none of the three RIs publishes one
    assert (table.n_datasets == "").all()                    # ICOS has no dataset count here
    row = table[table.term_uri == VAR + "AT"].iloc[0]
    assert (row.n_finnish_records, row.finnish_record_ids, row.finnish_record_names) == (1, SMR, "Station A")
    assert row.scope_candidate == "meteorology" and row.fetched_at.startswith("2026-10-20")
