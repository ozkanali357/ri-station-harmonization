"""Build the input of the definition-backed field comparison.

Reads:

* ``outputs/final_field_comparison.csv`` (committed) - the 117 compared fields and the definitions found so
  far (ICOS ``rdfs:comment`` only). It is not changed.
* ``outputs/deims_model_definitions.csv`` (**git-ignored, produced locally**) - the definitions of the
  DEIMS-SDR Site Metadata Model. If it is missing, this script runs ``scripts/deims_model_definitions.py``,
  which fetches the model JSON into ``data/raw/deims_model/`` (git-ignored) and compares its SHA-256 with
  the committed record ``outputs/deims_model_definitions_run.json``; a difference stops the run. If the CSV
  exists, its SHA-256 must equal that record as well.
* ``data/mappings/deims_model_field_mapping.csv`` (committed) - the explicit mapping from the model's
  fields to the DEIMS API field paths, with the relation of each row.

A DEIMS API field receives the model's ``Definition`` text (verbatim) only if a mapping row with relation
``direct`` or ``curated`` points at it and the model publishes a definition for that field. Rows with
relation ``component`` (the API field is a part of a model field) or ``candidate`` (name resemblance only)
never transfer a definition. Every other field keeps what ``final_field_comparison.csv`` says, which is
the flag text for all DEIMS and ACTRIS fields not covered here. Nothing is filled in.

Writes ``outputs/final_field_comparison_definition_backed.csv`` (**git-ignored**: it holds the model's
text), ``outputs/deims_model_mapping_unmapped.csv`` (what is not covered, on both sides; field paths only) and
``outputs/definition_backed_input_run.json`` (counts and checksums).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

try:
    from scripts import deims_model_definitions as dmd
except ImportError:  # run as ``python scripts/build_definition_backed_input.py``
    import deims_model_definitions as dmd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
IN_FIELDS = OUT / "final_field_comparison.csv"
IN_MODEL = OUT / "deims_model_definitions.csv"
IN_MODEL_RUN = OUT / "deims_model_definitions_run.json"
IN_MAPPING = ROOT / "data" / "mappings" / "deims_model_field_mapping.csv"
OUT_INPUT = OUT / "final_field_comparison_definition_backed.csv"
OUT_UNMAPPED = OUT / "deims_model_mapping_unmapped.csv"
OUT_RUN = OUT / "definition_backed_input_run.json"

TRANSFER_RELATIONS = ("direct", "curated")
ALL_RELATIONS = ("direct", "curated", "component", "candidate")
FLAG_TEXT = "FLAGGED: No published API definition found"
OUTPUT_COLUMNS = ["ri", "field", "definition", "flagged", "definition_source", "model_page_path",
                  "mapping_relation"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_mapping(mapping: pd.DataFrame, model: pd.DataFrame, fields: pd.DataFrame) -> None:
    """Fail loudly if the mapping names a field that does not exist or maps a field twice."""
    bad = sorted(set(mapping["relation"]) - set(ALL_RELATIONS))
    if bad:
        raise ValueError(f"unknown relation(s) in the mapping: {bad}")
    unknown_page = sorted(set(mapping["page_path"]) - set(model["page_path"]))
    if unknown_page:
        raise ValueError(f"mapping names model fields that were not extracted: {unknown_page}")
    page_names = dict(zip(model["page_path"], model["page_field_name"]))
    wrong = [(p, n) for p, n in zip(mapping["page_path"], mapping["page_field_name"]) if page_names[p] != n]
    if wrong:
        raise ValueError(f"page_field_name does not match the extracted model for: {wrong}")
    deims = set(fields.loc[fields["ri"] == "DEIMS", "field"])
    unknown_api = sorted(set(mapping["api_field"]) - deims)
    if unknown_api:
        raise ValueError(f"mapping names API fields that are not in final_field_comparison.csv: {unknown_api}")
    transfers = mapping[mapping["relation"].isin(TRANSFER_RELATIONS)]
    twice = transfers["api_field"][transfers["api_field"].duplicated()].tolist()
    if twice:
        raise ValueError(f"API field mapped by more than one direct/curated row: {twice}")
    twice_page = transfers["page_path"][transfers["page_path"].duplicated()].tolist()
    if twice_page:
        raise ValueError(f"model field mapped to more than one API field by direct/curated rows: {twice_page}")
    dupes = mapping[mapping.duplicated(["page_path", "api_field"], keep=False)]
    if len(dupes):
        raise ValueError(f"the same page/API pair appears twice: {dupes[['page_path', 'api_field']].values.tolist()}")


def build_input(fields: pd.DataFrame, model: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    validate_mapping(mapping, model, fields)
    published = model[model["definition_published"] == "yes"].set_index("page_path")
    transfers = mapping[mapping["relation"].isin(TRANSFER_RELATIONS)].set_index("api_field")
    version = str(model["model_version"].iloc[0]) if len(model) else ""
    source = f"DEIMS-SDR Site Metadata Model v{version}, Definition"

    out = fields[["ri", "field", "definition", "flagged"]].copy()
    out["definition_source"] = ""
    out["model_page_path"] = ""
    out["mapping_relation"] = ""
    for i, row in out.iterrows():
        if row["flagged"] == "no":  # an ICOS rdfs:comment found earlier; kept as it is
            out.at[i, "definition_source"] = "rdfs:comment published at https://meta.icos-cp.eu/sparql"
            continue
        if row["ri"] != "DEIMS" or row["field"] not in transfers.index:
            continue
        link = transfers.loc[row["field"]]
        out.at[i, "model_page_path"] = link["page_path"]
        out.at[i, "mapping_relation"] = link["relation"]
        if link["page_path"] in published.index:
            out.at[i, "definition"] = published.at[link["page_path"], "definition"]
            out.at[i, "flagged"] = "no"
            out.at[i, "definition_source"] = source
    return out[OUTPUT_COLUMNS]


def unmapped_report(fields: pd.DataFrame, model: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """What is not covered by a direct/curated row, on both sides, and why."""
    rows = []
    transfer_pages = set(mapping.loc[mapping["relation"].isin(TRANSFER_RELATIONS), "page_path"])
    by_page = mapping.groupby("page_path")["relation"].agg(lambda s: ",".join(sorted(set(s))))
    for page_path in model["page_path"]:
        if page_path in transfer_pages:
            continue
        rel = by_page.get(page_path)
        rows.append({"side": "model", "field": page_path,
                     "reason": f"only {rel} rows in the mapping" if rel else "no mapping row"})
    by_api = mapping.groupby("api_field")["relation"].agg(lambda s: ",".join(sorted(set(s))))
    covered = set(mapping.loc[mapping["relation"].isin(TRANSFER_RELATIONS), "api_field"])
    for api_field in fields.loc[fields["ri"] == "DEIMS", "field"]:
        if api_field in covered:
            continue
        rel = by_api.get(api_field)
        rows.append({"side": "api", "field": api_field,
                     "reason": f"only {rel} rows in the mapping" if rel else "no mapping row"})
    return pd.DataFrame(rows, columns=["side", "field", "reason"])


def ensure_model_definitions() -> int:
    """Produce the model CSV locally if it is missing; otherwise check it against the committed record."""
    if not IN_MODEL.exists():
        print("outputs/deims_model_definitions.csv is not in the checkout (it is git-ignored); "
              "running scripts/deims_model_definitions.py to fetch and extract it")
        return dmd.main([])
    recorded = json.loads(IN_MODEL_RUN.read_text(encoding="utf-8")).get("output", {}).get("sha256")
    if recorded != _sha256(IN_MODEL):
        print(f"CHECKSUM MISMATCH: {IN_MODEL.name} does not match the SHA-256 in {IN_MODEL_RUN.name}; "
              "delete it and run scripts/deims_model_definitions.py again", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    status = ensure_model_definitions()
    if status:
        return status
    fields = pd.read_csv(IN_FIELDS)
    model = pd.read_csv(IN_MODEL, keep_default_na=False)
    mapping = pd.read_csv(IN_MAPPING, keep_default_na=False)
    result = build_input(fields, model, mapping)
    unmapped = unmapped_report(fields, model, mapping)
    result.to_csv(OUT_INPUT, index=False)
    unmapped.to_csv(OUT_UNMAPPED, index=False)

    deims = result[result["ri"] == "DEIMS"]
    run = {
        "script": "scripts/build_definition_backed_input.py",
        "inputs": {str(p.relative_to(ROOT)): _sha256(p) for p in (IN_FIELDS, IN_MODEL, IN_MODEL_RUN, IN_MAPPING)},
        "transfer_relations": list(TRANSFER_RELATIONS),
        "mapping_rows_by_relation": mapping["relation"].value_counts().to_dict(),
        "fields_with_definition": {ri: int((result.loc[result["ri"] == ri, "flagged"] == "no").sum())
                                   for ri in ("DEIMS", "ICOS", "ACTRIS")},
        "field_counts": {ri: int((result["ri"] == ri).sum()) for ri in ("DEIMS", "ICOS", "ACTRIS")},
        "deims_fields_by_mapping_relation": deims["mapping_relation"].replace("", "none").value_counts().to_dict(),
        "deims_fields_mapped_but_model_gives_no_definition": int(
            ((deims["mapping_relation"] != "") & (deims["flagged"] == "yes")).sum()),
        "unmapped_model_fields": int((unmapped["side"] == "model").sum()),
        "unmapped_api_fields": int((unmapped["side"] == "api").sum()),
        "output": {"file": str(OUT_INPUT.relative_to(ROOT)), "sha256": _sha256(OUT_INPUT)},
        "unmapped_file": {"file": str(OUT_UNMAPPED.relative_to(ROOT)), "sha256": _sha256(OUT_UNMAPPED)},
    }
    OUT_RUN.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("fields_with_definition", "field_counts",
                                          "deims_fields_by_mapping_relation", "unmapped_model_fields",
                                          "unmapped_api_fields")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
