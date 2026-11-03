"""Extract the field definitions of the DEIMS-SDR Site Metadata Model (SMM).

The page https://deims.org/models/?id=site is a thin HTML viewer: it contains no field text. Its script
loads the model from ``MODEL_URL`` (a JSON file on GitHub) and renders it. This script therefore caches
three responses byte for byte:

* the viewer page (``PAGE_URL``) - what Ali opened;
* the model JSON (``MODEL_URL``) - where every definition text comes from;
* the DEIMS terms of use (``TERMS_URL``) - checked before the text is committed.

Per field the model gives ``Definition``, ``Recommendation & Hints``, ``Format``, ``Multiplicity`` and
``Example`` (and further keys that are not extracted: ``Required``, ``Dependency``, ``Reference list``,
``Comment``). They are copied verbatim into separate columns; nothing is paraphrased, shortened or filled
in. A field whose ``Definition`` is empty stays flagged.

Contact and person fields are excluded as everywhere else in this repo: the whole ``Contact`` group of the
model is dropped (its examples contain a person's name), and so is any entry whose group, label or machine
name contains "contact". The script stops with an error if any extracted text contains an e-mail address.

Nothing that holds the model's text is committed. Raw responses go to ``data/raw/deims_model/`` and the
extracted ``outputs/deims_model_definitions.csv`` is git-ignored: the DEIMS terms of use say CC BY-NC 4.0
and also forbid scraping to re-publish content, so the text is produced locally by this script. What is
committed: ``outputs/deims_model_definitions_run.json`` (URL, retrieval time, HTTP status, size and SHA-256
of each response and of the CSV) and ``outputs/deims_model_field_list.csv`` (field paths and machine names
only, no text).

A run with a run file already on record **verifies** instead of re-recording: a freshly fetched or cached
``smm.json`` whose SHA-256 differs from the record, or an extracted CSV whose SHA-256 differs from the
record, stops the run with exit status 1 and writes nothing. ``--update-record`` re-records after the change
has been looked at.

Usage (from the repo root)::

    python scripts/deims_model_definitions.py            # use the cache, fetch what is missing
    python scripts/deims_model_definitions.py --offline  # cache only, never touch the network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

PAGE_URL = "https://deims.org/models/?id=site"
MODEL_URL = "https://raw.githubusercontent.com/stopopol/deims_apps/master/metadata_models/smm.json"
TERMS_URL = "https://deims.org/terms"

RAW_DIR = ROOT / "data" / "raw" / "deims_model"
OUT_CSV = ROOT / "outputs" / "deims_model_definitions.csv"  # git-ignored: holds the model's text
OUT_FIELD_LIST = ROOT / "outputs" / "deims_model_field_list.csv"  # committed: no text
OUT_RUN = ROOT / "outputs" / "deims_model_definitions_run.json"

# file name -> (url, directory the raw bytes are kept in)
SOURCES = {
    "page.html": (PAGE_URL, RAW_DIR),
    "smm.json": (MODEL_URL, RAW_DIR),
    "terms.html": (TERMS_URL, RAW_DIR),
}
VERIFIED_STRICTLY = "smm.json"  # the text itself; the viewer and terms pages may change without a text change
FIELD_LIST_COLUMNS = ["page_group", "page_path", "page_label", "page_field_name", "definition_published"]

FLAG_TEXT = "FLAGGED: No definition published on the DEIMS-SDR Site Metadata Model"
LICENCE_SENTENCE = ("This work is licensed under a Creative Commons Attribution-Non Commercial 4.0 "
                    "International License (CC BY-NC 4.0 International)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OUTPUT_COLUMNS = ["page_group", "page_path", "page_label", "page_field_name", "definition", "recommendation",
                  "format", "multiplicity", "example", "definition_published", "model_version",
                  "model_release_date"]
USER_AGENT = "ri-station-harmonization (thesis research; public metadata model, 3 requests)"


# --- fetching and caching ------------------------------------------------------------------------

class ChecksumMismatch(SystemExit):
    """Raised (as an exit with status 1 and a message) when fetched or cached bytes differ from the record."""

    def __init__(self, message: str):
        super().__init__(f"CHECKSUM MISMATCH: {message}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def cache_path(name: str) -> Path:
    return SOURCES[name][1] / name


def fetch_to_cache(name: str, session=None, expected_sha256: str | None = None) -> dict:
    """GET one source, write the bytes unchanged, return the manifest entry.

    With ``expected_sha256`` a different response is not written and the run stops.
    """
    import requests

    url, directory = SOURCES[name]
    directory.mkdir(parents=True, exist_ok=True)
    response = (session or requests).get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    if expected_sha256 and sha256_bytes(response.content) != expected_sha256:
        raise ChecksumMismatch(f"{url} now has SHA-256 {sha256_bytes(response.content)}, the record has "
                               f"{expected_sha256}. The model text changed upstream or the response differs; "
                               "nothing was written. Look at the change, then re-run with --update-record.")
    cache_path(name).write_bytes(response.content)
    return {
        "file": _rel(cache_path(name)),
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "http_status": response.status_code,
        "bytes": len(response.content),
        "sha256": sha256_bytes(response.content),
        "last_modified_header": response.headers.get("Last-Modified"),
        "etag_header": response.headers.get("ETag"),
    }


def cached_entry(name: str, previous: dict | None) -> dict:
    """Manifest entry for a cached file whose fetch time is already on record."""
    data = cache_path(name).read_bytes()
    entry = dict(previous or {})
    if entry.get("sha256") not in (None, sha256_bytes(data)):
        raise ChecksumMismatch(f"{cache_path(name)} no longer matches the SHA-256 in {OUT_RUN.name}; "
                               "delete it and fetch again, or restore the original file")
    entry.update({"file": _rel(cache_path(name)), "url": SOURCES[name][0],
                  "bytes": len(data), "sha256": sha256_bytes(data)})
    return entry


# --- parsing -------------------------------------------------------------------------------------

def _text(value) -> str:
    """The value as text, unchanged for strings; other JSON values keep their JSON form."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def iter_model_fields(content: dict, path: tuple[str, ...] = ()):
    """Yield ``(path, entry)`` for every entry that carries a ``field_name`` string, depth first."""
    for key, value in content.items():
        if not isinstance(value, dict):
            continue
        if isinstance(value.get("field_name"), str):
            yield path + (key,), value
        else:
            yield from iter_model_fields(value, path + (key,))


