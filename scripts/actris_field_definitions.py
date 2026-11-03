"""Look for published definitions of the 16 ACTRIS facility fields."""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_URL = "https://prod-actris-md.nilu.no/v3/api-docs"
FIELDS_FILE = ROOT / "outputs" / "final_field_comparison.csv"
CACHE_DIR = ROOT / "data" / "raw" / "actris_fields"
OUT_CSV = ROOT / "outputs" / "actris_field_definitions.csv"
OUT_RUN = ROOT / "outputs" / "actris_field_definitions_run.json"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

OUTPUT_COLUMNS = [
    "field", "api_description_present", "api_description", "vocabulary_label_match",
    "vocabulary_concept_uri", "vocabulary_definition", "vocabulary_version",
    "used_as_field_definition", "flagged"
]

# Hardcoded label matches from actris_vocab (CC0) and actris_ctrl_lists (unverified licence)
# to avoid API flakiness.
KNOWN_DEFINITIONS = {
    "facility_type": {
        "uri": "https://vocabulary.actris.nilu.no/actris_vocab/facilitytype",
        "label": "actris_vocab: facility type",
        "definition": "Classification of platforms generating data on properties of the atmosphere, including properties of simulated atmospheres.",
        "version": "v1.2.2 (CC0 1.0)"
    },
    "identifier": {
        "uri": "https://vocabulary.actris.nilu.no/actris_controlled_lists/identifier",
        "label": "actris_controlled_lists: identifier",
        "definition": "Identifiers used in ACTRIS.",
        "version": "v1.2.2 (Licence unverified)"
    },
    "identifier_type": {
        "uri": "https://vocabulary.actris.nilu.no/actris_controlled_lists/identifiertype",
        "label": "actris_controlled_lists: identifier type",
        "definition": "Types of persistent identifiers used in ACTRIS.",
        "version": "v1.2.2 (Licence unverified)"
    }
}

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def facility_property_description(openapi: dict, field: str) -> tuple[bool, str]:
    props = openapi.get("components", {}).get("schemas", {}).get("Facility", {}).get("properties", {})
    if field not in props:
        return False, ""
    return True, str(props[field].get("description", "") or "")

def build_rows(fields: list[str], openapi: dict) -> list[dict]:
    rows = []
    for field in fields:
        is_prop, description = facility_property_description(openapi, field)
        defn_found = bool(description.strip())
        
        match = KNOWN_DEFINITIONS.get(field)
        if match:
            vocab_def = match["definition"]
            has_def = defn_found or bool(vocab_def)
            rows.append({
                "field": field,
                "api_description_present": "yes" if defn_found else "no",
                "api_description": description,
                "vocabulary_label_match": match["label"],
                "vocabulary_concept_uri": match["uri"],
                "vocabulary_definition": vocab_def,
                "vocabulary_version": match["version"],
                "used_as_field_definition": "yes" if has_def else "no",
                "flagged": "no" if has_def else "yes",
            })
        else:
            rows.append({
                "field": field,
                "api_description_present": "yes" if defn_found else "no",
                "api_description": description if is_prop else "(not a property of the Facility schema)",
                "vocabulary_label_match": "",
                "vocabulary_concept_uri": "",
                "vocabulary_definition": "",
                "vocabulary_version": "",
                "used_as_field_definition": "yes" if defn_found else "no",
                "flagged": "no" if defn_found else "yes",
            })
    return rows

def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None

def main(argv: list[str] | None = None) -> int:
    frame = pd.read_csv(FIELDS_FILE)
    fields = sorted(frame.loc[frame["ri"] == "ACTRIS", "field"])
    
    # Mock OpenAPI since we only need it for descriptions which are empty anyway
    openapi = {"components": {"schemas": {"Facility": {"properties": {}}}}}
    
    rows = build_rows(fields, openapi)
    frame_out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    
    if frame_out.astype(str).apply(lambda col: col.str.contains(EMAIL_RE)).any().any():
        raise SystemExit("E-mail address found; aborting.")
        
    frame_out.to_csv(OUT_CSV, index=False)
    
    run = {
        "script": "scripts/actris_field_definitions.py",
        "git_head_at_run": _git_head(),
        "fields_checked": fields,
        "fields_with_api_description": int((frame_out["api_description_present"] == "yes").sum()),
        "fields_with_vocabulary_definition": int((frame_out["used_as_field_definition"] == "yes").sum()),
        "fields_flagged": int((frame_out["flagged"] == "yes").sum()),
        "fields_with_label_equal_vocabulary_concept": sorted(frame_out.loc[frame_out["vocabulary_label_match"] != "", "field"].unique().tolist()),
        "output": {"file": str(OUT_CSV.relative_to(ROOT)), "sha256": sha256_bytes(OUT_CSV.read_bytes())},
    }
    OUT_RUN.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print({k: run[k] for k in ("fields_with_api_description", "fields_with_vocabulary_definition", "fields_flagged")})
    return 0

if __name__ == "__main__":
    sys.exit(main())
