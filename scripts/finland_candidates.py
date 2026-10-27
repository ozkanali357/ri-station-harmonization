"""Candidate cross-RI pairs for the Finnish records, for hand labelling (Step 2, generalised).

Scope (rule chosen 2026-10-19): harmonised records whose ``country`` is ``FI``. For ICOS and
ACTRIS that is the source country code; for eLTER it is the 20 DEIMS sites whose title ends
in `` - Finland`` and whose detail record says Finland (see ``ri_harmonize.deims_detail``).

Every cross-RI pair of those records gets one distance, computed once in EPSG:3035:

* ``distance_km_geometry``: polygon-aware. A DEIMS record with a boundary is its polygon
  (0 when the other record lies inside it); any other record is its point.
* ``distance_km_point``: point to point, for comparison.

A pair is a candidate when ``distance_km_geometry`` is at most ``MAX_KM`` (5). The cumulative
counts at the other thresholds come from the same distance table, not from further runs.

Nothing is labelled here: ``same_place``, ``match_type``, ``evidence``, ``checked_by`` and
``checked_at`` are written empty. The table is an unreviewed run.

Usage (from the repo root, after ``python -m ri_harmonize.cli run`` or ``--deims-detail-finland``
has filled ``data/raw/``)::

    python scripts/finland_candidates.py              # cached responses only
    python scripts/finland_candidates.py --fetch      # fetch what the cache lacks
    python scripts/finland_candidates.py --links-only # only outputs/finland_candidate_station_links.csv

``--links-only`` never touches ``outputs/finland_candidates.csv``, which may be hand-labelled.
A plain run rewrites it, now with the ``deims_*`` evidence columns before ``methods``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ri_harmonize import cluster as cl  # noqa: E402
from ri_harmonize import geo  # noqa: E402
from ri_harmonize.cli import RAW, load_stations  # noqa: E402

OUT = ROOT / "outputs"
MAX_KM = 5.0
THRESHOLDS_KM = [0.25, 0.5, 1, 2, 5, 10, 20]
# Same defaults as `python -m ri_harmonize.cli run`.
EPS_KM, MIN_SAMPLES, BUFFER_KM, KMEANS_DIVISOR = 5.0, 2, 5.0, 3

METHODS = ["dbscan", "buffer", "kmeans"]
RECORD_FIELDS = ["ri", "record_id", "source_id", "id_scheme", "name", "lat", "lon", "uri"]
KEY = ["ri_a", "record_id_a", "ri_b", "record_id_b"]

# DEIMS network evidence: does the pair's DEIMS record list the pair's ICOS station? Filled only for
# ICOS-eLTER pairs (blank otherwise); it is one fact about the pair, so there is one column, not one per side.
LINK_COLUMNS = ["deims_lists_icos_station", "deims_icos_sitecode_matched", "deims_icos_sitecode_verified",
                "deims_icos_sitecodes_listed"]
LINK_KEY = KEY + ["source_id_a", "source_id_b"]

# Hyytiälä columns, same order; the new evidence columns sit before `methods`, so the
# label columns stay together at the right-hand end.
COLUMNS = (
    ["cluster_id", "cluster_size"]
    + [f"{f}_a" for f in ("ri", "record_id", "source_id", "id_scheme", "name", "lat", "lon", "uri")]
    + [f"{f}_b" for f in ("ri", "record_id", "source_id", "id_scheme", "name", "lat", "lon", "uri")]
    + ["distance_km_dbscan", "distance_km_buffer", "distance_km_kmeans",
       "name_similarity_dbscan", "name_similarity_buffer", "name_similarity_kmeans"]
    + ["distance_km_geometry", "distance_km_point", "polygon_distance_m",
       "has_boundary_a", "has_boundary_b", "polygon_area_ha_a", "polygon_area_ha_b",
       "site_type_a", "site_type_b"]
    + LINK_COLUMNS
    + ["methods", "same_place", "checked_by", "checked_at", "evidence", "match_type"]
)
LABEL_COLUMNS = ["same_place", "checked_by", "checked_at", "evidence", "match_type"]

# Records the presence check looks for: (what it is, RI, source_id).
EXPECTED = [
    ("ICOS FI-Kvr (Kuivajärvi)", "ICOS", "FI-Kvr"),
    ("ICOS FI-Lom (Lompolojankka)", "ICOS", "FI-Lom"),
    ("DEIMS Lompolojankka", "eLTER", "e6b372ee-f310-49fd-9d0d-2a8306a06b64"),
    ("DEIMS Pallas LTER observatory", "eLTER", "b0edd1d7-4fe7-4945-a366-4e9ff21e9dd3"),
    ("DEIMS Helsinki HMA-LTSER platform", "eLTER", "35e3775a-88bc-483f-aed0-b614ce7736e2"),
]


def finnish_records(stations: pd.DataFrame) -> pd.DataFrame:
    """The Finland scope: harmonised records with country FI (eLTER only after the detail check)."""
    return stations[stations.country == "FI"].reset_index(drop=True)


def _extra(row, key):
    return json.loads(row.get("extra_ids") or "{}").get(key)


def record_table(fi: pd.DataFrame) -> pd.DataFrame:
    """Per-record geometry facts in EPSG:3035: polygon or point shape, area, boundary flag, site type."""
    shapes = gpd.GeoSeries([geo._record_geometry(r) for r in fi.to_dict("records")], crs=geo.WGS84).to_crs(geo.LAEA_EUROPE)
    points = gpd.GeoSeries([Point(x, y) for x, y in zip(fi.lon, fi.lat)], crs=geo.WGS84).to_crs(geo.LAEA_EUROPE)
    has_boundary = (fi.geometry_kind == "polygon").to_numpy()
    return pd.DataFrame({
        "geom": list(shapes), "point": list(points), "has_boundary": has_boundary,
        "polygon_area_ha": [round(s.area / 1e4, 2) if b else None for s, b in zip(shapes, has_boundary)],
        "site_type": [(_extra(r, "deims_site_type") or "") for r in fi.to_dict("records")],
    }, index=fi.index)


def pair_distances(fi: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    """Every cross-RI pair once, with its polygon-aware and point-to-point distance in metres."""
    rows = []
    for i, j in combinations(fi.index, 2):
        if fi.ri[i] == fi.ri[j]:
            continue
        i, j = sorted((i, j), key=lambda k: (fi.ri[k], fi.record_id[k]))
        rows.append({
            "i": i, "j": j,
            "geometry_m": float(rec.geom[i].distance(rec.geom[j])),
            "point_m": float(rec.point[i].distance(rec.point[j])),
            "with_polygon": bool(rec.has_boundary[i] or rec.has_boundary[j]),
        })
    return pd.DataFrame(rows, columns=["i", "j", "geometry_m", "point_m", "with_polygon"])


def cumulative_counts(dist: pd.DataFrame, fi: pd.DataFrame, thresholds=THRESHOLDS_KM) -> pd.DataFrame:
    """Cumulative number of pairs at or below each threshold, overall and by RI pair type."""
    kind = dist.apply(lambda r: "-".join(sorted((fi.ri[r.i], fi.ri[r.j]), key=str.lower)), axis=1)
    rows = []
    for t in thresholds:
        within = dist.geometry_m <= t * 1000
        row = {"threshold_km": t, "pairs_geometry": int(within.sum()),
               "pairs_point": int((dist.point_m <= t * 1000).sum())}
        for k in sorted(kind.unique(), key=str.lower):
            row[f"geometry_{k}"] = int((within & (kind == k)).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def method_pairs(stations: pd.DataFrame) -> pd.DataFrame:
    """DBSCAN, buffer and k-means pairs at the CLI defaults, on the full three-source table."""
    labels = cl.dbscan_labels(stations, eps_km=EPS_KM, min_samples=MIN_SAMPLES)
    k = max(2, len(stations) // KMEANS_DIVISOR)
    frames = [
        cl.cross_ri_pairs(stations, labels, "dbscan"),
        geo.buffer_overlap_pairs(stations, radius_km=BUFFER_KM),
        cl.cross_ri_pairs(stations, cl.kmeans_labels(stations, k=k), "kmeans"),
    ]
    return pd.concat([f for f in frames if not f.empty], ignore_index=True)


def _normalised(frame: pd.DataFrame) -> pd.DataFrame:
    """Order each pair by (ri, record_id) so (A, B) and (B, A) are the same pair."""
    frame = frame.copy()
    swap = pd.Series([(a, b) > (c, d) for a, b, c, d in zip(frame.ri_a, frame.record_id_a, frame.ri_b, frame.record_id_b)],
                     index=frame.index)
    for col in ("ri", "record_id"):
        a, b = frame[f"{col}_a"].copy(), frame[f"{col}_b"].copy()
        frame[f"{col}_a"], frame[f"{col}_b"] = a.where(~swap, b), b.where(~swap, a)
    return frame


def method_columns(pairs: pd.DataFrame) -> pd.DataFrame:
    """One row per pair with the distance, name similarity and flag list of each method that found it."""
    columns = KEY + [f"{p}_{m}" for p in ("distance_km", "name_similarity") for m in METHODS] + ["methods"]
    if pairs is None or pairs.empty:
        return pd.DataFrame(columns=columns)
    pairs = _normalised(pairs)
    out = {}
    for row in pairs.itertuples():
        entry = out.setdefault((row.ri_a, row.record_id_a, row.ri_b, row.record_id_b), {"methods": []})
        entry["methods"].append(row.method)
        entry[f"distance_km_{row.method}"] = row.distance_km
        entry[f"name_similarity_{row.method}"] = row.name_similarity
    frame = pd.DataFrame([{**dict(zip(KEY, k)), **v, "methods": ",".join(sorted(v["methods"]))} for k, v in out.items()])
    return frame.reindex(columns=columns)


def _icos_uri(value: str) -> str:
    """Compare ICOS resource URIs regardless of http/https and a trailing slash."""
    return value.strip().replace("https://", "http://", 1).rstrip("/")


def deims_icos_stations(row) -> list[dict]:
    """ICOS station URIs a DEIMS record lists in its ``ICOS`` network entries (``siteCode`` is a comma-separated URI list)."""
    listed = []
    for network in (_extra(row, "deims_networks") or []):
        if (network.get("name") or "").strip() != "ICOS" or not network.get("siteCode"):
            continue
        for code in network["siteCode"].split(","):
            if code.strip():
                listed.append({"uri": code.strip(), "verified": network.get("verified")})
    return listed


def station_link(icos_row, deims_row) -> dict:
    """Does the DEIMS record list this ICOS station? Exact match of the ICOS resource URI (``record_id``) against
    each listed ``siteCode`` URI, after http/https and trailing-slash normalisation; no suffix or name matching."""
    listed = deims_icos_stations(deims_row)
    hit = next((x for x in listed if _icos_uri(x["uri"]) == _icos_uri(icos_row["record_id"])), None)
    return {
        "deims_lists_icos_station": hit is not None,
        "deims_icos_sitecode_matched": hit["uri"] if hit else "",
        "deims_icos_sitecode_verified": hit["verified"] if hit else "",
        "deims_icos_sitecodes_listed": ";".join(x["uri"] for x in listed),
    }


def link_columns(fi: pd.DataFrame, chosen: pd.DataFrame) -> pd.DataFrame:
    """The DEIMS-lists-ICOS-station evidence for each chosen pair; blank unless the pair is ICOS-eLTER."""
    rows = []
    for i, j in zip(chosen.i, chosen.j):
        pair = {fi.ri[i]: fi.loc[i], fi.ri[j]: fi.loc[j]}
        rows.append(station_link(pair["ICOS"], pair["eLTER"]) if set(pair) == {"ICOS", "eLTER"}
                    else dict.fromkeys(LINK_COLUMNS, ""))
    return pd.DataFrame(rows, columns=LINK_COLUMNS)


def assign_clusters(fi: pd.DataFrame, edges) -> dict:
    """Connected components of the candidate-pair graph: record index -> cluster number.

    Components are numbered 1..n from north to south (mean latitude) so the numbering is
    stable between runs. Records with no candidate pair get no cluster.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        parent[find(i)] = find(j)
    groups = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    ordered = sorted(groups.values(), key=lambda g: (-fi.lat[g].mean(), min(g)))
    return {node: number for number, group in enumerate(ordered, start=1) for node in group}


