"""Adapters for the ICOS and eLTER station registries.

Raw responses are cached verbatim. The generated manifest records endpoint,
query text, retrieval time, and checksums for a reproducible run.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path

import pandas as pd
import requests

from .schema import COLUMNS, normalise_name

log = logging.getLogger(__name__)
ICOS_SPARQL = "https://meta.icos-cp.eu/sparql"
DEIMS_SITES = "https://deims.org/api/sites"
TIMEOUT = 120
ICOS_PAGE_SIZE = 500
UA = {"User-Agent": "ri-station-harmonization/0.1 (MSc thesis pilot; contact via GitHub)"}

# Do not use rdfs:subClassOf* here: it timed out on the live endpoint.
ICOS_QUERY = """
prefix cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
select ?uri ?stationId ?name ?lat ?lon ?elevation ?country ?wigos
where {{
  ?uri cpmeta:hasStationId ?stationId .
  optional {{ ?uri cpmeta:hasName ?name }}
  optional {{ ?uri cpmeta:hasLatitude ?lat }}
  optional {{ ?uri cpmeta:hasLongitude ?lon }}
  optional {{ ?uri cpmeta:hasElevation ?elevation }}
  optional {{ ?uri cpmeta:countryCode ?country }}
  optional {{ ?uri cpmeta:hasWigosId ?wigos }}
}}
order by str(?uri)
limit {limit}
offset {offset}
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(payload) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "manifest.json"


def _read_manifest(cache_dir: Path) -> dict:
    path = _manifest_path(cache_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sources": {}}


def _write_manifest(cache_dir: Path, source: str, entry: dict) -> None:
    manifest = _read_manifest(cache_dir)
    manifest.setdefault("sources", {})[source] = entry
    _manifest_path(cache_dir).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _cached_json(cache_dir: Path, filename: str, loader, offline: bool, source: str, endpoint: str):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / filename
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if offline:
        raise FileNotFoundError(f"{path} is missing and --offline was requested.")
    payload = loader()
    _write_json(path, payload)
    _write_manifest(cache_dir, source, {
        "endpoint": endpoint, "retrieved_at": _now(), "complete": True,
        "pages": [{"file": filename, "sha256": _sha256(payload)}],
    })
    return payload


def fetch_icos(cache_dir: Path, offline: bool = False) -> pd.DataFrame:
    """Fetch ICOS resources in deterministic, cached SPARQL pages."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    entry = _read_manifest(cache_dir).get("sources", {}).get("icos", {})
    pages = entry.get("pages", []) if entry.get("complete") else []
    if pages:
        payloads = [json.loads((cache_dir / page["file"]).read_text(encoding="utf-8")) for page in pages]
    elif offline:
        raise FileNotFoundError("No complete cached ICOS response is available; run once online first.")
    else:
        payloads, pages = [], []
        for page_no, offset in enumerate(range(0, 1_000_000, ICOS_PAGE_SIZE), start=1):
            query = ICOS_QUERY.format(limit=ICOS_PAGE_SIZE, offset=offset)
            log.info("fetching ICOS page %s (offset %s)", page_no, offset)
            response = requests.post(
                ICOS_SPARQL, data={"query": query},
                headers={"Accept": "application/sparql-results+json", **UA}, timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            filename = f"icos_stations_page_{page_no:04d}.json"
            _write_json(cache_dir / filename, payload)
            payloads.append(payload)
            pages.append({"file": filename, "sha256": _sha256(payload), "query": query})
            if len(payload.get("results", {}).get("bindings", [])) < ICOS_PAGE_SIZE:
                break
        else:  # pragma: no cover
            raise RuntimeError("ICOS pagination exceeded one million rows")
        _write_manifest(cache_dir, "icos", {
            "endpoint": ICOS_SPARQL, "retrieved_at": _now(), "complete": True,
            "page_size": ICOS_PAGE_SIZE, "pages": pages,
        })

    rows = []
    for payload in payloads:
        for binding in payload.get("results", {}).get("bindings", []):
            get = lambda key: binding.get(key, {}).get("value")  # noqa: E731
            uri = get("uri")
            if not uri:
                continue
            extra = {"wigos_id": get("wigos")} if get("wigos") else {}
            rows.append({
                "ri": "ICOS", "record_id": uri, "source_id": get("stationId") or "",
                "id_scheme": "ICOS station code", "uri": uri, "name": get("name") or "",
                "lat": get("lat"), "lon": get("lon"), "elevation_m": get("elevation"),
                "country": (get("country") or "").upper(), "geometry_kind": "point",
                "station_class": "ICOS station resource", "extra_ids": json.dumps(extra),
            })
    return _finalise(rows)


def fetch_deims(cache_dir: Path, offline: bool = False) -> pd.DataFrame:
    """Fetch eLTER site centroids from the documented DEIMS-SDR list API."""
    def load():
        response = requests.get(DEIMS_SITES, headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()

    payload = _cached_json(cache_dir, "deims_sites.json", load, offline, "elter", DEIMS_SITES)
    if not isinstance(payload, list):
        raise ValueError("DEIMS site-list response must be a JSON list")
    rows = []
    for site in payload:
        if not isinstance(site, dict):
            continue
        ident = site.get("id") or {}
        suffix = ident.get("suffix") if isinstance(ident, dict) else str(ident)
        prefix = ident.get("prefix") if isinstance(ident, dict) else "https://deims.org/"
        suffix, prefix = suffix or "", prefix or "https://deims.org/"
        lat, lon = _parse_wkt_point(site.get("coordinates"))
        rows.append({
            "ri": "eLTER", "record_id": suffix, "source_id": suffix,
            "id_scheme": "DEIMS-SDR UUID", "uri": f"{prefix}{suffix}" if suffix else "",
            "name": site.get("title") or "", "lat": lat, "lon": lon, "elevation_m": None,
            "country": "", "geometry_kind": "centroid_of_polygon", "station_class": "eLTER site",
            "extra_ids": json.dumps({}),
        })
    return _finalise(rows)


def _parse_wkt_point(wkt: str | None):
    if not wkt or "(" not in wkt:
        return None, None
    try:
        inner = wkt[wkt.index("(") + 1:wkt.rindex(")")]
        lon_s, lat_s = inner.replace(",", " ").split()[:2]
        return float(lat_s), float(lon_s)
    except (ValueError, IndexError):
        return None, None


def _finalise(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        return df
    for col in ("lat", "lon", "elevation_m"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    df["name_norm"] = df["name"].map(normalise_name)
    df = df[df["record_id"].fillna("").astype(str).str.strip().ne("")]
    df = df.dropna(subset=["lat", "lon"])
    df = df[(df.lat.between(-90, 90)) & (df.lon.between(-180, 180))]
    return df.drop_duplicates(subset=["ri", "record_id"]).reset_index(drop=True)


def validate_stations(df: pd.DataFrame) -> dict:
    """Validation facts written to the run manifest."""
    return {
        "records_with_usable_coordinates": int(len(df)),
        "records_by_infrastructure": {str(k): int(v) for k, v in df.ri.value_counts().items()},
        "duplicate_record_ids": int(df.duplicated(["ri", "record_id"]).sum()) if not df.empty else 0,
        "latitude_range": [float(df.lat.min()), float(df.lat.max())] if not df.empty else None,
        "longitude_range": [float(df.lon.min()), float(df.lon.max())] if not df.empty else None,
    }
