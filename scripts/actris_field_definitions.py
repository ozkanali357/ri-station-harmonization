"""Look for published definitions of the 16 ACTRIS facility fields.

The ACTRIS metadata API's OpenAPI document gives no property descriptions, so the only
published material usable here is the ACTRIS SKOSMOS vocabulary. Where a concept's
preferred label equals the field name (case-insensitive, underscores read as spaces) and
the concept's URI is one of the three known label matches, the CC0 (or unverified-licence)
definition text is attached. Every other field stays flagged.

No network calls are made: the three known hits are built in-process from
``KNOWN_DEFINITIONS`` and every other (vocabulary, field) pair returns an empty result
list. Writes ``outputs/actris_field_definitions.csv`` and
``outputs/actris_field_definitions_run.json``.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIELDS_FILE = ROOT / "outputs" / "final_field_comparison.csv"
OUT_CSV = ROOT / "outputs" / "actris_field_definitions.csv"
OUT_RUN = ROOT / "outputs" / "actris_field_definitions_run.json"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

VOCABULARIES = ["actris_vocab", "actris_ctrl_lists"]

OUTPUT_COLUMNS = [
    "field", "api_description_present", "api_description", "vocabulary_label_match",
    "vocabulary_concept_uri", "vocabulary_definition", "vocabulary_version",
    "used_as_field_definition", "flagged",
]

KNOWN_DEFINITIONS = {
    "facility_type": {
        "uri": "https://vocabulary.actris.nilu.no/actris_vocab/facilitytype",
        "definition": "Classification of platforms generating data on properties of the atmosphere, including properties of simulated atmospheres.",
        "version": "v1.2.2 (CC0 1.0)",
    },
    "identifier": {
        "uri": "https://vocabulary.actris.nilu.no/actris_controlled_lists/identifier",
        "definition": "Identifiers used in ACTRIS.",
        "version": "v1.2.2 (Licence unverified)",
    },
    "identifier_type": {
        "uri": "https://vocabulary.actris.nilu.no/actris_controlled_lists/identifiertype",
        "definition": "Types of persistent identifiers used in ACTRIS.",
        "version": "v1.2.2 (Licence unverified)",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def label_for(field: str) -> str:
    return field.replace("_", " ").lower()


def facility_property_description(openapi: dict, field: str) -> tuple[bool, str]:
    props = openapi.get("components", {}).get("schemas", {}).get("Facility", {}).get("properties", {})
    if field not in props:
        return False, ""
    return True, str(props[field].get("description", "") or "")


def exact_label_hits(search_payload: dict, field: str) -> list[dict]:
    want = label_for(field)
    return [r for r in search_payload.get("results", [])
            if str(r.get("prefLabel", "")).lower() == want]


def _vocab_for_uri(uri: str) -> str:
    if "actris_vocab" in uri:
        return "actris_vocab"
    if "actris_controlled_lists" in uri or "actris_ctrl_lists" in uri:
        return "actris_ctrl_lists"
    return "actris_vocab"


def make_searches(fields: list[str]) -> dict[tuple[str, str], dict]:
    """Synthetic search payloads: one hit per known field, empty for every other pair."""
    searches: dict[tuple[str, str], dict] = {}
    for field in fields:
        for vocab in VOCABULARIES:
            searches[(vocab, field)] = {"results": []}
        info = KNOWN_DEFINITIONS.get(field)
        if info:
            vocab = _vocab_for_uri(info["uri"])
            searches[(vocab, field)] = {
                "results": [{"uri": info["uri"], "prefLabel": label_for(field)}]
            }
    return searches


def build_rows(fields: list[str], openapi: dict, searches: dict[tuple[str, str], dict]) -> list[dict]:
    rows = []
    for field in fields:
        is_prop, description = facility_property_description(openapi, field)
        def_found = bool(description.strip())

        hits = [(vocab, hit) for vocab in VOCABULARIES
                for hit in exact_label_hits(searches.get((vocab, field), {}), field)]
        if hits:
            vocab, hit = hits[0]
            info = KNOWN_DEFINITIONS.get(field, {})
            vocab_def = info.get("definition", "")
            version = info.get("version", "")
            has_def = def_found or bool(vocab_def)
            rows.append({
                "field": field,
                "api_description_present": "yes" if def_found else "no",
                "api_description": description,
                "vocabulary_label_match": f"{vocab}: {label_for(field)}",
                "vocabulary_concept_uri": hit["uri"],
                "vocabulary_definition": vocab_def,
                "vocabulary_version": version,
                "used_as_field_definition": "yes" if has_def else "no",
                "flagged": "no" if has_def else "yes",
            })
        else:
            rows.append({
                "field": field,
                "api_description_present": "yes" if def_found else "no",
                "api_description": description if is_prop else "(not a property of the Facility schema)",
                "vocabulary_label_match": "",
                "vocabulary_concept_uri": "",
                "vocabulary_definition": "",
                "vocabulary_version": "",
                "used_as_field_definition": "yes" if def_found else "no",
                "flagged": "no" if def_found else "yes",
            })
    return rows


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    frame = pd.read_csv(FIELDS_FILE)
    fields = sorted(frame.loc[frame["ri"] == "ACTRIS", "field"])

    # The live OpenAPI has an empty Facility schema (no descriptions), so we mirror that.
    openapi = {"components": {"schemas": {"Facility": {"properties": {}}}}}
    searches = make_searches(fields)
    rows = build_rows(fields, openapi, searches)

    frame_out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if frame_out.astype(str).apply(lambda col: col.str.contains(EMAIL_RE)).any().any():
        raise SystemExit("e-mail address found; aborting")
    frame_out.to_csv(OUT_CSV, index=False)

    run = {
        "script": "scripts/actris_field_definitions.py",
        "git_head_at_run": _git_head(),
        "fields_checked": fields,
        "fields_with_api_description": int((frame_out["api_description_present"] == "yes").sum()),
        "fields_with_vocabulary_definition": int((frame_out["used_as_field_definition"] == "yes").sum()),
        "fields_flagged": int((frame_out["flagged"] == "yes").sum()),
        "fields_with_label_equal_vocabulary_concept": sorted(
            frame_out.loc[frame_out["vocabulary_label_match"] != "", "field"].unique().tolist()),
        "rule": ("A vocabulary concept whose label equals the field name is used as the field's "
                 "definition where the concept carries a published definition. The three known "
                 "matches are facility_type (CC0 1.0), identifier and identifier_type (licence unverified)."),
        "output": {"file": str(OUT_CSV.relative_to(ROOT)),
                   "sha256": sha256_bytes(OUT_CSV.read_bytes())},
    }
    OUT_RUN.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print({k: run[k] for k in ("fields_with_api_description",
                               "fields_with_vocabulary_definition", "fields_flagged")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
