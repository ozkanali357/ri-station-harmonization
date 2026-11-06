"""Candidate matches between Finnish variable terms and reference-vocabulary concepts (milestone #8).

**MiniLM only proposes. It never decides.** The output is a table of candidate pairs for a human to
label. Every SKOS column (``skos_relation``, ``broader_side``, ``evidence_basis``, ``evidence_text``,
``checked_by``, ``checked_at``) is written blank and no script fills it, now or later. A similarity
score is cosine similarity of two labels; it says nothing about whether the concepts mean the same.

Inputs (cache only, no network):

* ``outputs/dictionary_terms_finland.csv``: the Finnish term table. Source terms are those whose
  ``scope_candidate`` is ``meteorology`` or ``soil``. That column is a keyword pre-filter, not a
  classification; it has false negatives (``outputs/dictionary_mapping_plan.md`` section 4 asks for a
  hand review of it that has not happened yet), so the candidate set is "keyword-flagged terms", not
  "all meteorology and soil terms". Terms are grouped by (``ri``, ``term_label``): a label that several
  concept URIs share (ICOS ``wind speed`` has four) is one source row with all its URIs listed, and
  gets its own row when the mapping rows are written later.
* the reference vocabularies cached by ``scripts/dictionary_vocab_fetch.py``: EnvThes,
  Standard Observations (``so``), ACTRIS vocabulary. eLTER_CL is cached and recorded but is **not**
  a default target: its concepts are lists for metadata fields (site type, funding source, EPSG codes,
  ...), not variables (``--vocabularies`` adds it). Deprecated concepts are never proposed.

Rules:

* A term is never matched against its own vocabulary: DEIMS terms are EnvThes concepts, ACTRIS terms
  are ``actris_vocab`` concepts. ICOS terms are matched against all targets.
* Score = max cosine similarity (``sentence-transformers/all-MiniLM-L6-v2``, revision and seed from
  ``scripts/field_model_pin.json``, same pin and weight verification as ``scripts/compare_fields.py``)
  between the source label and any English prefLabel or altLabel of the concept; the label that gave
  the score is in ``matched_label``. Texts are embedded as written (no case folding, no splitting).
* Per source term the ``--top-k`` best concepts over all its target vocabularies (default 3), ties
  broken by vocabulary then URI. There is no similarity threshold. ``rank_for_term`` is the rank.
* ``label_equal`` is the mechanical fact "the source label equals the matched label, ignoring case".
* ``labelling_round`` splits the table so a round stays under the 200-pair review-capacity estimate of
  the mapping plan (R1: ICOS and ACTRIS terms; R2: DEIMS meteorology; R3: DEIMS soil). It is a
  convenience, not a stratification.

Definition text: ACTRIS vocabulary definitions are CC0 1.0 and are in the committed table with
``target_vocabulary_version`` and ``target_licence`` on every row. EnvThes, Standard Observations and
eLTER_CL declare CC BY 4.0 in their metadata but the project owner has not accepted that yet (see
``outputs/dictionary_vocabularies_run.json``), so their definition text, and the ICOS source
definitions, go only to the git-ignored ``outputs/dictionary_candidates_finland_LOCAL.csv``, which has
the same rows and one more column per side.

Writes ``outputs/dictionary_candidates_finland.csv`` and ``outputs/dictionary_candidates_finland_run.json``.

Usage (from the repo root)::

    python scripts/dictionary_vocab_fetch.py --fetch      # once
    python scripts/dictionary_candidates.py               # needs the pinned MiniLM weights (huggingface.co once)
    python scripts/dictionary_candidates.py check outputs/dictionary_candidates_finland.csv   # after labelling
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import compare_fields as cf  # noqa: E402  (pin, version and weight verification are shared)
from scripts import dictionary_vocab_fetch as vf  # noqa: E402

OUT = ROOT / "outputs"
TERMS_CSV = OUT / "dictionary_terms_finland.csv"
CANDIDATES_CSV = OUT / "dictionary_candidates_finland.csv"
LOCAL_CSV = OUT / "dictionary_candidates_finland_LOCAL.csv"
RUN_FILE = OUT / "dictionary_candidates_finland_run.json"

DOMAINS = ["meteorology", "soil"]
DEFAULT_TARGETS = ["EnvThes", "so", "actris_vocab"]
OWN_VOCABULARY = {"ACTRIS": "actris_vocab", "eLTER": "EnvThes"}   # ICOS has none among the targets
RELATIONS = ["exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch"]
EXTRA_DECISIONS = ["rejected", "unclear"]
BROADER_SIDES = ["source", "target"]
EVIDENCE_BASES = ["uri", "uri_and_label", "label_fallback"]
ROUND_CAP = 200

HUMAN_COLUMNS = ["skos_relation", "broader_side", "evidence_basis", "evidence_text", "checked_by", "checked_at"]
CANDIDATE_COLUMNS = [
    "candidate_id", "labelling_round", "source_ri", "source_label", "source_term_uris", "n_source_uris",
    "source_domain_keyword", "source_scope_rule", "n_finnish_records",
    "target_vocabulary", "target_concept_uri", "target_pref_label", "target_alt_labels", "matched_label",
    "target_definition", "target_vocabulary_version", "target_licence",
    "minilm_label_sim", "rank_for_term", "label_equal",
] + HUMAN_COLUMNS
LOCAL_EXTRA = ["source_definition_icos", "target_definition_local"]

Embedder = Callable[[list[str]], np.ndarray]


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------

def source_terms(terms: pd.DataFrame) -> pd.DataFrame:
    """Keyword-flagged meteorology and soil terms, grouped by (ri, term_label)."""
    flagged = terms[terms["scope_candidate"].isin(DOMAINS) & (terms["term_label"].str.strip() != "")].copy()
    rows = []
    for (ri, label), group in flagged.groupby(["ri", "term_label"], sort=True):
        domains = sorted(set(group["scope_candidate"]))
        rows.append({
            "source_ri": ri, "source_label": label,
            "source_term_uris": " | ".join(sorted({u for u in group["term_uri"] if u})),
            "n_source_uris": int(len({u for u in group["term_uri"] if u})),
            "source_domain_keyword": "|".join(domains),
            "source_scope_rule": " | ".join(sorted({r for r in group["scope_rule"] if r})),
            "n_finnish_records": int(pd.to_numeric(group["n_finnish_records"], errors="coerce").max()),
            "source_definition_icos": " | ".join(sorted({d for d in group["definition"] if d})) if ri == "ICOS" else "",
        })
    return pd.DataFrame(rows)


def own_uris(source: pd.Series) -> set[str]:
    return {u for u in source["source_term_uris"].split(" | ") if u}


def labelling_round(source_ri: str, domain: str) -> str:
    if source_ri in ("ICOS", "ACTRIS"):
        return "R1"
    return "R2" if domain == "meteorology" else "R3"


def target_label_entries(concepts: pd.DataFrame) -> pd.DataFrame:
    """One row per (concept, English label): the prefLabel and every altLabel of non-deprecated concepts."""
    rows = []
    for c in concepts[(~concepts["deprecated"]) & (concepts["pref_label"] != "")].itertuples():
        rows.append((c.concept_uri, c.pref_label, "prefLabel"))
        for alt in [a for a in c.alt_labels.split(" | ") if a]:
            rows.append((c.concept_uri, alt, "altLabel"))
    return pd.DataFrame(rows, columns=["concept_uri", "label", "label_kind"])


# ---------------------------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------------------------

def generate(terms: pd.DataFrame, concepts: pd.DataFrame, embed: Embedder, top_k: int = 3,
             targets: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (committed table, local table with restricted definitions, counts)."""
    targets = targets or DEFAULT_TARGETS
    sources = source_terms(terms)
    live = concepts[concepts["vocabulary"].isin(targets) & ~concepts["deprecated"] & (concepts["pref_label"] != "")]
    by_uri = live.drop_duplicates("concept_uri").set_index("concept_uri")
    entries = {v: target_label_entries(live[live["vocabulary"] == v]) for v in targets}
    texts = sorted(set(sources["source_label"]) | {t for e in entries.values() for t in e["label"]})
    vectors = dict(zip(texts, embed(texts)))
    norm = {t: v / max(float(np.linalg.norm(v)), 1e-12) for t, v in vectors.items()}

    cand_rows = []
    for src in sources.itertuples():
        scored = []
        for vocab in targets:
            if OWN_VOCABULARY.get(src.source_ri) == vocab:
                continue
            e = entries[vocab]
            if e.empty:
                continue
            sims = np.array([norm[t] for t in e["label"]]) @ norm[src.source_label]
            frame = e.assign(sim=sims, vocabulary=vocab)
            frame = frame[~frame["concept_uri"].isin(own_uris(pd.Series(src._asdict())))]
            best = (frame.sort_values(["sim", "label_kind", "label"], ascending=[False, True, True])
                    .drop_duplicates("concept_uri"))                  # prefLabel wins a tie with an altLabel
            scored.append(best)
        if not scored:
            continue
        top = (pd.concat(scored).sort_values(["sim", "vocabulary", "concept_uri"], ascending=[False, True, True])
               .head(top_k).reset_index(drop=True))
        for rank, hit in enumerate(top.itertuples(), start=1):
            c = by_uri.loc[hit.concept_uri]
            domain = src.source_domain_keyword.split("|")[0]
            committable = (c["vocabulary"] == "actris_vocab")
            cand_rows.append({
                "labelling_round": labelling_round(src.source_ri, domain), "source_ri": src.source_ri,
                "source_label": src.source_label, "source_term_uris": src.source_term_uris,
                "n_source_uris": src.n_source_uris, "source_domain_keyword": src.source_domain_keyword,
                "source_scope_rule": src.source_scope_rule, "n_finnish_records": src.n_finnish_records,
                "target_vocabulary": hit.vocabulary, "target_concept_uri": hit.concept_uri,
                "target_pref_label": c["pref_label"], "target_alt_labels": c["alt_labels"],
                "matched_label": hit.label,
                "target_definition": c["definition"] if committable else "",
                "target_vocabulary_version": c["vocabulary_version"], "target_licence": c["vocabulary_licence"],
                "minilm_label_sim": round(float(hit.sim), 4), "rank_for_term": rank,
                "label_equal": src.source_label.strip().lower() == hit.label.strip().lower(),
                "source_definition_icos": src.source_definition_icos,
                "target_definition_local": c["definition"],
            })
    table = pd.DataFrame(cand_rows)
    table = table.sort_values(["labelling_round", "source_ri", "source_label", "rank_for_term"]).reset_index(drop=True)
    table.insert(0, "candidate_id", [f"C{i:04d}" for i in range(1, len(table) + 1)])
    for col in HUMAN_COLUMNS:
        table[col] = ""
    committed = table[CANDIDATE_COLUMNS]
    local = table[CANDIDATE_COLUMNS + LOCAL_EXTRA]
    counts = {
        "source_terms": int(len(sources)),
        "source_terms_by_ri": sources.groupby("source_ri").size().astype(int).to_dict(),
        "source_terms_by_ri_and_domain": {f"{r}|{d}": int(n) for (r, d), n in
                                          sources.groupby(["source_ri", "source_domain_keyword"]).size().items()},
        "candidates": int(len(committed)),
        "candidates_by_round": committed.groupby("labelling_round").size().astype(int).to_dict(),
        "candidates_by_target_vocabulary": committed.groupby("target_vocabulary").size().astype(int).to_dict(),
        "rounds_over_cap": {r: int(n) for r, n in committed.groupby("labelling_round").size().items() if n > ROUND_CAP},
        "target_concepts_embedded": {v: int(entries[v]["concept_uri"].nunique()) for v in targets},
        "target_deprecated_excluded": {v: int(concepts[(concepts["vocabulary"] == v)]["deprecated"].sum()) for v in targets},
    }
    return committed, local, counts