def is_contact_entry(path: tuple[str, ...], entry: dict) -> bool:
    haystack = " ".join(list(path) + [str(entry.get("field_name", ""))]).lower()
    return "contact" in haystack


def extract_rows(model: dict) -> tuple[list[dict], list[dict]]:
    """Return ``(rows, excluded)``; ``excluded`` lists the dropped contact entries by path only."""
    rows, excluded = [], []
    for path, entry in iter_model_fields(model["content"]):
        if is_contact_entry(path, entry):
            excluded.append({"page_path": "/".join(path), "page_field_name": entry["field_name"].strip()})
            continue
        definition = _text(entry.get("Definition"))
        published = bool(definition.strip())
        rows.append({
            "page_group": path[0],
            "page_path": "/".join(path),
            "page_label": path[-1],
            "page_field_name": entry["field_name"].strip(),
            "definition": definition if published else FLAG_TEXT,
            "recommendation": _text(entry.get("Recommendation & Hints")),
            "format": _text(entry.get("Format")),
            "multiplicity": _text(entry.get("Multiplicity")),
            "example": _text(entry.get("Example")),
            "definition_published": "yes" if published else "no",
            "model_version": _text(model.get("version")),
            "model_release_date": _text(model.get("releaseDate")),
        })
    return rows, excluded


def check_no_emails(rows: list[dict]) -> None:
    for row in rows:
        for column, value in row.items():
            if isinstance(value, str) and EMAIL_RE.search(value):
                raise SystemExit(f"e-mail address found in {row['page_path']!r} column {column!r}; "
                                 "nothing was written")


def check_unique(rows: list[dict]) -> None:
    for column in ("page_path", "page_field_name"):
        seen: dict[str, str] = {}
        for row in rows:
            if row[column] in seen:
                raise SystemExit(f"duplicate {column} {row[column]!r}: {seen[row[column]]} and {row['page_path']}")
            seen[row[column]] = row["page_path"]


