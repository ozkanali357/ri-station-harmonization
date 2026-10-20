"""Variable-term table for the Finnish records (Step 3, dictionary: terms first).

Scope: harmonised records whose ``country`` is ``FI`` (the rule chosen 2026-10-19; see
``ri_harmonize.deims_detail``): ICOS stations, ACTRIS facilities and the DEIMS sites whose title
ends in `` - Finland``. One row per distinct published term and RI, listing the Finnish records
that use it. No term is mapped to a term of another RI, and nothing is labelled by hand.

Where each RI publishes variable/parameter terms (found by calling the live endpoints, 2026-10-20):

* ICOS: ``dcat:theme`` on a station resource points to a variable concept
  (``http://meta.icos-cp.eu/resources/dcat/var/<code>``) with ``skos:prefLabel``, usually an
  ``rdfs:comment``, a ``skos:altLabel`` that holds a regular expression over column names and, for
  a few, a ``skos:closeMatch`` to the NERC P07 vocabulary. One SPARQL query returns all of it.
* ACTRIS: ``POST https://prod-actris-md.nilu.no/api/metadata/search`` (plain Elasticsearch queries).
  A dataset record has ``variables[]`` with ``variable_name``, ``variable_property_of_interest``,
  ``object_of_interest``, ``variable_matrix`` and more. The complete term inventory per facility
  comes from one terms aggregation (exact dataset counts). The descriptive fields come from up to
  ``EXAMPLES_PER_TERM`` example datasets per term, because the API's ``_source`` filter fails with
  HTTP 500 and the ``fields`` output cannot be aligned per variable. Dataset records also carry
  person names; only the fields listed above are read.
* DEIMS-SDR: the detail record's ``attributes.focusDesignScale.observedProperties[]`` (label and
  EnvThes URI). Nothing from ``attributes.contact`` is read.

No domain (meteorology, soil, ...) is published per term by any of the three, so
``domain_published`` is empty. ``scope_candidate`` is a pre-filter from the keyword rules in
``SCOPE_RULES`` below, there for a human to review; it is not a classification.

Raw responses go to ``data/raw/dictionary/`` (ignored by Git) with SHA-256 and retrieval time in
``data/raw/manifest.json``.

Usage (from the repo root)::

    python scripts/dictionary_terms.py              # cached responses only
    python scripts/dictionary_terms.py --fetch      # fetch what the cache lacks
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ri_harmonize import deims_detail  # noqa: E402
from ri_harmonize.cli import RAW, load_stations  # noqa: E402
from ri_harmonize.sources import ICOS_SPARQL, TIMEOUT, UA, _now, _read_manifest, _write_manifest  # noqa: E402

OUT = ROOT / "outputs"
DICT_DIR = "dictionary"
ACTRIS_SEARCH = "https://prod-actris-md.nilu.no/api/metadata/search"
ICOS_VAR_PREFIX = "http://meta.icos-cp.eu/resources/dcat/var/"
ICOS_VOCAB = "http://meta.icos-cp.eu/resources/dcat/var/ (ICOS Carbon Portal variable concepts)"
ENVTHES = "http://vocabs.lter-europe.net/EnvThes"
EXAMPLES_PER_TERM = 5
PAUSE_SECONDS = 0.25
ICOS_LIMIT = 50_000

COLUMNS = [
    "ri", "term_label", "term_uri", "id_scheme", "definition", "alt_label", "published_attributes",
    "published_match_uri", "uri_label_variants", "field_path", "vocabulary", "source_url",
    "domain_published", "scope_candidate", "scope_rule", "n_finnish_records", "finnish_record_ids",
    "finnish_record_names", "n_datasets", "fetched_at",
]

# Keyword pre-filter, applied to the published label only. A match is a candidate for review,
# nothing more; labels the rules do not match stay empty (they are not thereby "other").
SCOPE_RULES = [
    ("meteorology", "air temperature/pressure/humidity/velocity", r"\bair (temperature|pressure|humidity|velocity|specific humidity)\b"),
    ("meteorology", "atmospheric pressure", r"\batmospheric pressure\b"),
    ("meteorology", "humidity, dew/frost point, vapour pressure", r"relative humidity|\bdew point\b|\bfrost point\b|vapou?r pressure|water vapou?r"),
    ("meteorology", "wind", r"\bwind\b"),
    ("meteorology", "precipitation amount/intensity/flux", r"precipitation (\(total\)|\(snow\)|intensity|accumulated)|mean annual precipitation|\brainfall\b"),
    ("meteorology", "radiation, irradiance, sunshine, photon flux", r"radiation|irradiance|solar light|sunshine|daylight|photon flux density"),
    ("meteorology", "max/min/mean (annual) temperature", r"\b(maximum|minimum|mean annual|mean) (air )?temperature\b"),
    ("soil", "soil", r"\bsoil\b"),
]


# ---------------------------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------------------------

def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cache_dir(raw_dir: Path) -> Path:
    path = Path(raw_dir) / DICT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cached_bytes(raw_dir: Path, filename: str, fetch, offline: bool) -> tuple[bytes, bool]:
    """(bytes, fetched_now): the cached file when present, else ``fetch()`` written byte-for-byte."""
    path = _cache_dir(raw_dir) / filename
    if path.exists():
        return path.read_bytes(), False
    if offline:
        raise FileNotFoundError(f"{path} is missing and --offline was requested.")
    raw = fetch()
    path.write_bytes(raw)
    return raw, True


def _page(manifest_pages: dict, filename: str) -> dict:
    return manifest_pages.get(filename, {})


# ---------------------------------------------------------------------------------------------
# ICOS
# ---------------------------------------------------------------------------------------------

ICOS_THEME_QUERY = """
prefix cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
prefix dcat: <http://www.w3.org/ns/dcat#>
prefix skos: <http://www.w3.org/2004/02/skos/core#>
prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
select ?station ?stationId ?theme ?label ?comment ?altLabel ?closeMatch
where {{
  ?station cpmeta:hasStationId ?stationId ; cpmeta:countryCode "FI" ; dcat:theme ?theme .
  optional {{ ?theme skos:prefLabel ?label }}
  optional {{ ?theme rdfs:comment ?comment }}
  optional {{ ?theme skos:altLabel ?altLabel }}
  optional {{ ?theme skos:closeMatch ?closeMatch }}
}}
order by str(?station) str(?theme)
limit {limit}
"""
ICOS_CACHE_FILE = "icos_station_variable_themes_FI.json"


def fetch_icos_themes(raw_dir: Path, offline: bool = False) -> dict:
    """One SPARQL response: every ``dcat:theme`` of a Finnish ICOS station with its concept facts."""
    query = ICOS_THEME_QUERY.format(limit=ICOS_LIMIT)

    def fetch() -> bytes:
        response = requests.post(ICOS_SPARQL, data={"query": query},
                                 headers={"Accept": "application/sparql-results+json", **UA}, timeout=TIMEOUT)
        response.raise_for_status()
        return response.content

    raw, fetched = _cached_bytes(raw_dir, ICOS_CACHE_FILE, fetch, offline)
    if fetched:
        _write_manifest(raw_dir, "dictionary_icos", {
            "endpoint": ICOS_SPARQL, "retrieved_at": _now(), "complete": True, "query": query,
            "checksum_of": "raw response bytes",
            "pages": [{"file": f"{DICT_DIR}/{ICOS_CACHE_FILE}", "sha256": _sha256_bytes(raw), "bytes": len(raw)}],
        })
    payload = json.loads(raw)
    if len(payload["results"]["bindings"]) >= ICOS_LIMIT:
        raise RuntimeError("ICOS theme query hit its LIMIT; the cached response is incomplete")
    return payload


def icos_terms(payload: dict, finnish_ids: set[str]) -> tuple[list[dict], dict]:
    """Term records from the SPARQL response, restricted to the harmonised Finnish stations."""
    concepts: dict[str, dict] = {}
    users: dict[str, set] = defaultdict(set)
    stations_seen, other_themes = set(), set()
    for b in payload["results"]["bindings"]:
        get = lambda key: b.get(key, {}).get("value")  # noqa: E731
        station, theme = get("station"), get("theme")
        stations_seen.add(station)
        if station not in finnish_ids:
            continue
        if not theme.startswith(ICOS_VAR_PREFIX):
            other_themes.add(theme)
            continue
        users[theme].add(station)
        c = concepts.setdefault(theme, {"label": set(), "comment": set(), "alt": set(), "close": set()})
        for key, field in (("label", "label"), ("comment", "comment"), ("alt", "altLabel"), ("close", "closeMatch")):
            if get(field):
                c[key].add(get(field))
    records = []
    for theme, c in sorted(concepts.items()):
        records.append({
            "ri": "ICOS", "term_label": "; ".join(sorted(c["label"])), "term_uri": theme,
            "id_scheme": "ICOS variable concept URI", "definition": "; ".join(sorted(c["comment"])),
            "alt_label": "; ".join(sorted(c["alt"])), "published_attributes": "",
            "published_match_uri": "; ".join(sorted(c["close"])),
            "field_path": "station dcat:theme -> skos:prefLabel / rdfs:comment / skos:altLabel / skos:closeMatch",
            "vocabulary": ICOS_VOCAB, "source_url": ICOS_SPARQL, "record_ids": sorted(users[theme]), "n_datasets": None,
        })
    label_uses = defaultdict(set)
    for theme, c in concepts.items():
        for label in c["label"]:
            label_uses[label].add(theme)
    coverage = {"stations_in_response": len(stations_seen),
                "labels_shared_by_several_concepts": {k: len(v) for k, v in sorted(label_uses.items()) if len(v) > 1},
                "stations_with_terms_in_scope": len({s for u in users.values() for s in u}),
                "non_variable_themes_skipped": sorted(other_themes)}
    return records, coverage


# ---------------------------------------------------------------------------------------------
# ACTRIS
# ---------------------------------------------------------------------------------------------

ACTRIS_COUNTS_FILE = "actris_variable_counts_FI.json"
ACTRIS_EXAMPLE_DIR = "actris_examples"


def _search(search: dict) -> bytes:
    response = requests.post(ACTRIS_SEARCH, json={"search": search}, headers=UA, timeout=300)
    response.raise_for_status()
    return response.content


def _counts_query(facility_ids: list[str]) -> dict:
    return {"size": 0, "track_total_hits": True,
            "query": {"terms": {"facility.identifier.keyword": facility_ids}},
            "aggs": {"fac": {"terms": {"field": "facility.identifier.keyword", "size": 1000},
                             "aggs": {"vn": {"terms": {"field": "variables.variable_name.keyword", "size": 10000}}}}}}


def _example_query(facility_ids: list[str], name: str) -> dict:
    return {"size": EXAMPLES_PER_TERM, "track_total_hits": True,
            "query": {"bool": {"must": [{"terms": {"facility.identifier.keyword": facility_ids}},
                                        {"term": {"variables.variable_name.keyword": name}}]}},
            "sort": [{"identification.identifier.pid.keyword": {"order": "asc"}}]}


def fetch_actris_counts(raw_dir: Path, facility_ids: list[str], offline: bool = False) -> dict:
    """Terms aggregation: for each Finnish facility, every ``variable_name`` with its dataset count."""
    search = _counts_query(sorted(facility_ids))
    raw, fetched = _cached_bytes(raw_dir, ACTRIS_COUNTS_FILE, lambda: _search(search), offline)
    if fetched:
        _write_manifest(raw_dir, "dictionary_actris_counts", {
            "endpoint": ACTRIS_SEARCH, "retrieved_at": _now(), "complete": True, "request": search,
            "checksum_of": "raw response bytes",
            "pages": [{"file": f"{DICT_DIR}/{ACTRIS_COUNTS_FILE}", "sha256": _sha256_bytes(raw), "bytes": len(raw)}],
        })
    return json.loads(raw)["response"]


def actris_term_counts(response: dict) -> dict[str, dict[str, int]]:
    """``{variable_name: {facility_id: n_datasets}}``; fails if the aggregation was truncated."""
    aggs = response["aggregations"]
    fac = next(v for k, v in aggs.items() if k.endswith("#fac"))
    if fac.get("sum_other_doc_count"):
        raise RuntimeError("ACTRIS facility aggregation was truncated")
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for bucket in fac["buckets"]:
        vn = next(v for k, v in bucket.items() if k.endswith("#vn"))
        if vn.get("sum_other_doc_count"):
            raise RuntimeError(f"ACTRIS variable aggregation was truncated for facility {bucket['key']}")
        for term in vn["buckets"]:
            out[term["key"]][bucket["key"]] = term["doc_count"]
    return dict(out)


def _example_file(name: str) -> str:
    return f"{ACTRIS_EXAMPLE_DIR}/{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}.json"


def fetch_actris_examples(raw_dir: Path, facility_ids: list[str], names: list[str], offline: bool = False) -> dict[str, dict]:
    """``{variable_name: response}``: up to ``EXAMPLES_PER_TERM`` datasets per term, one cached file each."""
    (_cache_dir(raw_dir) / ACTRIS_EXAMPLE_DIR).mkdir(parents=True, exist_ok=True)
    prev = _read_manifest(raw_dir).get("sources", {}).get("dictionary_actris_examples", {})
    pages = {p["term"]: p for p in prev.get("pages", [])}
    out, fetched_any = {}, False
    for name in sorted(names):
        filename = _example_file(name)
        if (_cache_dir(raw_dir) / filename).exists():
            raw = (_cache_dir(raw_dir) / filename).read_bytes()
        elif offline:
            raise FileNotFoundError(f"{_cache_dir(raw_dir) / filename} is missing and --offline was requested.")
        else:
            if fetched_any:
                time.sleep(PAUSE_SECONDS)
            raw = _search(_example_query(sorted(facility_ids), name))
            (_cache_dir(raw_dir) / filename).write_bytes(raw)
            fetched_any = True
            pages[name] = {"term": name, "file": f"{DICT_DIR}/{filename}", "sha256": _sha256_bytes(raw),
                           "bytes": len(raw), "retrieved_at": _now()}
        out[name] = json.loads(raw)["response"]
    if fetched_any:
        _write_manifest(raw_dir, "dictionary_actris_examples", {
            "endpoint": ACTRIS_SEARCH, "retrieved_at": _now(), "complete": True,
            "examples_per_term": EXAMPLES_PER_TERM, "checksum_of": "raw response bytes",
            "request_template": _example_query(["<finnish facility ids>"], "<variable_name>"),
            "pages": sorted(pages.values(), key=lambda p: p["term"]),
        })
    return out


ACTRIS_ATTRIBUTES = ["variable_property_of_interest", "object_of_interest", "variable_matrix",
                     "variable_statistical_property", "variable_geometry", "temporal_resolution"]


def actris_attributes(name: str, response: dict) -> tuple[list[dict], int, list[str]]:
    """Distinct descriptive-field combinations of the variables called ``name`` in the example
    datasets, the total dataset count the example query reported, and the repositories seen."""
    combos, repos = [], set()
    for hit in response["hits"]["hits"]:
        source = hit["_source"]
        repos.add(((source.get("dataset_metadata") or {}).get("repository") or {}).get("repository_id"))
        for variable in source.get("variables") or []:
            if variable.get("variable_name") != name:
                continue
            combo = {k.replace("variable_", "", 1) if k.startswith("variable_") else k: variable[k]
                     for k in ACTRIS_ATTRIBUTES if variable.get(k)}
            if combo not in combos:
                combos.append(combo)
    total = response["hits"]["total"]["value"]
    return combos, total, sorted(r for r in repos if r)


def actris_terms(counts: dict[str, dict[str, int]], examples: dict[str, dict]) -> tuple[list[dict], dict]:
    records, mismatches, multi = [], [], []
    for name in sorted(counts):
        by_fac = counts[name]
        combos, total, repos = actris_attributes(name, examples[name])
        n_datasets = sum(by_fac.values())
        if total != n_datasets:
            mismatches.append({"term": name, "aggregation": n_datasets, "example_query": total})
        if len({json.dumps({k: v for k, v in c.items() if k != "temporal_resolution"}, sort_keys=True) for c in combos}) > 1:
            multi.append(name)       # differ in more than the temporal resolution
        records.append({
            "ri": "ACTRIS", "term_label": name, "term_uri": "", "id_scheme": "", "definition": "",
            "alt_label": "", "published_attributes": json.dumps(combos, ensure_ascii=False, sort_keys=True),
            "published_match_uri": "", "field_path": "dataset record variables[].variable_name",
            "vocabulary": "", "source_url": ACTRIS_SEARCH, "record_ids": sorted(by_fac), "n_datasets": n_datasets,
            "_repositories": repos,
        })
    return records, {"terms": len(records), "count_mismatches": mismatches, "terms_with_several_attribute_sets": multi}


# ---------------------------------------------------------------------------------------------
# DEIMS-SDR
# ---------------------------------------------------------------------------------------------

def deims_observed_properties(payload: dict) -> list[dict]:
    """``[{label, uri}]`` from ``attributes.focusDesignScale.observedProperties``; nothing else is read."""
    items = ((payload.get("attributes") or {}).get("focusDesignScale") or {}).get("observedProperties") or []
    return [{"label": (i.get("label") or "").strip(), "uri": (i.get("uri") or "").strip()} for i in items if isinstance(i, dict)]


def deims_terms(details: dict[str, dict]) -> tuple[list[dict], dict]:
    users: dict[tuple, set] = defaultdict(set)
    soil_text_sites = 0
    for uuid, payload in details.items():
        for item in deims_observed_properties(payload):
            users[(item["label"], item["uri"])].add(uuid)
        if ((payload.get("attributes") or {}).get("environmentalCharacteristics") or {}).get("soils"):
            soil_text_sites += 1
    labels_by_uri: dict[str, set] = defaultdict(set)
    for label, uri in users:
        labels_by_uri[uri].add(label)
    records = []
    for (label, uri), uuids in sorted(users.items()):
        others = sorted(labels_by_uri[uri] - {label})
        records.append({
            "ri": "eLTER", "term_label": label, "term_uri": uri, "id_scheme": "EnvThes URI", "definition": "",
            "alt_label": "", "published_attributes": "", "published_match_uri": "",
            "uri_label_variants": "; ".join(others), "field_path": "attributes.focusDesignScale.observedProperties[]",
            "vocabulary": ENVTHES, "source_url": deims_detail.DEIMS_SITE, "record_ids": sorted(uuids), "n_datasets": None,
        })
    return records, {"sites_with_observed_properties": len({u for s in users.values() for u in s}),
                     "distinct_label_uri_pairs": len(users), "uris_with_several_labels": sum(len(v) > 1 for v in labels_by_uri.values()),
                     "sites_with_free_text_soils_field": soil_text_sites}


# ---------------------------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------------------------

def scope_candidate(label: str) -> tuple[str, str]:
    """(domain, rule name) of the first ``SCOPE_RULES`` entry matching the label, else ("", "")."""
    for domain, rule, pattern in SCOPE_RULES:
        if re.search(pattern, label, re.IGNORECASE):
            return domain, rule
    return "", ""


def build_table(records: list[dict], names: dict[tuple, str], fetched_at: dict[str, str]) -> pd.DataFrame:
    """Final rows. ``names`` maps ``(ri, record_id)`` to the record's display name."""
    rows = []
    for r in records:
        domain, rule = scope_candidate(r["term_label"])
        ids = r["record_ids"]
        rows.append({
            **{c: r.get(c, "") for c in COLUMNS},
            "domain_published": "", "scope_candidate": domain, "scope_rule": rule,
            "n_finnish_records": len(ids), "finnish_record_ids": ";".join(ids),
            "finnish_record_names": ";".join(names[(r["ri"], i)] for i in ids),
            "n_datasets": "" if r.get("n_datasets") is None else r["n_datasets"],
            "fetched_at": fetched_at[r["ri"]],
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.sort_values(["ri", "term_label", "term_uri"], kind="stable").reset_index(drop=True)


def _git_revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fetch", action="store_true", help="fetch what the cache lacks (default: cache only)")
    parser.add_argument("--out-dir", default=str(OUT))
    args = parser.parse_args()
    offline = not args.fetch
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stations = load_stations(offline, deims_detail_finland=True)
    fi = stations[stations.country == "FI"]
    by_ri = {ri: fi[fi.ri == ri] for ri in ("ICOS", "ACTRIS", "eLTER")}
    names = {(r.ri, r.record_id): r.name for r in fi.itertuples()}

    icos_payload = fetch_icos_themes(RAW, offline)
    icos_rec, icos_cov = icos_terms(icos_payload, set(by_ri["ICOS"].record_id))

    actris_ids = sorted(by_ri["ACTRIS"].record_id)
    counts_resp = fetch_actris_counts(RAW, actris_ids, offline)
    counts = actris_term_counts(counts_resp)
    examples = fetch_actris_examples(RAW, actris_ids, list(counts), offline)
    actris_rec, actris_cov = actris_terms(counts, examples)
    actris_cov["datasets_in_scope"] = counts_resp["hits"]["total"]["value"]

    details = deims_detail.fetch_details(RAW, deims_detail.finnish_site_ids(stations), offline)
    deims_rec, deims_cov = deims_terms(details)

    manifest = _read_manifest(RAW)["sources"]
    ex_pages = manifest.get("dictionary_actris_examples", {}).get("pages", [])
    fetched_at = {
        "ICOS": manifest["dictionary_icos"]["retrieved_at"],
        "ACTRIS": manifest["dictionary_actris_counts"]["retrieved_at"],
        "eLTER": max(p["retrieved_at"] for p in manifest["deims_detail"]["pages"] if p.get("retrieved_at")),
    }
    table = build_table(icos_rec + actris_rec + deims_rec, names, fetched_at)
    table.to_csv(out_dir / "dictionary_terms_finland.csv", index=False)

    with_terms = {"ICOS": {i for r in icos_rec for i in r["record_ids"]},
                  "ACTRIS": {i for r in actris_rec for i in r["record_ids"]},
                  "eLTER": {i for r in deims_rec for i in r["record_ids"]}}
    coverage = {}
    for ri, frame in by_ri.items():
        ids = set(frame.record_id)
        coverage[ri] = {"finnish_records": len(ids), "records_with_terms": len(ids & with_terms[ri]),
                        "distinct_terms": int((table.ri == ri).sum()),
                        "records_without_terms": sorted(f"{names[(ri, i)]} ({i})" for i in ids - with_terms[ri])}
    run = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "git_revision": _git_revision(),
        "scope": "harmonised records with country == FI", "coverage": coverage,
        "icos": icos_cov, "actris": actris_cov, "deims": deims_cov,
        "scope_candidate_counts": {ri: {k: int(v) for k, v in g.scope_candidate.replace("", "unmatched").value_counts().items()}
                                   for ri, g in table.groupby("ri")},
        "scope_rules": [{"domain": d, "rule": n, "pattern": p} for d, n, p in SCOPE_RULES],
        "controlled_lists": "not fetched: vocabs.lter-europe.net was denied by the container network policy on 2026-10-20",
        "sources": {k: {kk: vv for kk, vv in v.items() if kk != "pages"} | {"n_pages": len(v.get("pages", []))}
                    for k, v in manifest.items() if k.startswith("dictionary_")},
        "checksums": {k: [p["sha256"] for p in v["pages"]] for k, v in manifest.items()
                      if k in ("dictionary_icos", "dictionary_actris_counts")},
        "actris_example_pages_sha256": {p["term"]: p["sha256"] for p in ex_pages},
    }
    (out_dir / "dictionary_terms_finland_run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"coverage": coverage, "scope_candidate_counts": run["scope_candidate_counts"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