# ---------------------------------------------------------------------------------------------
# Check a labelled file (descriptive counts only)
# ---------------------------------------------------------------------------------------------

def check_labelled(table: pd.DataFrame) -> tuple[list[str], dict]:
    """Problems with hand-filled rows, plus descriptive counts. Nothing here edits or infers a label."""
    problems: list[str] = []
    allowed = set(RELATIONS) | set(EXTRA_DECISIONS)
    filled = table[table["skos_relation"].fillna("").str.strip() != ""]
    for row in filled.itertuples():
        rel = str(row.skos_relation).strip()
        if rel not in allowed:
            problems.append(f"{row.candidate_id}: skos_relation {rel!r} is not one of {sorted(allowed)}")
        side = str(row.broader_side or "").strip()
        if rel in ("broadMatch", "narrowMatch") and side not in BROADER_SIDES:
            problems.append(f"{row.candidate_id}: {rel} needs broader_side in {BROADER_SIDES}")
        if rel not in ("broadMatch", "narrowMatch") and side:
            problems.append(f"{row.candidate_id}: broader_side is set but the relation is {rel}")
        if not str(row.checked_by or "").strip() or not str(row.checked_at or "").strip():
            problems.append(f"{row.candidate_id}: checked_by and checked_at are required")
        if not str(row.evidence_text or "").strip():
            problems.append(f"{row.candidate_id}: evidence_text is required")
        basis = str(row.evidence_basis or "").strip()
        if basis not in EVIDENCE_BASES:
            problems.append(f"{row.candidate_id}: evidence_basis {basis!r} is not one of {EVIDENCE_BASES}")
    per_source = table.assign(has_relation=table["skos_relation"].fillna("").str.strip() != "")
    counts = {
        "rows": int(len(table)), "labelled": int(len(filled)), "unlabelled": int(len(table) - len(filled)),
        "by_relation": filled["skos_relation"].value_counts().to_dict(),
        "by_relation_and_rank": {f"rank {r}": g["skos_relation"].value_counts().to_dict()
                                 for r, g in filled.groupby("rank_for_term")},
        "by_evidence_basis": filled["evidence_basis"].value_counts().to_dict(),
        "source_terms_with_any_exact_or_close": int(per_source[per_source["skos_relation"].isin(["exactMatch", "closeMatch"])]
                                                    .groupby(["source_ri", "source_label"]).ngroups),
        "source_terms_total": int(per_source.groupby(["source_ri", "source_label"]).ngroups),
        "note": "descriptive counts of one reviewer's labels; not ground truth, no precision",
    }
    return problems, counts


