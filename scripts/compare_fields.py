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

which needs access to huggingface.co, looks up the model's current commit and the SHA-256 of each of its
LFS weight files, records them together with the installed library versions, and then runs. Commit the
pin file. ``--write-pin`` refuses to overwrite a pin that already has a revision unless ``--force-repin``
is also given, so the revision cannot move silently.

Later runs refuse to start if the installed library versions differ from the pin
(``--allow-version-drift`` records the difference in the manifest instead). They also re-hash every
weight file of the pinned snapshot in the local Hugging Face cache against the pin and exit with 2 on a
mismatch; if the transformers config supplies a commit hash it must equal the pinned revision. If the
snapshot cannot be found (or the pin has no weight hashes) the run exits with 2 as well, unless
``--allow-unverified-snapshot`` is given; the manifest then records that the weights were not verified.
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


def pin_note(pinned_at: str) -> str:
    return (f"revision, weight hashes and library versions were written by "
            f"'python scripts/compare_fields.py --write-pin' at {pinned_at} (UTC). "
            f"To re-pin run it again with --write-pin --force-repin on a machine that can reach huggingface.co.")


def write_pin(pin: dict, installed: dict, resolver: Callable[[str], tuple[str, dict[str, str]]], now: datetime) -> dict:
    """Return a copy of ``pin`` with revision, weight hashes, libraries, time and note filled in."""
    new = dict(pin)
    new["revision"], new["weights"] = resolver(pin["model"])
    new["libraries"] = {k: v for k, v in installed.items() if v is not None}
    new["pinned_at"] = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    new["note"] = pin_note(new["pinned_at"])
    return new


def locate_snapshot(pin: dict) -> Path:
    """Folder of the pinned snapshot in the local Hugging Face cache; never touches the network."""
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo_id=pin["model"], revision=pin["revision"], local_files_only=True))


def check_weights(weights: dict[str, str], snapshot_path: Path) -> tuple[int, str | None]:
    """Re-hash every pinned file; return (number verified, first problem or None)."""
    verified = 0
    for filename, expected in weights.items():
        local = snapshot_path / filename
        if not local.exists():
            return verified, f"missing {filename}"
        actual = _sha256_file(local)
        if actual != expected:
            return verified, f"{filename}: pin {expected[:12]}... actual {actual[:12]}..."
        verified += 1
    return verified, None


def verify_loaded_model(transformers_commit: str | None, pin: dict, allow_unverified: bool,
                        locate: Callable[[dict], Path] | None = None) -> tuple[str | None, str, bool, str | None]:
    """Return ``(revision_loaded, verification text, weights_verified, error)``; a non-None error means exit 2."""
    if transformers_commit and transformers_commit != pin["revision"]:
        return None, "transformers commit hash differs from pin", False, (
            f"Loaded revision {transformers_commit} but the pin says {pin['revision']}.")
    weights = pin.get("weights") or {}
    if not weights:
        reason = "the pin has no weight hashes; re-pin with --write-pin --force-repin"
    else:
        try:
            snapshot = (locate or locate_snapshot)(pin)
        except (ImportError, OSError, ValueError) as exc:
            reason = f"could not find the pinned snapshot in the local cache: {exc!r}"
        else:
            verified, problem = check_weights(weights, snapshot)
            if problem:
                return None, f"weight mismatch: {problem}", False, f"Weight verification failed: {problem}"
            text = f"verified {verified}/{len(weights)} weight file(s) against pin"
            if transformers_commit:
                return transformers_commit, f"transformers commit hash equals pin; {text}", True, None
            return pin["revision"], text, True, None
    if not allow_unverified:
        return None, f"NOT verified: {reason}", False, (
            f"Cannot verify the loaded model: {reason}. Pass --allow-unverified-snapshot to run anyway; "
            f"the manifest will record that the weights were not verified.")
    note = f"weights NOT verified ({reason}); run with --allow-unverified-snapshot"
    if transformers_commit:
        return transformers_commit, f"transformers commit hash equals pin; {note}", False, None
    return None, note, False, None


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
    parser.add_argument("--force-repin", action="store_true",
                        help="with --write-pin: overwrite a pin that already has a revision")
    parser.add_argument("--allow-unverified-snapshot", action="store_true",
                        help="run although the pinned snapshot cannot be found to verify the weights "
                             "(the manifest records that they were not verified)")
    args = parser.parse_args(argv)

    pin = load_pin()
    installed = installed_versions()
    if args.write_pin:
        if pin.get("revision") is not None and not args.force_repin:
            print(f"The pin already has revision {pin['revision']}; --write-pin would replace it with the "
                  "model's current revision. Pass --force-repin as well if that is intended.", file=sys.stderr)
            return 2
        pin = write_pin(pin, installed, resolve_revision_and_weights, datetime.now(timezone.utc))
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

    transformers_commit = None
    try:
        transformers_commit = model[0].auto_model.config._commit_hash or None
    except (AttributeError, IndexError, TypeError):
        pass
    loaded_commit, verification, weights_verified, error = verify_loaded_model(
        transformers_commit, pin, args.allow_unverified_snapshot)
    if error:
        print(error, file=sys.stderr)
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
                  "revision_loaded_verification": verification,
                  "weights_verified": weights_verified,
                  "allow_unverified_snapshot": bool(args.allow_unverified_snapshot)},
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