def build_candidates(fi: pd.DataFrame, rec: pd.DataFrame, dist: pd.DataFrame, methods: pd.DataFrame | None = None,
                     max_km: float = MAX_KM) -> pd.DataFrame:
    """The labelling table: pairs within ``max_km`` (polygon-aware), label columns empty."""
    chosen = dist[dist.geometry_m <= max_km * 1000].copy()
    clusters = assign_clusters(fi, zip(chosen.i, chosen.j))
    sizes = pd.Series(clusters).value_counts().to_dict()

    def side(index, suffix):
        r = fi.loc[index, RECORD_FIELDS].reset_index(drop=True)
        r.columns = [f"{c}_{suffix}" for c in RECORD_FIELDS]
        extra = pd.DataFrame({
            f"has_boundary_{suffix}": rec.has_boundary[index].to_numpy(),
            f"polygon_area_ha_{suffix}": rec.polygon_area_ha[index].to_numpy(),
            f"site_type_{suffix}": rec.site_type[index].to_numpy(),
        })
        return pd.concat([r, extra], axis=1)

    table = pd.concat([side(chosen.i, "a"), side(chosen.j, "b")], axis=1)
    table["cluster_id"] = [clusters[i] for i in chosen.i]
    table["cluster_size"] = [sizes[clusters[i]] for i in chosen.i]
    table["distance_km_geometry"] = (chosen.geometry_m.to_numpy() / 1000).round(3)
    table["distance_km_point"] = (chosen.point_m.to_numpy() / 1000).round(3)
    table["polygon_distance_m"] = [round(g, 1) if w else None for g, w in zip(chosen.geometry_m, chosen.with_polygon)]
    table = pd.concat([table, link_columns(fi, chosen)], axis=1)

    table = table.merge(method_columns(methods), on=KEY, how="left")
    for col in table.columns:
        if col.startswith(("distance_km_dbscan", "distance_km_buffer", "distance_km_kmeans", "name_similarity_")):
            table[col] = table[col].astype(object).where(table[col].notna(), "")
    table["methods"] = table["methods"].fillna("")
    for col in LABEL_COLUMNS:
        table[col] = ""
    table = table.sort_values(["cluster_id", "distance_km_geometry", "ri_a", "record_id_a", "ri_b", "record_id_b"])
    return table[COLUMNS].reset_index(drop=True)