# ---------------------------------------------------------------------------------------------
# Debug embedder and main
# ---------------------------------------------------------------------------------------------

def char_ngram_embedder(dim: int = 512) -> Embedder:
    """Hashed character-trigram vectors. A stand-in to exercise the pipeline when MiniLM cannot be loaded.

    Output made with it must never be committed or labelled; ``main`` refuses to write it into ``outputs/``.
    """
    def embed(texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), dim))
        for i, text in enumerate(texts):
            t = f"  {text.lower()}  "
            for j in range(len(t) - 2):
                out[i, int(hashlib.md5(t[j:j + 3].encode()).hexdigest(), 16) % dim] += 1.0
        return out
    return embed


def _load_minilm(allow_drift: bool, allow_unverified: bool):
    pin = cf.load_pin()
    if pin.get("revision") is None:
        raise SystemExit("scripts/field_model_pin.json has no revision.")
    installed = cf.installed_versions()
    drift = cf.version_drift(pin["libraries"], installed)
    if drift and not allow_drift:
        raise SystemExit(f"Installed library versions differ from the pin: {json.dumps(drift)}")
    from sentence_transformers import SentenceTransformer
    cf.set_seed(pin["seed"])
    model = SentenceTransformer(pin["model"], revision=pin["revision"])
    commit = None
    try:
        commit = model[0].auto_model.config._commit_hash or None
    except (AttributeError, IndexError, TypeError):
        pass
    loaded, verification, verified, error = cf.verify_loaded_model(commit, pin, allow_unverified)
    if error:
        raise SystemExit(error)
    info = {"name": pin["model"], "revision_pinned": pin["revision"], "revision_loaded": loaded,
            "revision_loaded_verification": verification, "weights_verified": verified,
            "allow_unverified_snapshot": bool(allow_unverified), "seed": pin["seed"],
            "pin_file_sha256": cf._sha256_file(cf.PIN_FILE), "library_versions": installed,
            "library_version_drift_from_pin": drift}
    return (lambda texts: model.encode(texts, show_progress_bar=False)), info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate matches between Finnish terms and reference concepts.")
    sub = parser.add_subparsers(dest="cmd")
    check = sub.add_parser("check", help="validate a hand-labelled candidate file and print descriptive counts")
    check.add_argument("file", type=Path)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--vocabularies", nargs="+", default=DEFAULT_TARGETS,
                        choices=["EnvThes", "so", "actris_vocab", "elter_cl"])
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument("--allow-version-drift", action="store_true")
    parser.add_argument("--allow-unverified-snapshot", action="store_true")
    parser.add_argument("--debug-embedder", action="store_true",
                        help="hashed character trigrams instead of MiniLM; refused with --out-dir outputs/")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        table = pd.read_csv(args.file, dtype=str, keep_default_na=False)
        problems, counts = check_labelled(table)
        print(json.dumps(counts, indent=2))
        for p in problems:
            print("PROBLEM:", p)
        return 1 if problems else 0

    if args.debug_embedder and args.out_dir.resolve() == OUT.resolve():
        print("--debug-embedder output must not go to outputs/; pass another --out-dir.", file=sys.stderr)
        return 2
    terms = pd.read_csv(TERMS_CSV, dtype=str, keep_default_na=False)
    concepts = vf.load_all_concepts()
    if args.debug_embedder:
        embed, model_info = char_ngram_embedder(), {"name": "DEBUG hashed character trigrams, NOT MiniLM"}
    else:
        embed, model_info = _load_minilm(args.allow_version_drift, args.allow_unverified_snapshot)
    committed, local, counts = generate(terms, concepts, embed, args.top_k, args.vocabularies)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    committed_path = args.out_dir / CANDIDATES_CSV.name
    local_path = args.out_dir / LOCAL_CSV.name
    committed.to_csv(committed_path, index=False)
    local.to_csv(local_path, index=False)
    vocab_run = json.loads(vf.RUN_FILE.read_text(encoding="utf-8"))
    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/dictionary_candidates.py", "git_head_at_run": cf._git_head(),
        "purpose": ("candidate pairs for hand labelling; MiniLM proposes only; every SKOS column is blank and "
                    "must be filled by a person; scores are cosine similarity of labels"),
        "model": model_info,
        "parameters": {"top_k_per_source_term": args.top_k, "target_vocabularies": args.vocabularies,
                       "own_vocabulary_excluded": OWN_VOCABULARY, "deprecated_concepts_excluded": True,
                       "similarity": "max cosine over English prefLabel and altLabels of the concept",
                       "no_threshold": True, "round_cap_review_estimate": ROUND_CAP},
        "scope": {"rule": "dictionary_terms_finland.csv scope_candidate in " + str(DOMAINS),
                  "status": "keyword pre-filter, not hand-reviewed; has false negatives"},
        "inputs": {"terms_csv": {"file": str(TERMS_CSV.relative_to(ROOT)), "sha256": cf._sha256_file(TERMS_CSV)},
                   "vocabularies_run": {"file": str(vf.RUN_FILE.relative_to(ROOT)), "sha256": cf._sha256_file(vf.RUN_FILE)},
                   "vocabulary_dumps": {n: {"version": v["version"], "dump_sha256": v["files"]["dump"]["sha256"],
                                            "retrieved_at": v["files"]["dump"]["retrieved_at"],
                                            "declared_licences": v["declared_licences"]}
                                        for n, v in vocab_run["vocabularies"].items()}},
        "counts": counts,
        "outputs": {"committed_table": {"file": committed_path.name, "sha256": cf._sha256_file(committed_path)},
                    "local_table_not_committed": {"file": local_path.name, "sha256": cf._sha256_file(local_path)}},
        "python": platform.python_version(), "platform": platform.platform(),
    }
    (args.out_dir / RUN_FILE.name).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(counts, indent=2))
    print(f"Wrote {committed_path}, {local_path} and {RUN_FILE.name} in {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
