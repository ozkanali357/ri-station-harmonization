"""Adapters that pull station metadata from each research infrastructure.

Every adapter follows the same contract:

    fetch_*(cache_dir, offline) -> pandas.DataFrame with schema.COLUMNS

Raw responses are written to ``data/raw`` verbatim and re-used when
``offline=True``, so a run is reproducible without network access and the
provenance of every row can be traced back to an unedited response.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import requests

from .schema import COLUMNS, normalise_name

log = logging.getLogger(__name__)

ICOS_SPARQL = "https://meta.icos-cp.eu/sparql"
DEIMS_SITES = "https://deims.org/api/sites"
DEIMS_SITE = "https://deims.org/api/sites/{uuid}"
ACTRIS_FACILITIES = "https://prod-actris-md.nilu.no/facilities"

TIMEOUT = 120
UA = {"User-Agent": "ri-station-harmonization/0.1 (MSc thesis pilot; contact via GitHub)"}

# Property names below are taken from the published ICOS ontology at
# http://meta.icos-cp.eu/ontologies/cpmeta/ .  Note hasWigosId has domain :AS,
# i.e. it exists only for atmospheric stations - one of the asymmetries this
# project is about.
ICOS_QUERY = """
prefix cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
select ?uri ?stationId ?name ?lat ?lon ?elevation ?country ?wigos ?klass
where {
  ?uri a ?klassUri .
  ?klassUri rdfs:subClassOf* cpmeta:Station ; rdfs:label ?klass .
  ?uri cpmeta:hasStationId ?stationId ; cpmeta:hasName ?name .
  optional { ?uri cpmeta:hasLatitude ?lat }
  optional { ?uri cpmeta:hasLongitude ?lon }
  optional { ?uri cpmeta:hasElevation ?elevation }
  optional { ?uri cpmeta:countryCode ?country }
  optional { ?uri cpmeta:hasWigosId ?wigos }
}
"""


def _cache(cache_dir: Path, filename: str, loader, offline: bool):
    """Return parsed JSON from cache, fetching it once if absent."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / filename
    if path.exists():
        log.info("using cached %s", path.name)
        return json.loads(path.read_text(encoding="utf-8"))
    if offline:
        raise FileNotFoundError(
            f"{path} is missing and --offline was requested. "
            "Run once with network access to populate data/raw/."
        )
    log.info("fetching %s", filename)
    payload = loader()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def fetch_icos(cache_dir: Path, offline: bool = False) -> pd.DataFrame:
    """ICOS stations via the Carbon Portal SPARQL endpoint."""

    def _load():
        resp = requests.post(
            ICOS_SPARQL,
            data={"query": ICOS_QUERY},
            headers={"Accept": "application/sparql-results+json", **UA},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    payload = _cache(cache_dir, "icos_stations.json", _load, offline)
    rows = []
    for binding in payload.get("results", {}).get("bindings", []):
        get = lambda k: binding.get(k, {}).get("value")  # noqa: E731
        extra = {}
        if get("wigos"):
            extra["wigos_id"] = get("wigos")
        rows.append(
            {
                "ri": "ICOS",
                "source_id": get("stationId"),
                "id_scheme": "ICOS station code",
                "uri": get("uri"),
                "name": get("name"),
                "lat": get("lat"),
                "lon": get("lon"),
                "elevation_m": get("elevation"),
                "country": (get("country") or "").upper(),
                "geometry_kind": "point",
                "station_class": get("klass") or "",
                "extra_ids": json.dumps(extra),
            }
        )
    return _finalise(rows)


def fetch_deims(cache_dir: Path, offline: bool = False, max_detail: int = 0) -> pd.DataFrame:
    """eLTER sites via the DEIMS-SDR REST API.

    The list endpoint returns a WKT centroid per site.  Full boundary polygons
    live on the detail records; ``max_detail`` optionally pulls that many of
    them so the polygon-overlap matcher has real geometry to work with.
    """

    def _load():
        resp = requests.get(DEIMS_SITES, headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    payload = _cache(cache_dir, "deims_sites.json", _load, offline)
    rows = []
    for site in payload:
        ident = site.get("id") or {}
        suffix = ident.get("suffix") or ""
        prefix = ident.get("prefix") or "https://deims.org/"
        lat, lon = _parse_wkt_point(site.get("coordinates"))
        rows.append(
            {
                "ri": "eLTER",
                "source_id": suffix,
                "id_scheme": "DEIMS-SDR UUID",
                "uri": f"{prefix}{suffix}" if suffix else "",
                "name": site.get("title"),
                "lat": lat,
                "lon": lon,
                "elevation_m": None,
                "country": "",
                "geometry_kind": "centroid_of_polygon",
                "station_class": "eLTER site",
                "extra_ids": json.dumps({}),
            }
        )
    return _finalise(rows)


def fetch_actris(cache_dir: Path, offline: bool = False) -> pd.DataFrame:
    """ACTRIS national facilities.

    Best effort: the ACTRIS metadata service is less stable than the other two
    and its response shape has changed between releases, so a failure here
    downgrades to an empty frame with a warning rather than killing the run.
    The two-RI comparison is still valid; the summary records which RIs were
    actually loaded.
    """

    def _load():
        resp = requests.get(ACTRIS_FACILITIES, headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    try:
        payload = _cache(cache_dir, "actris_facilities.json", _load, offline)
    except Exception as exc:  # noqa: BLE001 - deliberate: optional source
        log.warning("ACTRIS source unavailable (%s); continuing with ICOS + eLTER", exc)
        return _empty()

    if isinstance(payload, dict):
        payload = payload.get("results") or payload.get("facilities") or []

    rows = []
    for fac in payload:
        if not isinstance(fac, dict):
            continue
        ident = fac.get("identifier") or fac.get("id") or fac.get("actris_id")
        lat = _dig(fac, ["lat", "latitude"]) or _dig(fac.get("location") or {}, ["lat", "latitude"])
        lon = _dig(fac, ["lon", "lng", "longitude"]) or _dig(fac.get("location") or {}, ["lon", "lng", "longitude"])
        rows.append(
            {
                "ri": "ACTRIS",
                "source_id": str(ident) if ident is not None else "",
                "id_scheme": "ACTRIS facility identifier",
                "uri": fac.get("landing_page") or fac.get("url") or "",
                "name": fac.get("name") or fac.get("title"),
                "lat": lat,
                "lon": lon,
                "elevation_m": _dig(fac, ["altitude", "elevation"]),
                "country": str(_dig(fac, ["country_code", "country"]) or "").upper()[:2],
                "geometry_kind": "point",
                "station_class": "ACTRIS national facility",
                "extra_ids": json.dumps({}),
            }
        )
    return _finalise(rows)


def _dig(obj: dict, keys):
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def _parse_wkt_point(wkt: str | None):
    """DEIMS returns 'POINT (lon lat)'.  Longitude first - easy to get wrong."""
    if not wkt or "(" not in wkt:
        return None, None
    try:
        inner = wkt[wkt.index("(") + 1: wkt.rindex(")")]
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
    df = df.dropna(subset=["lat", "lon"])
    df = df[(df.lat.between(-90, 90)) & (df.lon.between(-180, 180))]
    df = df.drop_duplicates(subset=["ri", "source_id"])
    return df.reset_index(drop=True)