def presence_checks(fi: pd.DataFrame, rec: pd.DataFrame) -> list[dict]:
    out = []
    for label, ri, source_id in EXPECTED:
        hit = fi[(fi.ri == ri) & (fi.source_id == source_id)]
        if hit.empty:
            out.append({"record": label, "present": False})
            continue
        i = hit.index[0]
        out.append({"record": label, "present": True, "name": fi["name"][i], "lat": float(fi.lat[i]), "lon": float(fi.lon[i]),
                    "has_boundary": bool(rec.has_boundary[i]), "polygon_area_ha": rec.polygon_area_ha[i]})
    return out


def oddities(fi: pd.DataFrame, rec: pd.DataFrame, dist: pd.DataFrame, table: pd.DataFrame, max_km: float = MAX_KM) -> dict:
    """Facts a labeller should know before trusting the table."""
    chosen = dist[dist.geometry_m <= max_km * 1000]
    swallow = []
    for i in rec.index[rec.has_boundary]:
        mine = chosen[(chosen.i == i) | (chosen.j == i)]
        others = [j if i == a else a for a, j in zip(mine.i, mine.j)]
        inside = [o for o, g in zip(others, mine.geometry_m) if g == 0]
        swallow.append({"name": fi["name"][i], "area_ha": rec.polygon_area_ha[i], "pairs": len(mine), "pairs_at_distance_0": len(inside),
                        "records_inside": sorted(f"{fi.ri[o]}:{fi.source_id[o]}" for o in inside)})
    polygon_only = chosen[chosen.point_m > max_km * 1000]
    two_icos = []
    for i in fi.index[fi.ri == "eLTER"]:
        codes = []
        for network in (_extra(fi.loc[i], "deims_networks") or []):
            if "ICOS" in (network.get("name") or "") and network.get("siteCode"):
                codes += [c.strip().rsplit("/", 1)[-1] for c in network["siteCode"].split(",") if c.strip()]
        if len(codes) > 1:
            present = {c: bool(((fi.ri == "ICOS") & fi.record_id.str.endswith("_" + c.split("_", 1)[-1])).any()) for c in codes}
            two_icos.append({"name": fi["name"][i], "icos_codes": codes, "present_in_harmonised": present})
    paired = set(chosen.i) | set(chosen.j)
    unpaired = fi[~fi.index.isin(paired)]
    return {
        "polygon_swallow": sorted(swallow, key=lambda s: -s["pairs"]),
        "pairs_in_only_because_of_polygon": [
            {"a": f"{r.ri_a}:{r.source_id_a}", "b": f"{r.ri_b}:{r.source_id_b}", "distance_km_point": r.distance_km_point,
             "distance_km_geometry": r.distance_km_geometry}
            for r in table[table.distance_km_point > max_km].itertuples()],
        "deims_sites_listing_several_icos_stations": two_icos,
        "unpaired_records": {ri: sorted(g.name.tolist()) for ri, g in unpaired.groupby("ri")},
        "n_pairs_polygon_only_count": int(len(polygon_only)),
    }


