"""Reference-vocabulary lookups for the Finnish term table (Step 3, dictionary: terms first).

Reads ``outputs/dictionary_terms_finland.csv`` and writes ``outputs/dictionary_reference_finland.csv``,
one row per lookup hit, plus a run file with endpoints, checksums and counts. Nothing is mapped:
every row says which mechanical lookup produced it, and a term without a row had no hit.

Reference vocabularies (Skosmos REST APIs, fetched 2026-10-20):

* eLTER: ``EnvThes``, ``so`` (Standard Observations) and ``elter_cl`` (Controlled Lists) at
  ``https://vocabs.lter-europe.net/rest/v1/<vocab>``. EnvThes is the vocabulary the DEIMS
  ``observedProperties`` URIs point into. ``elter_cl`` turned out to be lists for metadata fields
  (site type, INSPIRE data theme, equipment, ...), not measured variables; ``so`` groups its
  observations by sphere (Atmosphere, Geosphere, ...).
* ACTRIS: ``actris_vocab`` and ``actris_ctrl_lists`` at
  ``https://vocabulary.actris.nilu.no/skosmos/rest/v1/<vocab>``.
* NERC Vocabulary Server P07 (CF standard names), only for URIs ICOS publishes as ``skos:closeMatch``.

Lookups:

* ``uri_resolves``: a DEIMS term's EnvThes URI, resolved to the concept as EnvThes publishes it
  today. ``published_label_matches`` says whether the DEIMS label equals that concept's prefLabel,
  one of its altLabels, or neither; ``reference_deprecated`` and ``reference_replaced_by`` are
  EnvThes's own flags.
* ``published_match_uri``: the NERC concept an ICOS term names as ``skos:closeMatch``.
* ``label_equals_prefLabel`` / ``label_equals_altLabel``: the term's label equals, ignoring case,
  a prefLabel or altLabel in the vocabulary. This is string equality, not a statement that the
  concepts are the same. Every term is looked up in the three eLTER vocabularies; ACTRIS terms are
  also looked up in the two ACTRIS vocabularies (their own). A concept that is the term's own URI
  is not repeated as a label hit.

The vocabulary indexes (``/index/<letter>``) list non-deprecated concepts only; deprecated ones are
reached through ``uri_resolves``. Raw responses are cached in ``data/raw/dictionary_reference/``
(ignored by Git) with SHA-256 and retrieval time in ``data/raw/manifest.json``.

Usage (from the repo root)::

    python scripts/dictionary_reference.py            # cached responses only
    python scripts/dictionary_reference.py --fetch    # fetch what the cache lacks
"""

from __future__ import annotations

import argparse
import hashlib
import json
import string
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import dictionary_terms as dt  # noqa: E402
from ri_harmonize.sources import TIMEOUT, UA, _now, _read_manifest, _write_manifest  # noqa: E402

OUT = ROOT / "outputs"
RAW = ROOT / "data" / "raw"
REF_DIR = "dictionary_reference"
TERMS_CSV = OUT / "dictionary_terms_finland.csv"
PAUSE_SECONDS = 0.1
ELTER_REST = "https://vocabs.lter-europe.net/rest/v1"
ACTRIS_REST = "https://vocabulary.actris.nilu.no/skosmos/rest/v1"
NERC_P07 = "http://vocab.nerc.ac.uk/collection/P07/current/"
VOCABS = {
    "EnvThes": ELTER_REST, "so": ELTER_REST, "elter_cl": ELTER_REST,
    "actris_vocab": ACTRIS_REST, "actris_ctrl_lists": ACTRIS_REST,
}
CROSS_VOCABS = ["EnvThes", "so", "elter_cl"]      # every term is looked up here
OWN_VOCABS = {"ACTRIS": ["actris_vocab", "actris_ctrl_lists"]}
INDEX_LETTERS = list(string.ascii_uppercase) + ["0-9", "!*"]

COLUMNS = [
    "ri", "term_label", "term_uri", "lookup", "published_label_matches", "reference_vocabulary",
    "reference_uri", "reference_pref_label", "reference_alt_labels", "reference_definition",
    "reference_broader", "reference_deprecated", "reference_replaced_by", "reference_exact_match_uris",
    "status", "source_url", "fetched_at",
]


