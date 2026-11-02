"""ICOS field definitions: parsing, flagging and the cache, all offline.

The two sample files in ``tests/data/`` are the real endpoint responses fetched on 2026-11-02
(``outputs/field_definitions_raw/``), reduced to five predicates.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import icos_field_definitions as icos

DATA = Path(__file__).parent / "data"
PROPS = json.loads((DATA / "icos_field_predicates_sample.json").read_text(encoding="utf-8"))
DEFS = json.loads((DATA / "icos_field_definitions_sample.json").read_text(encoding="utf-8"))


def test_local_name_matches_the_existing_field_names():
    assert icos.local_name("http://meta.icos-cp.eu/ontologies/cpmeta/hasLatitude") == "hasLatitude"
    assert icos.local_name("http://www.w3.org/ns/dcat#theme") == "dcat#theme"


def test_parse_predicates_is_sorted_and_distinct():
    uris = icos.parse_predicates(PROPS)
    assert uris == sorted(set(uris))
    assert len(uris) == 5


def test_only_rdfs_comment_counts_as_a_definition():
    rows = {r["field"]: r for r in icos.build_rows(icos.parse_predicates(PROPS), icos.parse_definitions(DEFS))}
    assert rows["hasLatitude"]["definition"] == "Decimal degrees in WGS84/GRS80"
    assert rows["hasLatitude"]["flagged"] == "no"
    assert rows["hasLatitude"]["definition_source"] == icos.DEFINITION_SOURCE
    # hasName has an rdfs:label ("Name") but no rdfs:comment: a label is not a definition.
    assert rows["hasName"]["definition"] == ""
    assert rows["hasName"]["label_published"] == "Name"
    assert rows["hasName"]["flagged"] == "yes"
    # a predicate the endpoint says nothing about stays flagged
    assert rows["hasAtcId"]["flagged"] == "yes"
    assert rows["identifier"]["flagged"] == "yes"


def test_several_distinct_comments_are_kept_not_picked():
    payload = {"results": {"bindings": [
        {"p": {"value": "http://x/p"}, "comment": {"value": "first"}},
        {"p": {"value": "http://x/p"}, "comment": {"value": "second"}},
        {"p": {"value": "http://x/p"}, "comment": {"value": "first"}},
    ]}}
    row = icos.build_rows(["http://x/p"], icos.parse_definitions(payload))[0]
    assert row["definition"] == "first || second"
    assert row["n_comments"] == 2


def test_defs_query_lists_every_predicate_once_and_asks_for_comments():
    query = icos.defs_query(["http://b/q", "http://a/p"])
    assert query.index("<http://a/p>") < query.index("<http://b/q>")
    assert icos.RDFS_COMMENT in query
    assert "skos" not in query.lower()


def _fake_requests(monkeypatch, bodies):
    calls = []

    class Response:
        status_code = 200

        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

    def post(url, data, headers, timeout):
        calls.append(data["query"])
        return Response(bodies[len(calls) - 1])

    import requests
    monkeypatch.setattr(requests, "post", post)
    return calls


def test_run_caches_bytes_verbatim_and_second_run_is_offline(tmp_path, monkeypatch):
    bodies = [(DATA / "icos_field_predicates_sample.json").read_bytes(),
              (DATA / "icos_field_definitions_sample.json").read_bytes()]
    calls = _fake_requests(monkeypatch, bodies)
    cache = tmp_path / "cache"
    df = icos.run(cache, tmp_path / "defs.csv", tmp_path / "run.json")
    assert len(calls) == 2
    assert (cache / "icos_station_predicates.json").read_bytes() == bodies[0]
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["responses"]["icos_predicate_definitions.json"]
    assert entry["sha256"] == hashlib.sha256(bodies[1]).hexdigest()
    assert entry["retrieved_at"] and entry["http_status"] == 200
    assert (df["flagged"] == "no").sum() == 2  # countryCode and hasLatitude carry a comment

    again = icos.run(cache, tmp_path / "defs2.csv", tmp_path / "run2.json", offline=True)
    assert len(calls) == 2  # nothing fetched
    pd.testing.assert_frame_equal(df, again)
    run_info = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_info["n_with_definition"] == 2 and run_info["n_flagged"] == 3


def test_offline_without_cache_fails_and_tampered_cache_is_detected(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        icos.run(tmp_path / "empty", tmp_path / "d.csv", tmp_path / "r.json", offline=True)

    bodies = [(DATA / "icos_field_predicates_sample.json").read_bytes(),
              (DATA / "icos_field_definitions_sample.json").read_bytes()]
    _fake_requests(monkeypatch, bodies)
    cache = tmp_path / "cache"
    icos.run(cache, tmp_path / "d.csv", tmp_path / "r.json")
    (cache / "icos_predicate_definitions.json").write_bytes(b'{"results": {"bindings": []}}')
    with pytest.raises(RuntimeError, match="checksum"):
        icos.run(cache, tmp_path / "d.csv", tmp_path / "r.json", offline=True)


def test_committed_raw_responses_match_their_checksums():
    cache = Path(__file__).resolve().parents[1] / "outputs" / "field_definitions_raw"
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["responses"]) == {"icos_station_predicates.json", "icos_predicate_definitions.json"}
    for name, entry in manifest["responses"].items():
        assert hashlib.sha256((cache / name).read_bytes()).hexdigest() == entry["sha256"]
        assert entry["endpoint"] == icos.ICOS_SPARQL and entry["retrieved_at"]