def write_summary(path: Path, fi, table, counts, presence, odd, params, manifest_sources) -> None:
    n_by_ri = fi.ri.value_counts().to_dict()
    lines = [
        "# Finland candidate pairs (unreviewed)", "",
        f"Generated {params['generated_at']} from git revision `{params['git_revision'][:7]}`. "
        "This is a candidate table for hand labelling: `same_place`, `match_type`, `evidence`, `checked_by` and `checked_at` are empty. "
        "Nothing in it is a result.", "",
        "## Scope", "",
        f"- Records: {len(fi)} Finnish harmonised records ({', '.join(f'{k} {v}' for k, v in sorted(n_by_ri.items()))}); "
        "country FI, eLTER by title suffix ` - Finland` confirmed by the DEIMS detail country.",
        f"- Candidate rule: cross-RI pair, polygon-aware distance at most {MAX_KM:g} km (EPSG:3035; DEIMS polygon where a boundary exists, 0 when the other record is inside, else points).",
        f"- Table: {len(table)} pairs in {table.cluster_id.nunique()} clusters (connected components of the pair graph, numbered north to south).",
        f"- Method columns (DBSCAN eps {EPS_KM:g} km, buffer {BUFFER_KM:g} km, k-means k = n // {KMEANS_DIVISOR}) are the CLI defaults run on the full three-source table; blank means that method did not pair the two records. "
                # Note: outputs/ generated before a15cda6 report raw-name name_similarity; do not assume they reflect this code.
"Their `name_similarity` uses the normalised name (`name_norm`) for all three methods, so a given pair shows the same value wherever it appears.", "",
        "## Cumulative candidate pairs", "",
        "Each pair's distance was computed once; the rows count pairs at or below the threshold. `geometry` = polygon-aware, `point` = point to point.", "",
        counts.to_markdown(index=False), "",
        "## Presence checks", "",
    ]
    for p in presence:
        lines.append(f"- {p['record']}: " + (f"present ({p['name']}; {p['lat']:.5f}, {p['lon']:.5f}; "
                     + (f"polygon {p['polygon_area_ha']:,.0f} ha" if p["has_boundary"] else "point only") + ")" if p["present"] else "**missing**"))
    lines += ["", "## Oddities", "", "Sites with a boundary polygon (every record inside a polygon is at distance 0, so a large polygon pairs with everything in it):", ""]
    for s in odd["polygon_swallow"]:
        lines.append(f"- {s['name']}: {s['area_ha']:,.0f} ha, {s['pairs']} pairs, {s['pairs_at_distance_0']} at distance 0")
    lines += ["", f"Pairs that are in only because of the polygon (point distance above {MAX_KM:g} km): {len(odd['pairs_in_only_because_of_polygon'])}"]
    for x in odd["pairs_in_only_because_of_polygon"]:
        lines.append(f"- {x['a']} / {x['b']}: point {x['distance_km_point']} km, geometry {x['distance_km_geometry']} km")
    lines += ["", "DEIMS sites that list several ICOS stations (one site to many stations):", ""]
    for x in odd["deims_sites_listing_several_icos_stations"]:
        lines.append(f"- {x['name']}: {', '.join(x['icos_codes'])}; in harmonised records: {x['present_in_harmonised']}")
    lines += ["", "Finnish records with no candidate pair at this threshold (no match is implied or ruled out):", ""]
    for ri, names in odd["unpaired_records"].items():
        lines.append(f"- {ri} ({len(names)}): {', '.join(names)}")
    lines += ["", "## Sources", ""]
    for name, entry in manifest_sources.items():
        lines.append(f"- {name}: {entry['endpoint']} retrieved {entry['retrieved_at']}")
    lines += ["", "Raw responses are cached in `data/raw/` (not committed; DEIMS detail records carry site-manager personal data) with SHA-256 in `outputs/finland_candidates_run.json`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _retrieved_at(entry: dict):
    """Source-level retrieval time, else the latest per-page time (DEIMS detail keeps it per page)."""
    return entry.get("retrieved_at") or max((p["retrieved_at"] for p in entry.get("pages", []) if p.get("retrieved_at")), default=None)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fetch", action="store_true", help="fetch sources missing from data/raw/ instead of failing")
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--links-only", action="store_true", dest="links_only",
                        help="write only finland_candidate_station_links.csv; leaves finland_candidates.csv (possibly "
                             "hand-labelled) and the other outputs untouched")
    args = parser.parse_args(argv)
    out = Path(args.out_dir)

    stations = load_stations(offline=not args.fetch, deims_detail_finland=True)
    fi = finnish_records(stations)
    rec = record_table(fi)
    dist = pair_distances(fi, rec)
    table = build_candidates(fi, rec, dist, method_pairs(stations))
    if args.links_only:
        out.mkdir(parents=True, exist_ok=True)
        table[LINK_KEY + LINK_COLUMNS].to_csv(out / "finland_candidate_station_links.csv", index=False)
        print(f"Wrote {len(table)} rows to {out / 'finland_candidate_station_links.csv'}")
        return
    counts = cumulative_counts(dist, fi)
    presence, odd = presence_checks(fi, rec), oddities(fi, rec, dist, table)

    raw_manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    sources = {k: {"endpoint": v.get("endpoint"), "retrieved_at": _retrieved_at(v),
                   "sha256": [p.get("sha256") for p in v.get("pages", [])]} for k, v in raw_manifest["sources"].items()}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip()
    params = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "git_revision": revision}

    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "finland_candidates.csv", index=False)
    counts.to_csv(out / "finland_candidates_thresholds.csv", index=False)
    write_summary(out / "finland_candidates_summary.md", fi, table, counts, presence, odd, params, sources)
    (out / "finland_candidates_run.json").write_text(json.dumps({
        **params, "status": "unreviewed", "max_km": MAX_KM, "thresholds_km": THRESHOLDS_KM,
        "method_parameters": {"eps_km": EPS_KM, "min_samples": MIN_SAMPLES, "buffer_km": BUFFER_KM, "kmeans_divisor": KMEANS_DIVISOR},
        "n_records": {k: int(v) for k, v in fi.ri.value_counts().items()}, "n_pairs": int(len(table)),
        "presence_checks": presence, "sources": sources,
    }, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {len(table)} candidate pairs ({table.cluster_id.nunique()} clusters) to {out / 'finland_candidates.csv'}")
    print(counts.to_string(index=False))


if __name__ == "__main__":
    main()
