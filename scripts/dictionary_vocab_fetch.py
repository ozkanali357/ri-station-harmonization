"""Fetch and cache the reference vocabularies for the term-mapping step (milestone #8), verbatim.

What is fetched (``data/raw/dictionary_vocabularies/``, not committed), each with SHA-256, size,
HTTP status and retrieval time:

* the Turtle dump each vocabulary names as its own data source: the ``void:dataDump`` of the ACTRIS
  vocabulary and the ``ontologyresourceLocator`` of EnvThes, Standard Observations (``so``) and
  eLTER_CL (``elter_cl``) in their Skosmos concept-scheme metadata;
* the concept-scheme metadata as Skosmos serves it (``/rest/v1/<vocab>/data?uri=<scheme>``);
* licence documents the sources publish next to the data (repository README / LICENSE files). A
  missing file (404) is recorded as such.

``outputs/dictionary_vocabularies_run.json`` (committed) records, per vocabulary, the files with
checksums, every licence statement found (subject, predicate, object, and the file it came from), the
version, the dates, the concept counts and whether the definition text may be committed. Nothing in
it is a definition. The rule it applies:

* ACTRIS vocabulary: ``dc:license`` CC0 1.0 in the data and in Skosmos. Definitions may be committed
  with version and licence per row.
* EnvThes, Standard Observations, eLTER_CL: the sources *declare* CC BY 4.0 in their scheme metadata
  (the Standard Observations repository's LICENSE file says CC0 1.0 instead), but until the project owner
  has accepted that declaration (and the third-party ``[GEMET]`` definitions in EnvThes have been
  looked at) their definition text stays out of the repository: ``definition_text_committable`` is
  false and ``scripts/dictionary_candidates.py`` writes it only to a git-ignored file.

Usage (from the repo root)::

    python scripts/dictionary_vocab_fetch.py --fetch      # fetch what the cache lacks, write the run record
    python scripts/dictionary_vocab_fetch.py              # read the cache only (offline), rewrite the run record
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

RAW_DIR = ROOT / "data" / "raw" / "dictionary_vocabularies"
RECORD = RAW_DIR / "fetch_record.json"
RUN_FILE = ROOT / "outputs" / "dictionary_vocabularies_run.json"
UA = {"User-Agent": "ri-station-harmonization/0.1 (MSc thesis pilot; contact via GitHub)"}
TIMEOUT = 180
PAUSE_SECONDS = 0.3

ELTER_SKOSMOS = "https://vocabs.lter-europe.net/rest/v1"
ACTRIS_SKOSMOS = "https://vocabulary.actris.nilu.no/skosmos/rest/v1"
GH = "https://raw.githubusercontent.com"


def _scheme_url(base: str, vocab: str, scheme_uri: str) -> str:
    from urllib.parse import quote
    return f"{base}/{vocab}/data?uri={quote(scheme_uri, safe='')}&format=text/turtle"


# Each file: (key, relative path in the cache, url, role). ``role`` is "dump", "scheme" or "licence_doc".
VOCABULARIES: dict[str, dict] = {
    "actris_vocab": {
        "title": "ACTRIS Vocabulary", "own_ri": "ACTRIS", "definitions_committable_if_licence": "CC0-1.0",
        "scheme_uri": "https://vocabulary.actris.nilu.no/actris_vocab/",
        "files": [
            ("dump", "actris_vocab/ACTRIS_vocabulary.ttl", f"{GH}/ACTRIS-Data-Centre/actris-vocabulary/main/ACTRIS_vocabulary.ttl", "dump"),
            ("scheme", "actris_vocab/skosmos_scheme.ttl", _scheme_url(ACTRIS_SKOSMOS, "actris_vocab", "https://vocabulary.actris.nilu.no/actris_vocab/"), "scheme"),
        ],
    },
    "EnvThes": {
        "title": "EnvThes", "own_ri": "eLTER", "definitions_committable_if_licence": None,
        "scheme_uri": "http://vocabs.lter-europe.net/EnvThes/",
        "files": [
            ("dump", "EnvThes/EnvThes.ttl", f"{GH}/LTER-Europe/EnvThes/main/EnvThes.ttl", "dump"),
            ("scheme", "EnvThes/skosmos_scheme.ttl", _scheme_url(ELTER_SKOSMOS, "EnvThes", "http://vocabs.lter-europe.net/EnvThes/"), "scheme"),
            ("readme", "EnvThes/README.md", f"{GH}/LTER-Europe/EnvThes/main/README.md", "licence_doc"),
            ("license_file", "EnvThes/LICENSE", f"{GH}/LTER-Europe/EnvThes/main/LICENSE", "licence_doc"),
        ],
    },
    "so": {
        "title": "Standard observations (eLTER Standard Observations)", "own_ri": "eLTER", "definitions_committable_if_licence": None,
        "scheme_uri": "http://vocabs.lter-europe.net/so/",
        "files": [
            ("dump", "so/standard-observations.ttl", f"{GH}/LTER-Europe/SO/main/standard-observations.ttl", "dump"),
            ("scheme", "so/skosmos_scheme.ttl", _scheme_url(ELTER_SKOSMOS, "so", "http://vocabs.lter-europe.net/so/"), "scheme"),
            ("readme", "so/README.md", f"{GH}/LTER-Europe/SO/main/README.md", "licence_doc"),
            ("license_file", "so/LICENSE", f"{GH}/LTER-Europe/SO/main/LICENSE", "licence_doc"),
        ],
    },
    "elter_cl": {
        "title": "eLTER_CL (eLTER Controlled Lists)", "own_ri": "eLTER", "definitions_committable_if_licence": None,
        "scheme_uri": "http://vocabs.lter-europe.net/elter_cl",
        "files": [
            ("dump", "elter_cl/elter_cl.ttl", f"{GH}/LTER-Europe/eLTER_CL/main/elter_cl.ttl", "dump"),
            ("scheme", "elter_cl/skosmos_scheme.ttl", _scheme_url(ELTER_SKOSMOS, "elter_cl", "http://vocabs.lter-europe.net/elter_cl"), "scheme"),
            ("readme", "elter_cl/README.md", f"{GH}/LTER-Europe/eLTER_CL/main/README.md", "licence_doc"),
            ("license_file", "elter_cl/LICENSE", f"{GH}/LTER-Europe/eLTER_CL/main/LICENSE", "licence_doc"),
        ],
    },
}

LICENSE_PREDICATES = {
    "http://purl.org/dc/terms/license", "http://purl.org/dc/elements/1.1/license",
    "http://purl.org/dc/terms/rights", "http://purl.org/dc/elements/1.1/rights",
    "http://schema.org/license", "https://schema.org/license",
}
VERSION_PREDICATES = {"http://www.w3.org/2002/07/owl#versionInfo", "http://purl.org/pav/version"}
DATE_PREDICATES = {"http://purl.org/dc/terms/modified", "http://purl.org/dc/elements/1.1/modified",
                   "http://purl.org/pav/lastUpdatedOn", "http://purl.org/dc/terms/created",
                   "http://purl.org/pav/createdOn"}
SKOS = "http://www.w3.org/2004/02/skos/core#"
OWL_DEPRECATED = "http://www.w3.org/2002/07/owl#deprecated"
DCT_REPLACED = "http://purl.org/dc/terms/isReplacedBy"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"

CONCEPT_COLUMNS = ["vocabulary", "concept_uri", "pref_label", "alt_labels", "definition", "deprecated",
                   "replaced_by", "vocabulary_version", "vocabulary_licence"]


# ---------------------------------------------------------------------------------------------
# Fetch and cache
# ---------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_record(path: Path = RECORD) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"files": {}}


def fetch_file(relpath: str, url: str, raw_dir: Path, record: dict, offline: bool, session=None) -> bytes | None:
    """Return the cached bytes (``None`` for a recorded 404); fetch and cache them first if needed."""
    target = raw_dir / relpath
    if target.exists():
        return target.read_bytes()
    if record["files"].get(relpath, {}).get("status") == 404:
        return None
    if offline:
        raise FileNotFoundError(f"{target} is missing and --fetch was not given.")
    import requests
    get = (session or requests).get
    response = get(url, headers=UA, timeout=TIMEOUT)
    if response.status_code != 404:
        response.raise_for_status()
    else:
        print(f"  404 {url}")
    record["files"][relpath] = {"url": url, "final_url": response.url, "status": response.status_code,
                                "sha256": _sha256(response.content), "bytes": len(response.content),
                                "retrieved_at": _now()}
    if response.status_code == 404:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    time.sleep(PAUSE_SECONDS)
    return response.content


# ---------------------------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------------------------

def parse_turtle(data: bytes):
    from rdflib import Graph
    graph = Graph()
    graph.parse(data=data, format="turtle")
    return graph


def _en(literal) -> bool:
    lang = getattr(literal, "language", None)
    return lang is None or lang.lower() == "en" or lang.lower().startswith("en-")


def scheme_statements(graph, file_label: str) -> dict:
    """Licence, version and date statements found on any node of ``graph`` that is a scheme or ontology."""
    from rdflib import RDF, URIRef
    scheme_nodes = set(graph.subjects(RDF.type, URIRef(SKOS + "ConceptScheme"))) | set(
        graph.subjects(RDF.type, URIRef("http://www.w3.org/2002/07/owl#Ontology")))
    out: dict[str, list] = {"licence": [], "version": [], "dates": []}
    for subject in sorted(scheme_nodes, key=str):
        for _, p, o in graph.triples((subject, None, None)):
            entry = {"file": file_label, "subject": str(subject), "predicate": str(p), "object": str(o)}
            if str(p) in LICENSE_PREDICATES:
                out["licence"].append(entry)
            elif str(p) in VERSION_PREDICATES:
                out["version"].append(entry)
            elif str(p) in DATE_PREDICATES:
                out["dates"].append(entry)
    return out


def concept_table(graph, vocabulary: str, version: str, licence: str) -> pd.DataFrame:
    """One row per ``skos:Concept``: English prefLabel, altLabels, definition, deprecation flags."""
    from rdflib import RDF, URIRef
    pref, alt, definition = URIRef(SKOS + "prefLabel"), URIRef(SKOS + "altLabel"), URIRef(SKOS + "definition")
    rows = []
    for concept in sorted(set(graph.subjects(RDF.type, URIRef(SKOS + "Concept"))), key=str):
        prefs = sorted(str(o) for o in graph.objects(concept, pref) if _en(o))
        alts = sorted(str(o) for o in graph.objects(concept, alt) if _en(o))
        defs = sorted(str(o) for o in graph.objects(concept, definition) if _en(o))
        deprecated = any(str(o).strip().lower() == "true" for o in graph.objects(concept, URIRef(OWL_DEPRECATED)))
        replaced = sorted(str(o) for o in graph.objects(concept, URIRef(DCT_REPLACED)))
        rows.append({"vocabulary": vocabulary, "concept_uri": str(concept), "pref_label": prefs[0] if prefs else "",
                     "alt_labels": " | ".join(alts), "definition": defs[0] if defs else "",
                     "deprecated": deprecated, "replaced_by": " | ".join(replaced),
                     "vocabulary_version": version, "vocabulary_licence": licence})
    return pd.DataFrame(rows, columns=CONCEPT_COLUMNS)


def definition_source_tags(concepts: pd.DataFrame) -> dict[str, int]:
    """Count the bracketed source tag a definition starts with (EnvThes: ``[GEMET]``, ``[Henderson's]``, ...).

    A tag marks text taken over from another work, which the vocabulary's own licence statement may not cover.
    """
    tags: dict[str, int] = {}
    for text in concepts["definition"]:
        match = re.match(r"\[[^\]]+\]", text) if text else None
        key = match.group(0) if match else ("(no tag)" if text else "(no definition)")
        tags[key] = tags.get(key, 0) + 1
    return dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])))


def _first(statements: list[dict]) -> str:
    return statements[0]["object"] if statements else ""


def licence_lines(text: str) -> list[str]:
    """Lines of a README that mention a licence, verbatim and stripped (short; no definitions here)."""
    return [ln.strip() for ln in text.splitlines()
            if re.search(r"licen[sc]e|CC BY|CC0|creative commons", ln, re.I)][:12]


def analyse_vocabulary(name: str, spec: dict, raw_dir: Path, record: dict, offline: bool, session=None) -> tuple[dict, pd.DataFrame]:
    files: dict[str, dict] = {}
    blobs: dict[str, bytes | None] = {}
    for key, relpath, url, role in spec["files"]:
        blobs[key] = fetch_file(relpath, url, raw_dir, record, offline, session)
        info = record["files"].get(relpath, {})
        files[key] = {"path": f"data/raw/dictionary_vocabularies/{relpath}", "url": url, "role": role,
                      "status": info.get("status", 200 if blobs[key] is not None else 404),
                      "sha256": _sha256(blobs[key]) if blobs[key] is not None else None,
                      "bytes": len(blobs[key]) if blobs[key] is not None else 0,
                      "retrieved_at": info.get("retrieved_at")}
    statements = {"licence": [], "version": [], "dates": []}
    graphs = {}
    for key in ("dump", "scheme"):
        if blobs.get(key) is not None:
            graphs[key] = parse_turtle(blobs[key])
            found = scheme_statements(graphs[key], key)
            for k in statements:
                statements[k].extend(found[k])
    doc_lines = {key: licence_lines(blob.decode("utf-8", errors="replace"))
                 for key, blob in blobs.items() if spec_role(spec, key) == "licence_doc" and blob is not None}
    for key in ("readme", "license_file"):
        if key in blobs and blobs[key] is None:
            doc_lines[key] = "404: not published at the expected path"
    if "license_file" in blobs and blobs["license_file"] is not None:
        doc_lines["license_file"] = [ln.strip() for ln in blobs["license_file"].decode("utf-8", errors="replace").splitlines() if ln.strip()][:3]
    licence = _first([s for s in statements["licence"] if s["file"] == "dump"] or statements["licence"])
    version = _first([s for s in statements["version"] if s["file"] == "dump"] or statements["version"])
    concepts = concept_table(graphs["dump"], name, version, licence) if "dump" in graphs else pd.DataFrame(columns=CONCEPT_COLUMNS)
    licences_seen = sorted({s["object"] for s in statements["licence"]})
    committable_if = spec["definitions_committable_if_licence"]
    facts = {
        "title": spec["title"], "scheme_uri": spec["scheme_uri"], "files": files,
        "licence_statements": statements["licence"], "version_statements": statements["version"],
        "date_statements": statements["dates"], "licence_documents_lines": doc_lines,
        "declared_licences": licences_seen, "version": version,
        "concepts": int(len(concepts)), "concepts_deprecated": int(concepts["deprecated"].sum()),
        "concepts_with_definition": int((concepts["definition"] != "").sum()),
        "definition_source_tags": definition_source_tags(concepts),
        "definition_text_committable": bool(committable_if and licences_seen == [CC0]),
        "definition_text_rule": (
            "committable: the source declares CC0 1.0 (dc:license) in its data and in Skosmos; version and licence "
            "go on every row" if committable_if and licences_seen == [CC0] else
            "NOT committable until the project owner accepts the declared licence (see licence_statements and "
            "licence_documents_lines for what the source says): definition text goes only to git-ignored files"),
    }
    return facts, concepts


def spec_role(spec: dict, key: str) -> str:
    return next(role for k, _, _, role in spec["files"] if k == key)


def load_all_concepts(raw_dir: Path = RAW_DIR, record_path: Path = RECORD) -> pd.DataFrame:
    """All concepts of all four vocabularies from the cached dumps (cache only, no network)."""
    record = read_record(record_path)
    frames = [analyse_vocabulary(n, s, raw_dir, record, offline=True)[1] for n, s in VOCABULARIES.items()]
    return pd.concat(frames, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and cache the reference vocabularies verbatim.")
    parser.add_argument("--fetch", action="store_true", help="fetch what the cache lacks")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--run-file", type=Path, default=RUN_FILE)
    args = parser.parse_args(argv)
    raw_dir = args.raw_dir
    record_path = raw_dir / "fetch_record.json"
    raw_dir.mkdir(parents=True, exist_ok=True)
    record = read_record(record_path)
    run = {"generated_at": _now(), "script": "scripts/dictionary_vocab_fetch.py",
           "note": "no definition text in this file; raw responses are in data/raw/dictionary_vocabularies/ (not committed)",
           "vocabularies": {}}
    for name, spec in VOCABULARIES.items():
        print(f"{name} ...")
        facts, concepts = analyse_vocabulary(name, spec, raw_dir, record, offline=not args.fetch)
        run["vocabularies"][name] = facts
        print(f"  version {facts['version']!r}, licence(s) {facts['declared_licences']}, {facts['concepts']} concepts "
              f"({facts['concepts_deprecated']} deprecated, {facts['concepts_with_definition']} with definition)")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.run_file.parent.mkdir(parents=True, exist_ok=True)
    args.run_file.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.run_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