# ---------------------------------------------------------------------------------------------
# Cache and fetch
# ---------------------------------------------------------------------------------------------

def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Cache:
    """Byte-for-byte cache under ``<raw>/dictionary_reference/`` with a page list for the manifest."""

    def __init__(self, raw_dir: Path, offline: bool):
        self.root, self.offline = Path(raw_dir) / REF_DIR, offline
        self.root.mkdir(parents=True, exist_ok=True)
        previous = _read_manifest(raw_dir).get("sources", {}).get("dictionary_reference", {})
        self.raw_dir = Path(raw_dir)
        self.pages = {p["file"]: p for p in previous.get("pages", [])}
        self.fetched_any = False

    def get(self, relpath: str, url: str, params: dict | None = None, allow_404: bool = False) -> bytes | None:
        path = self.root / relpath
        if path.exists():
            return path.read_bytes()
        missing = path.with_name(path.name + ".404")      # a recorded "no such concept" answer
        if missing.exists():
            return None
        if self.offline:
            raise FileNotFoundError(f"{path} is missing and --offline was requested.")
        if self.fetched_any:
            time.sleep(PAUSE_SECONDS)
        response = requests.get(url, params=params, headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
        self.fetched_any = True
        found = response.status_code != 404 or not allow_404
        if found:
            response.raise_for_status()
        target = path if found else missing
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        self.pages[f"{REF_DIR}/{relpath}" + ("" if found else ".404")] = {
            "file": f"{REF_DIR}/{relpath}" + ("" if found else ".404"), "url": response.url, "status": response.status_code,
            "sha256": hashlib.sha256(response.content).hexdigest(), "bytes": len(response.content), "retrieved_at": _now()}
        return response.content if found else None

    @property
    def not_found(self) -> list[str]:
        return sorted(p["url"] for p in self.pages.values() if p.get("status") == 404)

    def retrieved_at(self, relpath: str) -> str:
        return self.pages.get(f"{REF_DIR}/{relpath}", {}).get("retrieved_at", "")

    def write_manifest(self) -> None:
        if self.fetched_any:
            _write_manifest(self.raw_dir, "dictionary_reference", {
                "endpoints": [ELTER_REST, ACTRIS_REST, NERC_P07], "retrieved_at": _now(), "complete": True,
                "checksum_of": "raw response bytes", "pages": sorted(self.pages.values(), key=lambda p: p["file"])})


def _letter_file(letter: str) -> str:
    return "other" if letter == "!*" else letter


def fetch_index(cache: Cache, vocab: str) -> list[dict]:
    """Every ``/index/<letter>`` page of a vocabulary, concatenated: non-deprecated concepts, English."""
    entries = []
    for letter in INDEX_LETTERS:
        raw = cache.get(f"{vocab}/index_{_letter_file(letter)}.json", f"{VOCABS[vocab]}/{vocab}/index/{letter}",
                        {"lang": "en"}, allow_404=True)
        if raw:
            entries += json.loads(raw).get("indexConcepts", [])
    return entries


def fetch_stats(cache: Cache, vocab: str) -> dict:
    raw = cache.get(f"{vocab}/vocabularyStatistics.json", f"{VOCABS[vocab]}/{vocab}/vocabularyStatistics", {"lang": "en"})
    stats = json.loads(raw)
    return {"concepts": stats["concepts"]["count"], "deprecated": stats["concepts"]["deprecatedCount"]}


def concept_url(vocab: str, uri: str) -> tuple[str, dict]:
    return f"{VOCABS[vocab]}/{vocab}/data", {"uri": uri, "format": "application/ld+json"}


def concept_file(vocab: str, uri: str) -> str:
    return f"{vocab}/concept_{_sha16(uri)}.json"


def fetch_concept(cache: Cache, vocab: str, uri: str) -> dict | None:
    url, params = concept_url(vocab, uri)
    raw = cache.get(concept_file(vocab, uri), url, params, allow_404=True)
    return json.loads(raw) if raw else None


def fetch_top_concepts(cache: Cache, vocab: str) -> list[dict]:
    raw = cache.get(f"{vocab}/topConcepts.json", f"{VOCABS[vocab]}/{vocab}/topConcepts", {"lang": "en"})
    return [{"uri": c["uri"], "label": c.get("label", "")} for c in json.loads(raw).get("topconcepts", [])]


def fetch_children(cache: Cache, vocab: str, uri: str) -> list[dict]:
    raw = cache.get(f"{vocab}/children_{_sha16(uri)}.json", f"{VOCABS[vocab]}/{vocab}/children", {"uri": uri, "lang": "en"}, allow_404=True)
    return [{"uri": c["uri"], "label": c.get("prefLabel", "")} for c in json.loads(raw).get("narrower", [])] if raw else []


def nerc_file(uri: str) -> str:
    return f"nerc/concept_{_sha16(uri)}.json"


def fetch_nerc(cache: Cache, uri: str) -> dict | None:
    raw = cache.get(nerc_file(uri), uri, {"_profile": "nvs", "_mediatype": "application/ld+json"}, allow_404=True)
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------

def _as_list(value) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


def _en(values) -> list[str]:
    return [v["value"] for v in _as_list(values) if isinstance(v, dict) and v.get("lang") == "en" and v.get("value")]


def concept_facts(payload: dict, uri: str) -> dict | None:
    """Facts of one Skosmos JSON-LD concept; ``None`` when the response has no node for ``uri``."""
    nodes = {g["uri"]: g for g in payload.get("graph", []) if isinstance(g, dict) and "uri" in g}
    node = nodes.get(uri)
    if node is None:
        return None
    broader = []
    for b in _as_list(node.get("broader")):
        label = (_en((nodes.get(b["uri"]) or {}).get("prefLabel")) or [""])[0]
        broader.append(f"{label} ({b['uri']})" if label else b["uri"])
    return {
        "pref": (_en(node.get("prefLabel")) or [""])[0], "alt": _en(node.get("altLabel")),
        "definition": (_en(node.get("skos:definition")) or [""])[0], "broader": broader,
        "deprecated": node.get("owl:deprecated") is True,
        "replaced_by": (node.get("dct:isReplacedBy") or {}).get("uri", ""),
        "exact": [m["uri"] for m in _as_list(node.get("exactMatch")) if isinstance(m, dict) and "uri" in m],
    }


def nerc_facts(payload: dict) -> dict:
    """Facts of one NERC Vocabulary Server concept (flat JSON-LD, ``@id`` / ``@value`` keys)."""
    def text(key):
        return next((v["@value"] for v in _as_list(payload.get(key)) if isinstance(v, dict) and v.get("@language") == "en"), "")
    return {
        "pref": text("skos:prefLabel"), "alt": [], "definition": text("skos:definition"),
        "broader": [b["@id"] for b in _as_list(payload.get("skos:broader"))],
        "deprecated": str(payload.get("owl:deprecated")).lower() == "true", "replaced_by": "",
        "exact": [s["@id"] for s in _as_list(payload.get("owl:sameAs"))],
    }


def build_label_index(entries: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    """``{lowercase label: [(uri, concept prefLabel, "prefLabel" | "altLabel")]}`` from index entries."""
    index: dict[str, list] = defaultdict(list)
    for e in entries:
        alt = e.get("altLabel")
        label, kind = (alt, "altLabel") if alt else (e["prefLabel"], "prefLabel")
        hit = (e["uri"], e["prefLabel"], kind)
        if hit not in index[label.strip().lower()]:
            index[label.strip().lower()].append(hit)
    return dict(index)


# ---------------------------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------------------------

def plan_lookups(terms: pd.DataFrame, label_index: dict[str, dict]) -> list[dict]:
    """Every lookup to report, as dicts without facts: pure, no network."""
    plan = []
    for t in terms.itertuples():
        base = {"ri": t.ri, "term_label": t.term_label, "term_uri": t.term_uri}
        if t.ri == "eLTER" and t.term_uri:
            plan.append({**base, "lookup": "uri_resolves", "vocab": "EnvThes", "uri": t.term_uri, "kind": ""})
        for uri in filter(None, (u.strip() for u in t.published_match_uri.split(";"))):
            if uri.startswith(NERC_P07.replace("http://", "https://")) or uri.startswith(NERC_P07):
                plan.append({**base, "lookup": "published_match_uri", "vocab": "NERC_P07", "uri": uri, "kind": ""})
        for vocab in CROSS_VOCABS + OWN_VOCABS.get(t.ri, []):
            for uri, _pref, kind in label_index[vocab].get(t.term_label.strip().lower(), []):
                if uri != t.term_uri:
                    plan.append({**base, "lookup": f"label_equals_{kind}", "vocab": vocab, "uri": uri, "kind": kind})
    return plan


def _label_match(label: str, facts: dict) -> str:
    label = label.strip().lower()
    if label == facts["pref"].strip().lower():
        return "prefLabel"
    return "altLabel" if label in {a.strip().lower() for a in facts["alt"]} else "neither"


def assemble(plan: list[dict], facts: dict[tuple, dict | None], fetched_at: dict[tuple, str]) -> pd.DataFrame:
    rows = []
    for p in plan:
        key = (p["vocab"], p["uri"])
        f = facts.get(key)
        rows.append({
            "ri": p["ri"], "term_label": p["term_label"], "term_uri": p["term_uri"], "lookup": p["lookup"],
            "published_label_matches": _label_match(p["term_label"], f) if f and p["lookup"] == "uri_resolves" else "",
            "reference_vocabulary": p["vocab"], "reference_uri": p["uri"],
            "reference_pref_label": f["pref"] if f else "", "reference_alt_labels": "; ".join(f["alt"]) if f else "",
            "reference_definition": f["definition"] if f else "", "reference_broader": "; ".join(f["broader"]) if f else "",
            "reference_deprecated": ("true" if f["deprecated"] else "false") if f else "",
            "reference_replaced_by": f["replaced_by"] if f else "",
            "reference_exact_match_uris": "; ".join(f["exact"]) if f else "",
            "status": "found" if f else "not_found", "source_url": _source_url(p["vocab"], p["uri"]),
            "fetched_at": fetched_at.get(key, ""),
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.sort_values(["ri", "term_label", "term_uri", "lookup", "reference_vocabulary", "reference_uri"], kind="stable").reset_index(drop=True)


def _source_url(vocab: str, uri: str) -> str:
    if vocab == "NERC_P07":
        return uri
    url, params = concept_url(vocab, uri)
    return f"{url}?uri={quote(uri, safe='')}&format=application%2Fld%2Bjson"


def coverage(terms: pd.DataFrame, table: pd.DataFrame) -> dict:
    """Per RI: how many terms have at least one reference row, overall and per lookup/vocabulary."""
    out = {}
    for ri, g in terms.groupby("ri"):
        mine = table[table.ri == ri]
        labels = mine[mine.lookup.str.startswith("label_equals")]
        row = {"terms": int(len(g)), "terms_with_any_hit": _terms_with_rows(g, mine)}
        for vocab in CROSS_VOCABS + OWN_VOCABS.get(ri, []):
            row[f"terms_with_label_hit_in_{vocab}"] = _terms_with_rows(g, labels[labels.reference_vocabulary == vocab])
        out[ri] = row
    return out


def _terms_with_rows(terms: pd.DataFrame, rows: pd.DataFrame) -> int:
    keys = set(zip(rows.term_label, rows.term_uri))
    return int(sum(key in keys for key in zip(terms.term_label, terms.term_uri)))


def scope_inventory(entries: list[dict]) -> dict:
    """Concepts of a vocabulary whose English prefLabel matches the dictionary_terms scope rules."""
    labels = {}
    for e in entries:
        if not e.get("altLabel"):
            labels[e["uri"]] = e["prefLabel"]
    by_domain: dict[str, list[str]] = defaultdict(list)
    for label in labels.values():
        domain, _ = dt.scope_candidate(label)
        if domain:
            by_domain[domain].append(label)
    return {"concepts_in_index": len(labels), **{d: len(v) for d, v in sorted(by_domain.items())},
            "labels": {d: sorted(v) for d, v in sorted(by_domain.items())}}


def structure_inventory(cache: Cache) -> dict:
    """What the two eLTER thesauri that are not EnvThes are made of, in their own structure.

    ``so``: its five top concepts are spheres; the children of each are listed. ``elter_cl``: the
    names of its top-level lists, and the entries of the one list called "INSPIRE data theme".
    """
    so = {sphere["label"]: [c["label"] for c in fetch_children(cache, "so", sphere["uri"])]
          for sphere in fetch_top_concepts(cache, "so")}
    lists = fetch_top_concepts(cache, "elter_cl")
    inspire = next((t for t in lists if t["label"] == "INSPIRE data theme"), None)
    return {"so_concepts_by_sphere": {k: {"count": len(v), "labels": v} for k, v in so.items()},
            "elter_cl_top_level_lists": [t["label"] for t in lists],
            "elter_cl_inspire_data_themes": [c["label"] for c in fetch_children(cache, "elter_cl", inspire["uri"])] if inspire else []}


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

def _git_revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fetch", action="store_true", help="fetch what the cache lacks (default: cache only)")
    parser.add_argument("--terms", default=str(TERMS_CSV))
    parser.add_argument("--out-dir", default=str(OUT))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    terms = pd.read_csv(args.terms, dtype=str, keep_default_na=False)
    cache = Cache(RAW, offline=not args.fetch)
    entries = {v: fetch_index(cache, v) for v in VOCABS}
    stats = {v: fetch_stats(cache, v) for v in VOCABS}
    label_index = {v: build_label_index(e) for v, e in entries.items()}

    plan = plan_lookups(terms, label_index)
    facts, fetched_at = {}, {}
    for vocab, uri in sorted({(p["vocab"], p["uri"]) for p in plan}):
        if vocab == "NERC_P07":
            payload = fetch_nerc(cache, uri)
            facts[(vocab, uri)] = nerc_facts(payload) if payload else None
            fetched_at[(vocab, uri)] = cache.retrieved_at(nerc_file(uri))
        else:
            payload = fetch_concept(cache, vocab, uri)
            facts[(vocab, uri)] = concept_facts(payload, uri) if payload else None
            fetched_at[(vocab, uri)] = cache.retrieved_at(concept_file(vocab, uri))
    structure = structure_inventory(cache)
    cache.write_manifest()

    table = assemble(plan, facts, fetched_at)
    table.to_csv(out_dir / "dictionary_reference_finland.csv", index=False)

    resolves = table[table.lookup == "uri_resolves"]
    deims_terms = terms[terms.ri == "eLTER"]
    run = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "git_revision": _git_revision(),
        "input": str(Path(args.terms).name), "input_rows": int(len(terms)), "reference_rows": int(len(table)),
        "vocabulary_statistics": stats,
        "vocabulary_index_distinct_concepts": {v: len({e["uri"] for e in entries[v]}) for v in VOCABS},
        "deims_uri_resolution": {
            "terms_with_uri": int((deims_terms.term_uri != "").sum()), "found": int((resolves.status == "found").sum()),
            "not_found": int((resolves.status == "not_found").sum()),
            "deprecated": int((resolves.reference_deprecated == "true").sum()),
            "published_label_matches": {k: int(v) for k, v in resolves.published_label_matches.value_counts().items()}},
        "icos_published_matches": {"rows": int((table.lookup == "published_match_uri").sum()),
                                   "distinct_uris": sorted(set(table[table.lookup == "published_match_uri"].reference_uri))},
        "per_ri": coverage(terms, table),
        "scope_rule_hits_in_reference_vocabularies": {v: scope_inventory(entries[v]) for v in VOCABS},
        "reference_structure": structure,
        "not_found_urls": cache.not_found,
        "sources": {"pages": len(cache.pages)},
    }
    (out_dir / "dictionary_reference_finland_run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("vocabulary_statistics", "deims_uri_resolution", "icos_published_matches", "per_ri")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
