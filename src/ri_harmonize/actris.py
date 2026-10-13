"""Adapter for the ACTRIS Metadata (DVAS) facilities API.

Endpoint: ``GET https://prod-actris-md.nilu.no/api/facilities`` (public, no key;
the host root redirects to the Swagger UI, whose OpenAPI spec is at ``/v3/api-docs``).

The response is cached byte-for-byte; the checksum recorded in the cache manifest
is the SHA-256 of those bytes. ACTRIS facility records are mapped into the
canonical schema without rewriting identifiers:

* ``record_id`` and ``source_id``: the API ``identifier`` (e.g. ``ko6m``), verbatim.
* ``id_scheme``: ``ACTRIS DVAS facility identifier``. The API itself labels the
  identifier type as ``other PID``; that label is kept in ``extra_ids``.
* ``uri``: the API ``uri`` field when present, otherwise empty (never constructed).
* ``lat`` / ``lon`` / ``elevation_m``: the GeoJSON ``location.coordinates``
  ``[lon, lat, (elevation)]``. Records without a location are dropped by the
  common coordinate validation, not given coordinates from other fields.
* ``extra_ids``: secondary identifiers (EBAS station code, GAW id, national
  facility URI) plus the status fields ``active`` and ``actris_national_facility``.
  The canonical schema has no status column, so these travel here instead of
  being discarded; the list contains inactive and unlabelled facilities.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd
import requests

from .sources import TIMEOUT, UA, _finalise, _now, _write_manifest

log = logging.getLogger(__name__)
ACTRIS_FACILITIES = "https://prod-actris-md.nilu.no/api/facilities"
ACTRIS_CACHE_FILE = "actris_facilities.json"


def fetch_actris(cache_dir: Path, offline: bool = False) -> pd.DataFrame:
    """Fetch ACTRIS facilities, caching the raw response verbatim."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / ACTRIS_CACHE_FILE
    if path.exists():
        raw = path.read_bytes()
    elif offline:
        raise FileNotFoundError(f"{path} is missing and --offline was requested.")
    else:
        log.info("fetching ACTRIS facilities from %s", ACTRIS_FACILITIES)
        response = requests.get(ACTRIS_FACILITIES, headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
        response.raise_for_status()
        raw = response.content
        if not isinstance(json.loads(raw), list):
            raise ValueError("ACTRIS facilities response must be a JSON list")
        path.write_bytes(raw)
        _write_manifest(cache_dir, "actris", {
            "endpoint": ACTRIS_FACILITIES, "retrieved_at": _now(), "complete": True,
            "checksum_of": "raw response bytes",
            "pages": [{"file": ACTRIS_CACHE_FILE, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}],
        })

    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("ACTRIS facilities response must be a JSON list")
    return _finalise([row for row in map(_facility_row, payload) if row])


def _facility_row(facility) -> dict | None:
    if not isinstance(facility, dict):
        return None
    ident = str(facility.get("identifier") or "").strip()
    coords = (facility.get("location") or {}).get("coordinates") or []
    lon, lat = (coords[0], coords[1]) if len(coords) >= 2 else (None, None)
    elevation = coords[2] if len(coords) >= 3 else None
    insitu = (facility.get("extra_metadata") or {}).get("insitu") or {}
    extra = {
        "identifier_type": facility.get("identifier_type"),
        "ebas_station_code": insitu.get("ebas_station_code"),
        "ebas_station_lat": insitu.get("ebas_station_lat"),
        "ebas_station_lon": insitu.get("ebas_station_lon"),
        "gawid_uri": facility.get("gawid_uri"),
        "actris_nf_uri": facility.get("actris_nf_uri"),
        "active": facility.get("active"),
        "actris_national_facility": facility.get("actris_national_facility"),
    }
    return {
        "ri": "ACTRIS", "record_id": ident, "source_id": ident,
        "id_scheme": "ACTRIS DVAS facility identifier", "uri": facility.get("uri") or "",
        "name": facility.get("name") or "", "lat": lat, "lon": lon, "elevation_m": elevation,
        "country": (facility.get("country_code") or "").upper(), "geometry_kind": "point",
        "station_class": "; ".join(facility.get("facility_type") or []),
        "extra_ids": json.dumps({k: v for k, v in extra.items() if v is not None}),
    }
