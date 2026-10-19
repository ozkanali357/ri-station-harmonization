"""DEIMS-SDR detail records for the Finnish eLTER sites (opt-in enrichment).

The list call (``GET https://deims.org/api/sites``) returns only a centre point.
The detail call ``GET https://deims.org/api/sites/{uuid}`` adds the site boundary
(WKT polygon), the site type, the country and the network memberships.

Scope rule (chosen 2026-10-19): an eLTER record is a Finnish site when its title
ends in `` - Finland``; the detail record's ``geographic.country`` is then checked
against ``Finland`` and any disagreement is reported, not silently dropped.

Each detail response is cached byte-for-byte in ``<cache>/deims_detail/<uuid>.json``
and the cache manifest records the SHA-256 of those bytes and the retrieval time.
The raw cache is not committed: DEIMS detail records also carry site-manager names
and e-mail addresses (personal data). ``extract_detail`` copies out only the fields
listed above and never reads the ``contact`` block, so nothing derived from it ends
up in the harmonised records, the candidate files or the fixtures.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from .sources import DEIMS_SITES, TIMEOUT, UA, _now, _read_manifest, _write_manifest

log = logging.getLogger(__name__)
DEIMS_SITE = DEIMS_SITES + "/{uuid}"
DETAIL_DIR = "deims_detail"
FINLAND_TITLE_SUFFIX = " - Finland"
FINLAND_COUNTRY = "Finland"
PAUSE_SECONDS = 1.0


def finnish_site_ids(deims: pd.DataFrame) -> list[str]:
    """UUIDs of eLTER list records whose title ends in `` - Finland``."""
    elter = deims[deims.ri == "eLTER"]
    return sorted(elter[elter.name.str.endswith(FINLAND_TITLE_SUFFIX)].record_id.tolist())


def _fetch_one(uuid: str) -> bytes:
    response = requests.get(DEIMS_SITE.format(uuid=uuid), headers={"Accept": "application/json", **UA}, timeout=TIMEOUT)
    response.raise_for_status()
    raw = response.content
    if not isinstance(json.loads(raw), dict):
        raise ValueError(f"DEIMS detail response for {uuid} must be a JSON object")
    return raw


def fetch_details(cache_dir: Path, uuids: list[str], offline: bool = False) -> dict[str, dict]:
    """Fetch (or read from cache) one detail record per UUID; return ``{uuid: payload}``."""
    folder = Path(cache_dir) / DETAIL_DIR
    folder.mkdir(parents=True, exist_ok=True)
    previous = {p["id"]: p for p in _read_manifest(cache_dir).get("sources", {}).get("deims_detail", {}).get("pages", [])}
    pages, payloads, fetched_any = [], {}, False
    for uuid in uuids:
        path = folder / f"{uuid}.json"
        if path.exists():
            raw, retrieved_at = path.read_bytes(), previous.get(uuid, {}).get("retrieved_at")
        elif offline:
            raise FileNotFoundError(f"{path} is missing and --offline was requested.")
        else:
            if fetched_any:
                time.sleep(PAUSE_SECONDS)
            log.info("fetching DEIMS detail %s", uuid)
            raw, retrieved_at, fetched_any = _fetch_one(uuid), _now(), True
            path.write_bytes(raw)
        payloads[uuid] = json.loads(raw)
        pages.append({"id": uuid, "file": f"{DETAIL_DIR}/{uuid}.json", "sha256": hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw), "retrieved_at": retrieved_at})
    _write_manifest(cache_dir, "deims_detail", {
        "endpoint": DEIMS_SITE, "retrieved_at": _now() if fetched_any else None, "complete": True,
        "checksum_of": "raw response bytes", "pages": pages,
    })
    return payloads


def extract_detail(payload: dict) -> dict:
    """The few detail fields the pipeline uses. Never touches ``attributes.contact``."""
    attrs = payload.get("attributes") or {}
    geographic = attrs.get("geographic") or {}
    countries = geographic.get("country") or []
    networks = []
    for entry in (attrs.get("affiliation") or {}).get("networks") or []:
        network = entry.get("network") or {}
        ident = network.get("id") or {}
        networks.append({
            "name": network.get("name"), "id": ident.get("suffix") if isinstance(ident, dict) else ident,
            "siteCode": entry.get("siteCode"), "verified": entry.get("verified"),
        })
    return {
        "site_type": (attrs.get("general") or {}).get("siteType") or None,
        "country": countries[0] if countries else None,
        "boundary_wkt": geographic.get("boundaries") or None,
        "networks": networks,
    }


def enrich_stations(stations: pd.DataFrame, details: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    """Add detail-record facts to the eLTER rows named in ``details``.

    ``geometry_kind`` becomes ``polygon`` where a boundary exists and ``point`` where
    it does not (the centre point is then all there is). ``country`` is set to ``FI``
    only when the detail record says ``Finland``. The boundary WKT, site type, verbatim
    country name and networks travel in ``extra_ids`` (the canonical schema has no
    column for them). Returns the new frame and a scope-check summary.
    """
    out = stations.copy()
    check = {"n_title_suffix": len(details), "n_detail_country_finland": 0, "country_mismatches": [],
             "n_polygon": 0, "n_without_polygon": 0, "without_polygon": []}
    for uuid, payload in details.items():
        rows = out.index[(out.ri == "eLTER") & (out.record_id == uuid)]
        if len(rows) != 1:
            raise KeyError(f"eLTER record {uuid} is not in the station table")
        i = rows[0]
        facts = extract_detail(payload)
        extra = json.loads(out.at[i, "extra_ids"] or "{}")
        extra.update({k: v for k, v in {"deims_site_type": facts["site_type"], "deims_country": facts["country"],
                                        "boundary_wkt": facts["boundary_wkt"]}.items() if v})
        extra["deims_networks"] = facts["networks"]
        out.at[i, "extra_ids"] = json.dumps(extra, ensure_ascii=False)
        if facts["country"] == FINLAND_COUNTRY:
            out.at[i, "country"] = "FI"
            check["n_detail_country_finland"] += 1
        else:
            check["country_mismatches"].append({"record_id": uuid, "name": out.at[i, "name"], "detail_country": facts["country"]})
        if facts["boundary_wkt"]:
            out.at[i, "geometry_kind"] = "polygon"
            check["n_polygon"] += 1
        else:
            out.at[i, "geometry_kind"] = "point"
            check["n_without_polygon"] += 1
            check["without_polygon"].append({"record_id": uuid, "name": out.at[i, "name"]})
    return out, check
