"""Similarity of field names between the site-schema fields of DEIMS, ICOS and ACTRIS.

Reads ``outputs/final_field_comparison.csv`` and writes one ranking file per pair of infrastructures
(never pooled):

* ``outputs/field_similarity_deims_icos.csv`` (primary table)
* ``outputs/field_similarity_deims_actris.csv``
* ``outputs/field_similarity_icos_actris.csv``
* ``outputs/field_similarity_run.json`` (run manifest)

Every score is a cosine similarity of **field names**; it says nothing about whether two fields hold
the same kind of information. Columns:

* ``tfidf_name_sim`` / ``minilm_name_sim``: the field names only (the text is the field string as
  extracted, with no splitting of camelCase or dots).
* ``tfidf_text_sim`` / ``minilm_text_sim``: the field name followed by the published definition where
  one exists (today only ICOS ``rdfs:comment`` definitions, see ``scripts/icos_field_definitions.py``).
  For a pair where neither field has a definition the two score pairs are equal.
* ``definition_used_a`` / ``definition_used_b``: whether the ``*_text_*`` score used a definition.

TF-IDF is fitted separately on the two sides of each pair. MiniLM is
``sentence-transformers/all-MiniLM-L6-v2`` at the revision stored in ``scripts/field_model_pin.json``,
with the seed and library versions stored there. The first time (revision still ``null``) run::

    python scripts/compare_fields.py --write-pin

which needs access to huggingface.co, looks up the model's current commit, records it together with
the installed library versions, and then runs. Commit the pin file. Later runs refuse to start if the
installed library versions differ from the pin (``--allow-version-drift`` records the difference in the
manifest instead). Weights are fetched from the Hugging Face Hub at that revision on first use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from itertools import combinations
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
IN_FILE = OUT / "final_field_comparison.csv"
PIN_FILE = ROOT / "scripts" / "field_model_pin.json"
RUN_FILE = OUT / "field_similarity_run.json"

RIS = ["DEIMS", "ICOS", "ACTRIS"]
PAIR_ORDER = list(combinations(RIS, 2))  # (DEIMS, ICOS) is the primary table
LIBRARIES = ["sentence-transformers", "transformers", "torch", "huggingface_hub", "tokenizers",
             "scikit-learn", "numpy", "pandas"]
SCORE_LABEL = "similarity of field names"
OUTPUT_COLUMNS = ["ri_a", "field_a", "ri_b", "field_b", "tfidf_name_sim", "minilm_name_sim",
                  "tfidf_text_sim", "minilm_text_sim", "definition_used_a", "definition_used_b"]

Embedder = Callable[[list[str]], np.ndarray]


def pair_file(ri_a: str, ri_b: str, out_dir: Path = OUT) -> Path:
    return out_dir / f"field_similarity_{ri_a.lower()}_{ri_b.lower()}.csv"


def _is_flagged(definition) -> bool:
    return pd.isna(definition) or not str(definition).strip() or str(definition).startswith("FLAGGED")


def prepare_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``name_text``, ``text`` and ``definition_used``.

    Fields whose name contains "contact" (any RI) are removed upstream by ``scripts/consolidate_dataset.py``;
    DEIMS ``contact.*`` fields are dropped here as well in case this function gets an unfiltered table.
    """
    df = df[~((df["ri"] == "DEIMS") & df["field"].str.startswith("contact."))].copy()
    df["definition_used"] = ~df["definition"].map(_is_flagged)
    df["name_text"] = df["field"]
    df["text"] = [f"{f}. {d}" if used else f
                  for f, d, used in zip(df["field"], df["definition"], df["definition_used"])]
    return df.reset_index(drop=True)


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-12, None)
    b = b / np.clip(np.linalg.norm(b, axis=1, keepdims=True), 1e-12, None)
    return a @ b.T


