"""Offline tests for ``scripts/dictionary_vocab_fetch.py`` with tiny hand-written Turtle fixtures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from scripts import dictionary_vocab_fetch as vf

CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
BY = "https://creativecommons.org/licenses/by/4.0/"

ACTRIS_TTL = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix pav: <http://purl.org/pav/> .
@prefix a: <https://vocabulary.actris.nilu.no/actris_vocab/> .
a: a skos:ConceptScheme ; dc:license <{CC0}> ; pav:version "1.2.2"@en ; pav:lastUpdatedOn "2026-07-28"@en .
a:airtemperature a skos:Concept ; skos:prefLabel "air temperature"@en ; skos:altLabel "temperature of air"@en ;
  skos:definition "Temperature of the air."@en .
"""
ENVTHES_TTL = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix e: <http://vocabs.lter-europe.net/EnvThes/> .
e: a skos:ConceptScheme ; dct:license <{BY}> ; owl:versionInfo "5.0.16"@en .
e:1 a skos:Concept ; skos:prefLabel "soil temperature"@en, "Bodentemperatur"@de ; skos:definition "[GEMET] Heat of the soil."@en .
e:2 a skos:Concept ; skos:prefLabel "old term"@en ; owl:deprecated "true"@en ; dct:isReplacedBy e:1 .
e:3 a skos:Concept ; skos:prefLabel "wind"@en ; skos:definition "Moving air."@en .
"""


def test_scheme_statements_read_licence_version_and_dates():
    found = vf.scheme_statements(vf.parse_turtle(ACTRIS_TTL.encode()), "dump")
    assert [s["object"] for s in found["licence"]] == [CC0]
    assert [s["object"] for s in found["version"]] == ["1.2.2"]
    assert [s["object"] for s in found["dates"]] == ["2026-07-28"]


def test_concept_table_keeps_english_labels_deprecation_and_replacement():
    table = vf.concept_table(vf.parse_turtle(ENVTHES_TTL.encode()), "EnvThes", "5.0.16", BY)
    by = table.set_index("concept_uri")
    assert by.loc["http://vocabs.lter-europe.net/EnvThes/1", "pref_label"] == "soil temperature"
    assert bool(by.loc["http://vocabs.lter-europe.net/EnvThes/2", "deprecated"]) is True
    assert by.loc["http://vocabs.lter-europe.net/EnvThes/2", "replaced_by"] == "http://vocabs.lter-europe.net/EnvThes/1"
    assert not by.loc["http://vocabs.lter-europe.net/EnvThes/3", "deprecated"]
    assert set(table["vocabulary_licence"]) == {BY}


def test_definition_source_tags_count_bracketed_prefixes():
    table = vf.concept_table(vf.parse_turtle(ENVTHES_TTL.encode()), "EnvThes", "5.0.16", BY)
    assert vf.definition_source_tags(table) == {"(no definition)": 1, "(no tag)": 1, "[GEMET]": 1}


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200, url: str = "u"):
        self.content, self.status_code, self.url = content, status, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, answers: dict[str, FakeResponse]):
        self.answers, self.calls = answers, []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.answers[url]


def test_fetch_file_caches_verbatim_records_checksum_and_never_refetches(tmp_path):
    record = {"files": {}}
    session = FakeSession({"http://x/a": FakeResponse(b"raw bytes\n", url="http://x/a")})
    first = vf.fetch_file("v/a.ttl", "http://x/a", tmp_path, record, offline=False, session=session)
    again = vf.fetch_file("v/a.ttl", "http://x/a", tmp_path, record, offline=False, session=session)
    assert first == again == b"raw bytes\n" == (tmp_path / "v" / "a.ttl").read_bytes()
    assert session.calls == ["http://x/a"]
    info = record["files"]["v/a.ttl"]
    assert info["sha256"] == vf._sha256(b"raw bytes\n") and info["bytes"] == 10 and info["retrieved_at"]


def test_fetch_file_records_a_404_and_returns_none(tmp_path):
    record = {"files": {}}
    session = FakeSession({"http://x/l": FakeResponse(b"nope", 404)})
    assert vf.fetch_file("v/LICENSE", "http://x/l", tmp_path, record, offline=False, session=session) is None
    assert record["files"]["v/LICENSE"]["status"] == 404 and not (tmp_path / "v" / "LICENSE").exists()
    assert vf.fetch_file("v/LICENSE", "http://x/l", tmp_path, record, offline=False, session=session) is None
    assert session.calls == ["http://x/l"]


def test_offline_with_empty_cache_fails_instead_of_fetching(tmp_path):
    with pytest.raises(FileNotFoundError):
        vf.fetch_file("v/a.ttl", "http://x/a", tmp_path, {"files": {}}, offline=True)


def _spec(licence_rule):
    return {"title": "t", "scheme_uri": "s", "definitions_committable_if_licence": licence_rule,
            "files": [("dump", "v/dump.ttl", "http://x/dump", "dump")]}


def test_only_a_cc0_vocabulary_has_committable_definitions(tmp_path):
    record = {"files": {}}
    session = FakeSession({"http://x/dump": FakeResponse(ACTRIS_TTL.encode())})
    facts, concepts = vf.analyse_vocabulary("actris_vocab", _spec("CC0-1.0"), tmp_path, record, False, session)
    assert facts["definition_text_committable"] is True and facts["version"] == "1.2.2"
    assert facts["declared_licences"] == [CC0] and list(concepts["vocabulary_licence"]) == [CC0]

    (tmp_path / "v" / "dump.ttl").write_bytes(ENVTHES_TTL.encode())
    facts, _ = vf.analyse_vocabulary("EnvThes", _spec(None), tmp_path, record, True)
    assert facts["definition_text_committable"] is False and facts["declared_licences"] == [BY]
    assert facts["concepts"] == 3 and facts["concepts_deprecated"] == 1
    assert "NOT committable" in facts["definition_text_rule"]


def test_a_cc0_vocabulary_with_an_extra_licence_statement_is_not_committable(tmp_path):
    mixed = ACTRIS_TTL.replace("pav:version", f"dc:license <{BY}> ; pav:version")
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "dump.ttl").write_bytes(mixed.encode())
    facts, _ = vf.analyse_vocabulary("actris_vocab", _spec("CC0-1.0"), tmp_path, {"files": {}}, True)
    assert facts["definition_text_committable"] is False
