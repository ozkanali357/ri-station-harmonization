"""Synthetic RI responses that mimic the real payload shapes.

Used by the tests and by `make_fixtures.py` so the pipeline can be exercised
end to end without touching the network.
"""

import json

# Three genuinely co-located pairs, one near-miss at ~40 km, and isolated noise.
_PLACES = [
    # name,            lat,     lon,    icos_code, deims_uuid,                              offset_km
    ("Hyytiala",       61.8474, 24.2948, "SMR",    "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", 0.4),
    ("Zotino",         60.8000, 89.3500, "ZOT",    "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb", 1.2),
    ("Hohenpeissenberg", 47.8011, 11.0246, "HPB",  "cccccccc-3333-4333-8333-cccccccccccc", 2.5),
    ("Kosetice",       49.5730, 15.0800, "KRE",    "dddddddd-4444-4444-8444-dddddddddddd", 38.0),
]

_ICOS_ONLY = [("Weybourne", 52.9500, 1.1210, "WAO", "0-20008-0-WAO"), ("Mace Head", 53.3260, -9.9000, "MHD", None)]
_DEIMS_ONLY = [("Wadden Sea", 53.2500, 5.2500, "eeeeeeee-5555-4555-8555-eeeeeeeeeeee")]

_KM_PER_DEG_LAT = 110.574


def icos_payload() -> dict:
    bindings = []

    def add(name, lat, lon, code, wigos=None, klass="Atmospheric station"):
        row = {
            "uri": {"value": f"https://meta.icos-cp.eu/resources/stations/AS_{code}"},
            "stationId": {"value": code},
            "name": {"value": name},
            "lat": {"value": f"{lat}"},
            "lon": {"value": f"{lon}"},
            "elevation": {"value": "181.0"},
            "country": {"value": "fi"},
            "klass": {"value": klass},
        }
        if wigos:
            row["wigos"] = {"value": wigos}
        bindings.append(row)

    for name, lat, lon, code, _uuid, _off in _PLACES:
        add(name, lat, lon, code, wigos=f"0-20008-0-{code}")
    for name, lat, lon, code, wigos in _ICOS_ONLY:
        add(name, lat, lon, code, wigos=wigos)
    return {"head": {"vars": []}, "results": {"bindings": bindings}}


def deims_payload() -> list:
    sites = []

    def add(name, lat, lon, uuid):
        sites.append({
            "title": f"{name} LTER site",
            "id": {"prefix": "https://deims.org/", "suffix": uuid},
            "coordinates": f"POINT ({lon} {lat})",
            "changed": "2026-08-14",
        })

    for name, lat, lon, _code, uuid, offset_km in _PLACES:
        add(name, lat + offset_km / _KM_PER_DEG_LAT, lon, uuid)
    for name, lat, lon, uuid in _DEIMS_ONLY:
        add(name, lat, lon, uuid)
    return sites


def write_all(raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "icos_stations_page_0001.json").write_text(json.dumps(icos_payload()), encoding="utf-8")
    (raw_dir / "deims_sites.json").write_text(json.dumps(deims_payload()), encoding="utf-8")
    (raw_dir / "manifest.json").write_text(json.dumps({"sources": {"icos": {"complete": True, "pages": [{"file": "icos_stations_page_0001.json"}]}}}), encoding="utf-8")