def _tfidf_similarity(texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vectorizer = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b")
    matrix = vectorizer.fit_transform(texts_a + texts_b)
    return cosine_similarity(matrix[: len(texts_a)], matrix[len(texts_a):])


def _embedding_similarity(embed: Embedder, texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    unique = sorted(set(texts_a) | set(texts_b))
    vectors = dict(zip(unique, embed(unique)))
    return _cosine(np.array([vectors[t] for t in texts_a]), np.array([vectors[t] for t in texts_b]))


def rank_pair(fields: pd.DataFrame, ri_a: str, ri_b: str, embed: Embedder) -> pd.DataFrame:
    """All field pairs of two infrastructures, best MiniLM name similarity first."""
    a = fields[fields["ri"] == ri_a].reset_index(drop=True)
    b = fields[fields["ri"] == ri_b].reset_index(drop=True)
    tfidf_name = _tfidf_similarity(a["name_text"].tolist(), b["name_text"].tolist())
    tfidf_text = _tfidf_similarity(a["text"].tolist(), b["text"].tolist())
    minilm_name = _embedding_similarity(embed, a["name_text"].tolist(), b["name_text"].tolist())
    minilm_text = _embedding_similarity(embed, a["text"].tolist(), b["text"].tolist())
    rows = []
    for i, row_a in a.iterrows():
        for j, row_b in b.iterrows():
            rows.append({
                "ri_a": ri_a, "field_a": row_a["field"], "ri_b": ri_b, "field_b": row_b["field"],
                "tfidf_name_sim": round(float(tfidf_name[i, j]), 4),
                "minilm_name_sim": round(float(minilm_name[i, j]), 4),
                "tfidf_text_sim": round(float(tfidf_text[i, j]), 4),
                "minilm_text_sim": round(float(minilm_text[i, j]), 4),
                "definition_used_a": bool(row_a["definition_used"]),
                "definition_used_b": bool(row_b["definition_used"]),
            })
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return out.sort_values(["minilm_name_sim", "field_a", "field_b"], ascending=[False, True, True]).reset_index(drop=True)


# --- pinning ---------------------------------------------------------------------------------------

def load_pin(path: Path = PIN_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def installed_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in LIBRARIES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def version_drift(pinned: dict, installed: dict) -> dict[str, dict]:
    return {name: {"pinned": want, "installed": installed.get(name)}
            for name, want in pinned.items() if installed.get(name) != want}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
    except ImportError:  # the manifest records torch as missing in that case
        pass


def resolve_revision_and_weights(model_name: str) -> tuple[str, dict[str, str]]:
    from huggingface_hub import HfApi

    info = HfApi().model_info(model_name, files_metadata=True)
    weights: dict[str, str] = {}
    for sibling in (info.siblings or []):
        lfs = getattr(sibling, "lfs", None)
        sha = None
        if isinstance(lfs, dict):
            sha = lfs.get("sha256")
        elif lfs is not None:
            sha = getattr(lfs, "sha256", None)
        if sha:
            weights[sibling.rfilename] = sha
    return info.sha, weights


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Similarity of field names (TF-IDF and MiniLM).")
    parser.add_argument("--write-pin", action="store_true",
                        help="resolve the model's current Hub revision, store it with the installed library versions")
    parser.add_argument("--allow-version-drift", action="store_true",
                        help="run although installed library versions differ from the pin (recorded in the manifest)")
    args = parser.parse_args(argv)

    pin = load_pin()
    installed = installed_versions()
    if args.write_pin:
        pin["revision"], pin["weights"] = resolve_revision_and_weights(pin["model"])
        pin["libraries"] = {k: v for k, v in installed.items() if v is not None}
        pin["pinned_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        PIN_FILE.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
        print(f"Pinned {pin['model']} at {pin['revision']} ({len(pin['weights'])} weight file(s))")
    elif pin.get("revision") is None:
        print("scripts/field_model_pin.json has no revision yet. Run once with --write-pin on a machine "
              "that can reach huggingface.co, then commit the pin file.", file=sys.stderr)
        return 2

    drift = version_drift(pin["libraries"], installed)
    if drift and not args.allow_version_drift:
        print(f"Installed library versions differ from the pin: {json.dumps(drift)}", file=sys.stderr)
        return 2

    from sentence_transformers import SentenceTransformer

    set_seed(pin["seed"])
    model = SentenceTransformer(pin["model"], revision=pin["revision"])

    loaded_commit = None
    verification = "not attempted"

    # Prefer transformers' own commit hash when the installed version populates it.
    try:
        attr = model[0].auto_model.config._commit_hash
        if attr:
            loaded_commit = attr
            verification = "from transformers config._commit_hash"
    except (AttributeError, IndexError, TypeError):
        pass

    # Otherwise verify the loaded weights against the per-file hashes recorded in the pin.
    if loaded_commit is None:
        weights = pin.get("weights") or {}
        if not weights:
            verification = "pin has no weights map; re-pin with --write-pin"
        else:
            try:
                from huggingface_hub import snapshot_download
                snapshot_path = Path(snapshot_download(
                    repo_id=pin["model"], revision=pin["revision"], local_files_only=True,
                ))
                verified = 0
                mismatch = None
                for filename, expected in weights.items():
                    local = snapshot_path / filename
                    if not local.exists():
                        mismatch = f"missing {filename}"
                        break
                    actual = _sha256_file(local)
                    if actual != expected:
                        mismatch = f"{filename}: pin {expected[:12]}... actual {actual[:12]}..."
                        break
                    verified += 1
                if mismatch is None:
                    loaded_commit = pin["revision"]
                    verification = f"verified {verified}/{len(weights)} weight file(s) against pin"
                else:
                    verification = f"weight mismatch: {mismatch}"
                    print(f"Weight verification failed: {mismatch}", file=sys.stderr)
                    return 2
            except (ImportError, OSError, ValueError) as exc:
                verification = f"could not verify weights: {exc!r}"

    if loaded_commit and loaded_commit != pin["revision"]:
        print(f"Loaded revision {loaded_commit} but the pin says {pin['revision']}.", file=sys.stderr)
        return 2

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, show_progress_bar=False)

    fields = prepare_fields(pd.read_csv(IN_FILE))
    counts = {ri: int((fields["ri"] == ri).sum()) for ri in RIS}
    print(f"Fields: {counts}")
    outputs = {}
    for ri_a, ri_b in PAIR_ORDER:
        ranked = rank_pair(fields, ri_a, ri_b, embed)
        path = pair_file(ri_a, ri_b)
        ranked.to_csv(path, index=False)
        outputs[f"{ri_a}-{ri_b}"] = {"file": str(path.relative_to(ROOT)), "pairs": int(len(ranked)),
                                     "sha256": _sha256_file(path)}
        print(f"  {ri_a} x {ri_b}: {len(ranked)} pairs -> {path.relative_to(ROOT)}")

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/compare_fields.py",
        "git_head_at_run": _git_head(),
        "score_label": SCORE_LABEL,
        "text_rule": ("name_text = field string as extracted; text = field string + '. ' + published "
                      "definition where one exists (ICOS rdfs:comment only); fields whose name contains 'contact' "
                      "are dropped in all RIs (consolidate_dataset.py)"),
        "input": {"file": str(IN_FILE.relative_to(ROOT)), "sha256": _sha256_file(IN_FILE)},
        "field_counts": counts,
        "fields_with_definition": {ri: int(fields.loc[fields["ri"] == ri, "definition_used"].sum()) for ri in RIS},
        "tables": outputs,
        "model": {"name": pin["model"], "revision_pinned": pin["revision"],
                  "revision_loaded": loaded_commit,
                  "revision_loaded_verification": verification},
        "seed": pin["seed"],
        "pin_file": {"file": str(PIN_FILE.relative_to(ROOT)), "sha256": _sha256_file(PIN_FILE)},
        "library_versions": installed,
        "library_version_drift_from_pin": drift,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    RUN_FILE.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {RUN_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
