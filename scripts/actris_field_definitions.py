"""Look for published definitions of the 16 ACTRIS facility fields.

Two sources are checked, and only these:

1. The ACTRIS metadata API's OpenAPI document (``https://prod-actris-md.nilu.no/v3/api-docs``): does the
   ``Facility`` schema give a ``description`` for the property?
2. The ACTRIS SKOSMOS vocabularies (``actris_vocab`` and ``actris_ctrl_lists`` at
   ``https://vocabulary.actris.nilu.no/skosmos/``): is there a concept whose label equals the field name
   (case-insensitive, underscores read as spaces)?

A vocabulary concept with an equal label is a *candidate*, not a definition of the API field: the concept
defines a term, the field is a property of a record. Candidates are listed in the output by label and URI
only. **No ACTRIS vocabulary text is read or written**: the licence of the vocabulary is unknown, so the
concept's ``skos:definition`` is never fetched, and the search responses that are cached hold only labels and
URIs. A field without an API description stays flagged. Nothing is filled in.

Raw responses are cached byte for byte in ``data/raw/actris_fields/`` (not committed: the OpenAPI document
holds a service e-mail address). The committed run file ``outputs/actris_field_definitions_run.json`` records URL, query, retrieval time, status, size and
SHA-256 of each response.

Writes ``outputs/actris_field_definitions.csv`` and ``outputs/actris_field_definitions_run.json``.

Usage (from the repo root)::

    python scripts/actris_field_definitions.py            # use the cache, fetch what is missing
    python scripts/actris_field_definitions.py --offline  # cache only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

OPENAPI_URL = "https://prod-actris-md.nilu.no/v3/api-docs"
SKOSMOS = "https://vocabulary.actris.nilu.no/skosmos"
VOCABULARIES = ["actris_vocab", "actris_ctrl_lists"]
FIELDS_FILE = ROOT / "outputs" / "final_field_comparison.csv"
CACHE_DIR = ROOT / "data" / "raw" / "actris_fields"
OUT_CSV = ROOT / "outputs" / "actris_field_definitions.csv"
OUT_RUN = ROOT / "outputs" / "actris_field_definitions_run.json"
USER_AGENT = "ri-station-harmonization (thesis research; public ACTRIS metadata)"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OUTPUT_COLUMNS = ["field", "api_description_present", "api_description", "vocabulary_label_match",
                  "vocabulary_concept_uri", "used_as_field_definition", "flagged"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def label_for(field: str) -> str:
    return field.replace("_", " ").lower()


def facility_property_description(openapi: dict, field: str) -> tuple[bool, str]:
    """``(is a Facility property, its description or empty)``."""
    props = openapi.get("components", {}).get("schemas", {}).get("Facility", {}).get("properties", {})
    if field not in props:
        return False, ""
    return True, str(props[field].get("description", "") or "")


def exact_label_hits(search_payload: dict, field: str) -> list[dict]:
    """Results whose preferred label equals the field name read as words."""
    want = label_for(field)
    return [r for r in search_payload.get("results", []) if str(r.get("prefLabel", "")).lower() == want]


def build_rows(fields: list[str], openapi: dict, searches: dict[tuple[str, str], dict]) -> list[dict]:
    rows = []
    for field in fields:
        is_prop, description = facility_property_description(openapi, field)
        hits = [(vocab, hit) for vocab in VOCABULARIES for hit in exact_label_hits(searches[(vocab, field)], field)]
        definition_found = bool(description.strip())
        if hits:
            for vocab, hit in hits:
                rows.append({
                    "field": field,
                    "api_description_present": "yes" if definition_found else "no",
                    "api_description": description,
                    "vocabulary_label_match": f"{vocab}: {hit['prefLabel']}",
                    "vocabulary_concept_uri": hit["uri"],
                    "used_as_field_definition": "yes" if definition_found else "no",
                    "flagged": "no" if definition_found else "yes",
                })
        else:
            rows.append({
                "field": field,
                "api_description_present": "yes" if definition_found else "no",
                "api_description": description,
                "vocabulary_label_match": "",
                "vocabulary_concept_uri": "",
                "used_as_field_definition": "yes" if definition_found else "no",
                "flagged": "no" if definition_found else "yes",
            })
        if not is_prop:
            rows[-1]["api_description"] = "(not a property of the Facility schema)"
    return rows


# --- fetching ------------------------------------------------------------------------------------

def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


class Cache:
    """Byte-for-byte cache of GET responses with a manifest entry for each."""

    def __init__(self, offline: bool, previous: dict):
        self.offline = offline
        self.previous = previous
        self.entries: dict[str, dict] = {}

    def get_json(self, name: str, url: str, params: dict | None = None) -> dict:
        path = CACHE_DIR / name
        if path.exists():
            data = path.read_bytes()
            entry = dict(self.previous.get(name, {}))
            if entry.get("sha256") not in (None, sha256_bytes(data)):
                raise SystemExit(f"{path} no longer matches its recorded SHA-256")
            entry.update({"bytes": len(data), "sha256": sha256_bytes(data)})
        elif self.offline:
            raise SystemExit(f"--offline but {path} is missing")
        else:
            import requests

            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT,
                                                                 "Accept": "application/json"}, timeout=60)
            response.raise_for_status()
            path.write_bytes(response.content)
            data = response.content
            entry = {"url": response.url, "query": params or {}, "http_status": response.status_code,
                     "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                     "bytes": len(data), "sha256": sha256_bytes(data)}
        entry["file"] = str(path.relative_to(ROOT))
        self.entries[name] = entry
        return json.loads(data.decode("utf-8"))


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Definitions of the ACTRIS facility fields.")
    parser.add_argument("--offline", action="store_true", help="use the cache only")
    args = parser.parse_args(argv)

    frame = pd.read_csv(FIELDS_FILE)
    fields = sorted(frame.loc[frame["ri"] == "ACTRIS", "field"])
    previous = {}
    if OUT_RUN.exists():
        previous = json.loads(OUT_RUN.read_text(encoding="utf-8")).get("responses", {})
    cache = Cache(args.offline, previous)

    openapi = cache.get_json("openapi.json", OPENAPI_URL)
    searches: dict[tuple[str, str], dict] = {}
    for vocab in VOCABULARIES:
        for field in fields:
            params = {"query": label_for(field), "vocab": vocab, "lang": "en"}
            searches[(vocab, field)] = cache.get_json(f"search_{vocab}_{_safe(field)}.json",
                                                      f"{SKOSMOS}/rest/v1/search", params)

    rows = build_rows(fields, openapi, searches)
    frame_out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    for column in frame_out.columns:
        if frame_out[column].astype(str).str.contains(EMAIL_RE).any():
            raise SystemExit(f"e-mail address in column {column}; nothing was written")
    frame_out.to_csv(OUT_CSV, index=False)

    facility_paths = {p: {m: v.get("summary") or v.get("description", "") for m, v in ops.items()
                          if isinstance(v, dict)}
                      for p, ops in openapi.get("paths", {}).items() if "facilit" in p.lower()}
    run = {
        "script": "scripts/actris_field_definitions.py",
        "git_head_at_run": _git_head(),
        "fields_checked": fields,
        "openapi_version": openapi.get("info", {}).get("version"),
        "fields_with_api_description": int((frame_out.drop_duplicates("field")["api_description_present"] == "yes").sum()),
        "fields_flagged": int((frame_out.drop_duplicates("field")["flagged"] == "yes").sum()),
        "fields_with_label_equal_vocabulary_concept": sorted(
            frame_out.loc[frame_out["vocabulary_label_match"] != "", "field"].unique().tolist()),
        "facility_endpoint_descriptions": facility_paths,
        "rule": ("A vocabulary concept whose label equals the field name is listed as a candidate only; it "
                 "defines a term, not the API property, and is not used as the field's definition."),
        "responses": cache.entries,
        "output": {"file": str(OUT_CSV.relative_to(ROOT)), "sha256": sha256_bytes(OUT_CSV.read_bytes())},
    }
    OUT_RUN.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print({k: run[k] for k in ("fields_with_api_description", "fields_flagged",
                               "fields_with_label_equal_vocabulary_concept")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