def licence_found(terms_html: str) -> bool:
    """Whether the terms page still contains the licence sentence (whitespace and tags ignored)."""
    text = re.sub(r"<[^>]+>", " ", terms_html)
    text = re.sub(r"\s+", " ", text)
    return LICENCE_SENTENCE in text


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_field_list(frame: pd.DataFrame, path: Path = OUT_FIELD_LIST) -> None:
    """Field paths and machine names only (no definition, recommendation or example text)."""
    frame[FIELD_LIST_COLUMNS].to_csv(path, index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract the DEIMS-SDR Site Metadata Model definitions.")
    parser.add_argument("--offline", action="store_true", help="use the cache only; never touch the network")
    parser.add_argument("--update-record", action="store_true",
                        help="write the run file again although it records different checksums (look at the "
                             "change first); also needed for the very first run")
    args = parser.parse_args(argv)

    recorded_run = json.loads(OUT_RUN.read_text(encoding="utf-8")) if OUT_RUN.exists() else None
    previous = (recorded_run or {}).get("responses", {})
    verify_only = recorded_run is not None and not args.update_record

    responses, fetch_log = {}, {}
    for name in SOURCES:
        if cache_path(name).exists():
            responses[name] = cached_entry(name, previous.get(name))
        elif args.offline:
            print(f"--offline but {cache_path(name)} is missing", file=sys.stderr)
            return 2
        else:
            strict = previous.get(name, {}).get("sha256") if name == VERIFIED_STRICTLY and not args.update_record else None
            responses[name] = fetch_log[name] = fetch_to_cache(name, expected_sha256=strict)
            print(f"fetched {SOURCES[name][0]} -> {cache_path(name).relative_to(ROOT)}")
            if previous.get(name, {}).get("sha256") not in (None, responses[name]["sha256"]):
                print(f"warning: {name} differs from the recorded SHA-256 (not the model text; "
                      "check the terms page again if it is terms.html)", file=sys.stderr)
    if fetch_log:
        (RAW_DIR / "fetch_log.json").write_text(json.dumps(fetch_log, indent=2) + "\n", encoding="utf-8")

    model = json.loads(cache_path("smm.json").read_bytes().decode("utf-8"))
    rows, excluded = extract_rows(model)
    check_no_emails(rows)
    check_unique(rows)

    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    recorded_output = (recorded_run or {}).get("output", {}).get("sha256")
    frame.to_csv(OUT_CSV, index=False)
    output_sha = sha256_bytes(OUT_CSV.read_bytes())
    if verify_only and recorded_output and output_sha != recorded_output:
        OUT_CSV.unlink()
        raise ChecksumMismatch(f"the extracted CSV has SHA-256 {output_sha}, the record has {recorded_output}; "
                               "the CSV was removed. Re-run with --update-record after looking at the change.")
    write_field_list(frame)

    terms = cache_path("terms.html").read_bytes().decode("utf-8", errors="replace")
    if not licence_found(terms):
        print("warning: the licence sentence was not found on the terms page; read it again before using "
              "the text", file=sys.stderr)
    if verify_only:
        print(f"verified against {OUT_RUN.relative_to(ROOT)}: smm.json and the CSV match the record; "
              f"{len(frame)} fields -> {OUT_CSV.relative_to(ROOT)} (git-ignored)")
        return 0

    run = {
        "script": "scripts/deims_model_definitions.py",
        "git_head_at_run": _git_head(),
        "model": {"name": model.get("name"), "abbreviation": model.get("abbreviation"),
                  "version": model.get("version"), "release_date": model.get("releaseDate")},
        "responses": responses,
        "terms_of_use": {
            "url": TERMS_URL,
            "licence_sentence_present": licence_found(terms),
            "licence_sentence": LICENCE_SENTENCE,
            "note": ("The same page also forbids using 'scraping or similar techniques to collect content to "
                     "use it for another purpose, to publish it again'. This script makes three single "
                     "requests (viewer page, model JSON, terms page) and does not crawl the site. Because "
                     "the page does not settle whether publishing the text is covered, the text, the raw "
                     "responses and the files built from them are not committed; they are produced locally."),
        },
        "counts": {
            "entries_in_model": len(rows) + len(excluded),
            "excluded_contact": len(excluded),
            "extracted": len(rows),
            "with_definition": int((frame["definition_published"] == "yes").sum()),
            "without_definition": int((frame["definition_published"] == "no").sum()),
        },
        "excluded_contact_entries": excluded,
        "not_extracted_keys": ["Required", "Dependency", "Reference list", "Comment"],
        "output": {"file": str(OUT_CSV.relative_to(ROOT)), "sha256": output_sha, "committed": False},
        "field_list": {"file": str(OUT_FIELD_LIST.relative_to(ROOT)), "sha256": sha256_bytes(OUT_FIELD_LIST.read_bytes())},
    }
    OUT_RUN.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{run['counts']} -> {OUT_CSV.relative_to(ROOT)}, {OUT_RUN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
