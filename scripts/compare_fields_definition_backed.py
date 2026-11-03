"""Definition-backed similarity tables for the site-schema fields of DEIMS, ICOS and ACTRIS.

A second set of the three tables written by ``scripts/compare_fields.py``; the name-only tables are not
touched. Same fields, same pairs, same MiniLM revision and weight check, same seed (all read from
``scripts/field_model_pin.json``). What differs is the text that is embedded for the ``*_text_sim`` columns:

* the published definition where the field has one, verbatim;
* otherwise the field name.

(The name-only tables use "field name. definition". Here the definition stands alone, as asked for the
definition-backed set.) The ``*_name_sim`` columns are computed exactly as in the name-only tables, so they
repeat those values and show what the definitions change. Definitions come from
``outputs/final_field_comparison_definition_backed.csv`` (``scripts/build_definition_backed_input.py``):
ICOS ``rdfs:comment`` for 5 fields and the DEIMS-SDR Site Metadata Model ``Definition`` for the DEIMS fields
that a ``direct`` or ``curated`` mapping row covers. ACTRIS has none. A pair in which only one side has a
definition compares a definition sentence with a bare field name; ``definition_used_a`` / ``definition_used_b``
mark every such pair. Scores are cosine **similarity of text**, not evidence that two fields mean the same.

Outputs (the pairs are never pooled; DEIMS-ICOS is the primary table):

* ``outputs/field_similarity_definition_backed_deims_icos.csv``
* ``outputs/field_similarity_definition_backed_deims_actris.csv``
* ``outputs/field_similarity_definition_backed_icos_actris.csv``
* ``outputs/field_similarity_definition_backed_run.json`` (run manifest)

Run it on a machine that can reach huggingface.co once, or that already holds the pinned snapshot::

    python scripts/build_definition_backed_input.py
    python scripts/compare_fields_definition_backed.py

The pin must already exist (``python scripts/compare_fields.py --write-pin`` was run for the name-only
tables); this script never writes or moves it. It exits with 2 if the input file does not match the hash
recorded by ``build_definition_backed_input.py``, if library versions differ from the pin (unless
``--allow-version-drift``), or if the pinned weights cannot be verified (unless
``--allow-unverified-snapshot``, which the manifest records).
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scripts import compare_fields as cf
except ImportError:  # run as ``python scripts/compare_fields_definition_backed.py``
    import compare_fields as cf

ROOT = cf.ROOT
OUT = cf.OUT
IN_FILE = OUT / "final_field_comparison_definition_backed.csv"
IN_RUN = OUT / "definition_backed_input_run.json"
RUN_FILE = OUT / "field_similarity_definition_backed_run.json"
SCORE_LABEL = "similarity of definition-backed text"
TEXT_RULE = ("text = the published definition verbatim where the field has one (ICOS rdfs:comment; DEIMS-SDR "
             "Site Metadata Model 'Definition' via a direct or curated mapping row), else the field name; "
             "name_text = field string as extracted; fields whose name contains 'contact' are dropped in "
             "all RIs; ACTRIS has 3 label-matched vocabulary definitions (CC0 1.0)")


def pair_file(ri_a: str, ri_b: str, out_dir: Path = OUT) -> Path:
    return out_dir / f"field_similarity_definition_backed_{ri_a.lower()}_{ri_b.lower()}.csv"


def prepare_definition_backed(df: pd.DataFrame) -> pd.DataFrame:
    """``compare_fields.prepare_fields`` with ``text`` = definition where one exists, else the field name."""
    prepared = cf.prepare_fields(df)
    prepared["text"] = [d if used else f for f, d, used in
                        zip(prepared["field"], prepared["definition"], prepared["definition_used"])]
    return prepared


def write_tables(fields: pd.DataFrame, embed: cf.Embedder, out_dir: Path = OUT) -> dict:
    """Rank every pair of infrastructures and write the three files; return the manifest entries."""
    outputs = {}
    for ri_a, ri_b in cf.PAIR_ORDER:
        ranked = cf.rank_pair(fields, ri_a, ri_b, embed)
        path = pair_file(ri_a, ri_b, out_dir)
        ranked.to_csv(path, index=False)
        outputs[f"{ri_a}-{ri_b}"] = {"file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                                     "pairs": int(len(ranked)), "sha256": cf._sha256_file(path)}
    return outputs


def input_matches_recorded_hash(input_file: Path = IN_FILE, run_file: Path = IN_RUN) -> tuple[bool, str]:
    if not run_file.exists():
        return False, f"{run_file.name} is missing; run scripts/build_definition_backed_input.py first"
    recorded = json.loads(run_file.read_text(encoding="utf-8")).get("output", {}).get("sha256")
    actual = cf._sha256_file(input_file)
    if recorded != actual:
        return False, (f"{input_file.name} (sha256 {actual[:12]}...) does not match the hash recorded in "
                       f"{run_file.name} ({str(recorded)[:12]}...); run scripts/build_definition_backed_input.py")
    return True, "input matches the recorded hash"


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    try:
        dirty = [line[3:] for line in run("status", "--porcelain").splitlines()]
        return {"head": run("rev-parse", "HEAD").strip(), "working_tree_clean": not dirty,
                "uncommitted_paths": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"head": None, "working_tree_clean": None, "uncommitted_paths": []}


def build_manifest(*, fields: pd.DataFrame, outputs: dict, pin: dict, installed: dict, drift: dict,
                   loaded_commit, verification: str, weights_verified: bool, allow_unverified: bool,
                   git: dict, now: datetime) -> dict:
    sources = {}
    for name in ("deims_model_definitions_run.json", "definition_backed_input_run.json"):
        path = OUT / name
        if path.exists():
            sources[f"outputs/{name}"] = cf._sha256_file(path)
    mapping = ROOT / "data" / "mappings" / "deims_model_field_mapping.csv"
    if mapping.exists():
        sources["data/mappings/deims_model_field_mapping.csv"] = cf._sha256_file(mapping)
    model_run = OUT / "deims_model_definitions_run.json"
    model_info = json.loads(model_run.read_text(encoding="utf-8")).get("model") if model_run.exists() else None
    counts = {ri: int((fields["ri"] == ri).sum()) for ri in cf.RIS}
    return {
        "timestamp_utc": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/compare_fields_definition_backed.py",
        "git_head_at_run": git["head"],
        "git_working_tree_clean": git["working_tree_clean"],
        "git_uncommitted_paths": git["uncommitted_paths"],
        "score_label": SCORE_LABEL,
        "text_rule": TEXT_RULE,
        "definition_sources": {"DEIMS": model_info, "ICOS": "rdfs:comment at https://meta.icos-cp.eu/sparql",
                               "ACTRIS": "hand-copied from ACTRIS SKOSMOS vocabulary (CC0 1.0)"},
        "definition_source_files": sources,
        "input": {"file": str(IN_FILE.relative_to(ROOT)), "sha256": cf._sha256_file(IN_FILE)},
        "field_counts": counts,
        "fields_with_definition": {ri: int(fields.loc[fields["ri"] == ri, "definition_used"].sum())
                                   for ri in cf.RIS},
        "tables": outputs,
        "model": {"name": pin["model"], "revision_pinned": pin["revision"], "revision_loaded": loaded_commit,
                  "revision_loaded_verification": verification, "weights_verified": weights_verified,
                  "allow_unverified_snapshot": bool(allow_unverified)},
        "seed": pin["seed"],
        "pin_file": {"file": str(cf.PIN_FILE.relative_to(ROOT)), "sha256": cf._sha256_file(cf.PIN_FILE)},
        "library_versions": installed,
        "library_version_drift_from_pin": drift,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Definition-backed field similarity tables.")
    parser.add_argument("--allow-version-drift", action="store_true",
                        help="run although installed library versions differ from the pin (recorded)")
    parser.add_argument("--allow-unverified-snapshot", action="store_true",
                        help="run although the pinned weights cannot be verified (recorded in the manifest)")
    args = parser.parse_args(argv)

    ok, message = input_matches_recorded_hash()
    if not ok:
        print(message, file=sys.stderr)
        return 2
    pin = cf.load_pin()
    if pin.get("revision") is None:
        print("scripts/field_model_pin.json has no revision. Run 'python scripts/compare_fields.py "
              "--write-pin' first; this script never writes the pin.", file=sys.stderr)
        return 2
    installed = cf.installed_versions()
    drift = cf.version_drift(pin["libraries"], installed)
    if drift and not args.allow_version_drift:
        print(f"Installed library versions differ from the pin: {json.dumps(drift)}", file=sys.stderr)
        return 2

    from sentence_transformers import SentenceTransformer

    cf.set_seed(pin["seed"])
    model = SentenceTransformer(pin["model"], revision=pin["revision"])
    transformers_commit = None
    try:
        transformers_commit = model[0].auto_model.config._commit_hash or None
    except (AttributeError, IndexError, TypeError):
        pass
    loaded_commit, verification, weights_verified, error = cf.verify_loaded_model(
        transformers_commit, pin, args.allow_unverified_snapshot)
    if error:
        print(error, file=sys.stderr)
        return 2

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, show_progress_bar=False)

    fields = prepare_definition_backed(pd.read_csv(IN_FILE))
    print(f"Fields: { {ri: int((fields['ri'] == ri).sum()) for ri in cf.RIS} }")
    outputs = write_tables(fields, embed)
    for key, entry in outputs.items():
        print(f"  {key}: {entry['pairs']} pairs -> {entry['file']}")
    manifest = build_manifest(fields=fields, outputs=outputs, pin=pin, installed=installed, drift=drift,
                              loaded_commit=loaded_commit, verification=verification,
                              weights_verified=weights_verified, allow_unverified=args.allow_unverified_snapshot,
                              git=git_state(), now=datetime.now(timezone.utc))
    RUN_FILE.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {RUN_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
