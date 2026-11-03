"""Build the sheet for the manual review of top-ranked field-name pairs (DEIMS x ICOS).

Reads the committed ``outputs/field_similarity_deims_icos.csv`` (sorted by ``minilm_name_sim``) and
``outputs/final_field_comparison.csv`` and writes

* ``outputs/field_review_sheet_deims_icos.csv``: what the reviewer sees. Columns ``pair_id``,
  ``deims_field``, ``icos_field``, ``icos_definition`` (the published ``rdfs:comment``, else
  ``FLAGGED``), ``reviewer_label`` and ``evidence_note`` (both empty). No score and no rank, so the
  reviewer is not anchored by the similarity.
* ``outputs/field_review_key_deims_icos.csv``: ``pair_id`` to ``selection`` (top10 or random), rank by
  ``minilm_name_sim`` (1 = highest) and the scores. Keep it away from the reviewer until the sheet is filled.
* ``outputs/field_review_sheet_run.json``: seed, input checksums and counts.

Selection: the 10 highest pairs by ``minilm_name_sim`` plus a random sample of 10 of the remaining
pairs (``random.Random(SEED)``), all 20 shuffled with the same generator; ``pair_id`` is assigned after
the shuffle (R01, R02, ...) so it carries no rank information. This is a manual review of top-ranked
field-name pairs, not ground truth: the random part is a small sample of the rest, not a stratified or
population-wide one.

Usage (from the repo root)::

    python scripts/make_field_review_sheet.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
TABLE = OUT / "field_similarity_deims_icos.csv"
FIELDS = OUT / "final_field_comparison.csv"
SHEET = OUT / "field_review_sheet_deims_icos.csv"
KEY = OUT / "field_review_key_deims_icos.csv"
RUN = OUT / "field_review_sheet_run.json"

SEED = 42
N_TOP = 10
N_RANDOM = 10
SHEET_COLUMNS = ["pair_id", "deims_field", "icos_field", "icos_definition", "reviewer_label", "evidence_note"]
KEY_COLUMNS = ["pair_id", "selection", "rank_minilm_name_sim", "minilm_name_sim", "tfidf_name_sim",
               "minilm_text_sim", "tfidf_text_sim"]


def build(table: pd.DataFrame, fields: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    table = table.sort_values(["minilm_name_sim", "field_a", "field_b"], ascending=[False, True, True]).reset_index(drop=True)
    table["rank_minilm_name_sim"] = range(1, len(table) + 1)
    top = table.iloc[:N_TOP].assign(selection="top10")
    rest = table.iloc[N_TOP:]
    rng = random.Random(seed)
    picked = sorted(rng.sample(range(len(rest)), N_RANDOM))
    sample = rest.iloc[picked].assign(selection="random")
    chosen = pd.concat([top, sample]).reset_index(drop=True)
    order = list(range(len(chosen)))
    rng.shuffle(order)
    chosen = chosen.iloc[order].reset_index(drop=True)
    chosen["pair_id"] = [f"R{i:02d}" for i in range(1, len(chosen) + 1)]

    icos = fields[fields["ri"] == "ICOS"].set_index("field")["definition"]

    def definition(name: str) -> str:
        text = icos.get(name, "")
        return "FLAGGED" if pd.isna(text) or not str(text).strip() or str(text).startswith("FLAGGED") else str(text)

    sheet = pd.DataFrame({
        "pair_id": chosen["pair_id"],
        "deims_field": chosen["field_a"],
        "icos_field": chosen["field_b"],
        "icos_definition": [definition(name) for name in chosen["field_b"]],
        "reviewer_label": "",
        "evidence_note": "",
    }, columns=SHEET_COLUMNS)
    key = chosen[KEY_COLUMNS]
    return sheet, key


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    table = pd.read_csv(TABLE)
    fields = pd.read_csv(FIELDS)
    sheet, key = build(table, fields)
    sheet.to_csv(SHEET, index=False)
    key.to_csv(KEY, index=False)
    RUN.write_text(json.dumps({
        "script": "scripts/make_field_review_sheet.py",
        "title": "manual review of top-ranked field-name pairs (not ground truth)",
        "seed": SEED, "n_top": N_TOP, "n_random": N_RANDOM,
        "random_population": "pairs ranked 11 and below by minilm_name_sim",
        "input_table": {"file": str(TABLE.relative_to(ROOT)), "rows": int(len(table)), "sha256": _sha256(TABLE)},
        "input_fields": {"file": str(FIELDS.relative_to(ROOT)), "sha256": _sha256(FIELDS)},
        "outputs": {str(p.relative_to(ROOT)): _sha256(p) for p in (SHEET, KEY)},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {SHEET.relative_to(ROOT)} ({len(sheet)} pairs), {KEY.relative_to(ROOT)}, {RUN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
