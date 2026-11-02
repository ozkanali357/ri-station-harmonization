"""Fetch the published definitions (``rdfs:comment``) of the ICOS station-record fields.

The ICOS "fields" compared in ``scripts/compare_fields.py`` are the predicates of one example
station resource (``AS_ARN``), shortened to the part of the predicate URI after the last ``/``.
This script asks the ICOS Carbon Portal SPARQL endpoint for

1. the distinct predicates of that station resource (``props`` query), and
2. every ``rdfs:comment`` (and ``rdfs:label``, kept for reference only) the portal publishes for
   those predicate URIs (``defs`` query).

A predicate with no ``rdfs:comment`` stays flagged (``flagged = yes``, empty definition). Nothing is
filled in from other sources or from general knowledge: ``rdfs:label`` is not a definition.

Raw responses are cached byte for byte in ``outputs/field_definitions_raw/`` with SHA-256, HTTP
status, query and retrieval time in ``manifest.json`` there. Unlike the station and site caches in
``data/raw/``, these responses hold only ontology predicate URIs and ontology comments (no station
values, names or contacts), so they are committed and ``--offline`` works from a clean checkout.

Writes ``outputs/icos_field_definitions.csv`` and ``outputs/icos_field_definitions_run.json``.

Usage (from the repo root)::

    python scripts/icos_field_definitions.py            # use the cache, fetch what is missing
    python scripts/icos_field_definitions.py --offline  # cache only, never touch the network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ICOS_SPARQL = "https://meta.icos-cp.eu/sparql"
EXAMPLE_STATION = "http://meta.icos-cp.eu/resources/stations/AS_ARN"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
COMMENT_SEPARATOR = " || "
DEFINITION_SOURCE = "rdfs:comment published at https://meta.icos-cp.eu/sparql"
FLAG_TEXT = "FLAGGED: No published API definition found"

PROPS_QUERY = f"SELECT DISTINCT ?p WHERE {{ <{EXAMPLE_STATION}> ?p ?o }} ORDER BY ?p"

CACHE_DIR = ROOT / "outputs" / "field_definitions_raw"
OUT_CSV = ROOT / "outputs" / "icos_field_definitions.csv"
OUT_RUN = ROOT / "outputs" / "icos_field_definitions_run.json"


def defs_query(predicate_uris: list[str]) -> str:
    values = " ".join(f"<{uri}>" for uri in sorted(predicate_uris))
    return (
        f"SELECT ?p ?label ?comment WHERE {{ VALUES ?p {{ {values} }} "
        f"OPTIONAL {{ ?p <{RDFS_LABEL}> ?label }} "
        f"OPTIONAL {{ ?p <{RDFS_COMMENT}> ?comment }} }} ORDER BY ?p ?label ?comment"
    )


def local_name(uri: str) -> str:
    """The field name used in ``final_field_comparison.csv``: the text after the last ``/``."""
    return uri.split("/")[-1]


def parse_predicates(payload: dict) -> list[str]:
    return sorted({b["p"]["value"] for b in payload.get("results", {}).get("bindings", []) if "p" in b})


def parse_definitions(payload: dict) -> dict[str, dict[str, list[str]]]:
    """Map predicate URI to its distinct labels and comments, in the order the endpoint sorted them."""
    out: dict[str, dict[str, list[str]]] = {}
    for b in payload.get("results", {}).get("bindings", []):
        entry = out.setdefault(b["p"]["value"], {"labels": [], "comments": []})
        for key, bucket in (("label", "labels"), ("comment", "comments")):
            value = b.get(key, {}).get("value")
            if value is not None and value.strip() and value not in entry[bucket]:
                entry[bucket].append(value)
    return out


def build_rows(predicate_uris: list[str], definitions: dict[str, dict[str, list[str]]]) -> list[dict]:
    rows = []
    for uri in sorted(predicate_uris, key=lambda u: (local_name(u), u)):
        info = definitions.get(uri, {"labels": [], "comments": []})
        comments = info["comments"]
        rows.append({
            "ri": "ICOS",
            "field": local_name(uri),
            "predicate_uri": uri,
            "definition": COMMENT_SEPARATOR.join(comments),
            "n_comments": len(comments),
            "label_published": COMMENT_SEPARATOR.join(info["labels"]),
            "definition_source": DEFINITION_SOURCE if comments else "",
            "flagged": "no" if comments else "yes",
        })
    return rows


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cached_query(cache_dir: Path, name: str, query: str, offline: bool) -> tuple[dict, dict]:
    """Return ``(parsed payload, manifest entry)``; the cached bytes are never rewritten."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"responses": {}}
    path = cache_dir / name
    entry = manifest["responses"].get(name)
    if path.exists() and entry:
        raw = path.read_bytes()
        if _sha256_bytes(raw) != entry["sha256"]:
            raise RuntimeError(f"{path} does not match the checksum in {manifest_path}")
        return json.loads(raw.decode("utf-8")), entry
    if offline:
        raise FileNotFoundError(f"{path} is not cached and --offline was requested.")

    import requests  # imported here so the offline path and the tests need no network stack

    response = requests.post(
        ICOS_SPARQL, data={"query": query},
        headers={"Accept": "application/sparql-results+json",
                 "User-Agent": "ri-station-harmonization field-definitions (thesis research)"},
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    path.write_bytes(raw)
    entry = {
        "file": name, "endpoint": ICOS_SPARQL, "method": "POST", "retrieved_at": _now(),
        "http_status": response.status_code, "bytes": len(raw), "sha256": _sha256_bytes(raw), "query": query,
    }
    manifest["responses"][name] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(raw.decode("utf-8")), entry


def run(cache_dir: Path = CACHE_DIR, out_csv: Path = OUT_CSV, out_run: Path = OUT_RUN, offline: bool = False) -> pd.DataFrame:
    props_payload, props_entry = cached_query(cache_dir, "icos_station_predicates.json", PROPS_QUERY, offline)
    predicates = parse_predicates(props_payload)
    if not predicates:
        raise RuntimeError(f"The ICOS endpoint returned no predicates for {EXAMPLE_STATION}.")
    defs_payload, defs_entry = cached_query(cache_dir, "icos_predicate_definitions.json", defs_query(predicates), offline)
    rows = build_rows(predicates, parse_definitions(defs_payload))
    df = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    run_info = {
        "script": "scripts/icos_field_definitions.py",
        "git_head_at_run": _git_head(),
        "endpoint": ICOS_SPARQL,
        "example_station": EXAMPLE_STATION,
        "definition_property": RDFS_COMMENT,
        "responses": [props_entry, defs_entry],
        "n_fields": int(len(df)),
        "n_with_definition": int((df["flagged"] == "no").sum()),
        "n_flagged": int((df["flagged"] == "yes").sum()),
        "fields_with_several_distinct_comments": df.loc[df["n_comments"] > 1, "field"].tolist(),
        "output_sha256": _sha256_bytes(out_csv.read_bytes()),
        "note": ("Flagged fields have no rdfs:comment at the ICOS endpoint; rdfs:label is stored in "
                 "label_published for reference and is not used as a definition."),
    }
    out_run.write_text(json.dumps(run_info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--offline", action="store_true", help="use the cache only")
    args = parser.parse_args(argv)
    df = run(offline=args.offline)
    print(f"{len(df)} ICOS fields: {(df['flagged'] == 'no').sum()} with an rdfs:comment, "
          f"{(df['flagged'] == 'yes').sum()} flagged. Wrote {OUT_CSV.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
