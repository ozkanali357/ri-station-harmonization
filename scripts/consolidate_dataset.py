"""Combine the field lists with every published definition into ``outputs/final_field_comparison.csv``.

Inputs (all under ``outputs/``): ``field_comparison_dataset.csv`` (the fields of each RI),
``definitions_extracted.csv`` (definitions pulled from the DEIMS and ACTRIS APIs) and
``icos_field_definitions.csv`` (``rdfs:comment`` definitions from ``scripts/icos_field_definitions.py``).

A field keeps the text ``FLAGGED: No published API definition found`` unless one of those files holds a
published definition for it. Nothing is filled in from any other source. Contact fields (any RI) are
dropped here as a safeguard: nothing from a contact block is compared.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT = Path("outputs")
FLAG_TEXT = "FLAGGED: No published API definition found"


def _clean(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def consolidate(fields: pd.DataFrame, defs: pd.DataFrame, icos_defs: pd.DataFrame) -> pd.DataFrame:
    published: dict[tuple[str, str], str] = {}
    for frame in (defs, icos_defs):
        for row in frame.itertuples(index=False):
            text = _clean(row.definition)
            if text and not text.startswith("FLAGGED"):
                published[(row.ri, row.field)] = text

    contact_mask = fields["field"].str.contains("contact", case=False, na=False)
    fields = fields[~contact_mask]
    out = fields[["ri", "field"]].copy()
    out["definition"] = [published.get((ri, field), FLAG_TEXT) for ri, field in zip(out["ri"], out["field"])]
    out["flagged"] = ["yes" if d.startswith("FLAGGED") else "no" for d in out["definition"]]
    return out


def main() -> None:
    fields = pd.read_csv(OUT / "field_comparison_dataset.csv")
    defs_file = OUT / "definitions_extracted.csv"
    defs = pd.read_csv(defs_file) if defs_file.exists() else pd.DataFrame(columns=["ri", "field", "definition"])
    icos_file = OUT / "icos_field_definitions.csv"
    icos_defs = pd.read_csv(icos_file) if icos_file.exists() else pd.DataFrame(columns=["ri", "field", "definition"])

    final = consolidate(fields, defs, icos_defs)
    final.to_csv(OUT / "final_field_comparison.csv", index=False)
    print(f"Saved {len(final)} fields to {OUT / 'final_field_comparison.csv'}")
    print(final.groupby(["ri", "flagged"]).size().to_string())


if __name__ == "__main__":
    main()
