"""Projected-CRS geometry: the non-clustering alternative to Method 2.

Everything here happens in EPSG:3035 (ETRS89 / LAEA Europe), the equal-area
projection used for pan-European reporting.  Buffering in degrees would be
wrong: one degree of longitude is 111 km at the equator and 55 km at 60N, which
is precisely the latitude band most of these stations sit in.
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz
from shapely import wkt
from shapely.geometry import Point

WGS84 = "EPSG:4326"
LAEA_EUROPE = "EPSG:3035"


def to_geodataframe(df: pd.DataFrame, crs: str = WGS84) -> gpd.GeoDataFrame:
    geometry = [Point(xy) for xy in zip(df.lon, df.lat)]
    return gpd.GeoDataFrame(df.copy(), geometry=geometry, crs=crs)


def buffer_overlap_pairs(df: pd.DataFrame, radius_km: float = 5.0) -> pd.DataFrame:
    """Match records by intersecting circular buffers in a projected CRS.

    A deliberately different failure mode from DBSCAN: no transitivity, so a
    chain of stations 4 km apart cannot merge into one 40 km blob.  Comparing
    the two candidate sets is more informative than trusting either.
    """
    if df.empty:
        return pd.DataFrame(columns=["method", "cluster", "ri_a", "record_id_a", "source_id_a", "name_a", "ri_b", "record_id_b", "source_id_b", "name_b", "distance_km", "name_similarity", "uri_a", "uri_b"])

    gdf = to_geodataframe(df).to_crs(LAEA_EUROPE)
    gdf = gdf.reset_index(drop=True)
    buffered = gdf.copy()
    buffered["geometry"] = buffered.geometry.buffer(radius_km * 1000.0)

    joined = gpd.sjoin(
        buffered[["ri", "record_id", "source_id", "name", "uri", "geometry"]],
        gdf[["ri", "record_id", "source_id", "name", "uri", "geometry"]].rename(
            columns={"ri": "ri_b", "record_id": "record_id_b", "source_id": "source_id_b", "name": "name_b", "uri": "uri_b"}
        ),
        how="inner",
        predicate="intersects",
    )
    joined = joined[joined.ri != joined.ri_b]

    left_pts = gdf.set_index(["ri", "source_id"]).geometry
    rows = []
    seen = set()
    for _, r in joined.iterrows():
        key = tuple(sorted([(r["ri"], r["record_id"]), (r["ri_b"], r["record_id_b"])]))
        if key in seen:
            continue
        seen.add(key)
        (ri_a, record_id_a), (ri_b, record_id_b) = key
        # `key` is sorted, but the sjoin row may have the pair the other way round.
        if (r["ri"], r["record_id"]) == (ri_a, record_id_a):
            a, b = (r["source_id"], r["name"], r["uri"]), (r["source_id_b"], r["name_b"], r["uri_b"])
        else:
            a, b = (r["source_id_b"], r["name_b"], r["uri_b"]), (r["source_id"], r["name"], r["uri"])
        try:
            left_pts = gdf.set_index(["ri", "record_id"]).geometry
            dist_m = left_pts.loc[(ri_a, record_id_a)].distance(left_pts.loc[(ri_b, record_id_b)])
        except KeyError:
            continue
        rows.append(
            {
                "method": "buffer", "cluster": -1, "ri_a": ri_a, "record_id_a": record_id_a,
                "source_id_a": a[0], "name_a": a[1], "ri_b": ri_b,
                "record_id_b": record_id_b, "source_id_b": b[0], "name_b": b[1],
                "distance_km": round(float(dist_m) / 1000.0, 3),
                "name_similarity": round(fuzz.token_set_ratio(a[1], b[1]) / 100.0, 3),
                "uri_a": a[2], "uri_b": b[2],
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("distance_km").reset_index(drop=True)


PAIR_COLUMNS = ["method", "cluster", "ri_a", "record_id_a", "source_id_a", "name_a", "ri_b", "record_id_b",
                "source_id_b", "name_b", "distance_km", "name_similarity", "uri_a", "uri_b"]
POLYGON_PAIR_COLUMNS = PAIR_COLUMNS + ["geometry_kind_a", "geometry_kind_b", "polygon_distance_m"]


def _record_geometry(row):
    """Boundary polygon from ``extra_ids`` when the record is a polygon, else its point."""
    if row.get("geometry_kind") == "polygon":
        boundary = json.loads(row.get("extra_ids") or "{}").get("boundary_wkt")
        if boundary:
            return wkt.loads(boundary)
    return Point(row["lon"], row["lat"])


def buffer_overlap_pairs_polygon(df: pd.DataFrame, radius_km: float = 5.0) -> pd.DataFrame:
    """Buffer matching where a record's boundary polygon is used instead of its point.

    Opt-in sibling of :func:`buffer_overlap_pairs`. A pair is a candidate when the
    distance between the two records' geometries, in EPSG:3035, is within
    ``radius_km``. For a point against a polygon that is the distance from the point
    to the polygon (0 when the point is inside), so a polygon is evidence and not a
    hard inside/outside cut. Records without a polygon keep their point.

    ``distance_km`` is still the point-to-point distance (as in the plain buffer
    file); ``polygon_distance_m`` is the geometry-to-geometry distance in metres and
    is empty for pairs where neither record has a polygon. ``name_similarity`` is
    computed on the raw names, as in :func:`buffer_overlap_pairs`.
    """
    if df.empty:
        return pd.DataFrame(columns=POLYGON_PAIR_COLUMNS)
    df = df.reset_index(drop=True)
    shapes = gpd.GeoSeries([_record_geometry(r) for r in df.to_dict("records")], crs=WGS84).to_crs(LAEA_EUROPE)
    points = to_geodataframe(df).to_crs(LAEA_EUROPE).geometry
    radius_m = radius_km * 1000.0

    # Coarse candidate search with a slightly wide buffer; the exact distance decides.
    left = gpd.GeoDataFrame({"i": range(len(df))}, geometry=shapes.buffer(radius_m * 1.01), crs=LAEA_EUROPE)
    right = gpd.GeoDataFrame({"j": range(len(df))}, geometry=shapes, crs=LAEA_EUROPE)
    joined = gpd.sjoin(left, right, how="inner", predicate="intersects")
    ri = df.ri.to_numpy()
    rows = []
    for i, j in zip(joined.i.to_numpy(), joined.j.to_numpy()):
        if i >= j or ri[i] == ri[j]:
            continue
        gap_m = float(shapes.iloc[i].distance(shapes.iloc[j]))
        if gap_m > radius_m:
            continue
        a, b = sorted((df.iloc[i], df.iloc[j]), key=lambda r: (r["ri"], r["record_id"]))
        a_kind = "polygon" if a.get("geometry_kind") == "polygon" else "point"
        b_kind = "polygon" if b.get("geometry_kind") == "polygon" else "point"
        has_polygon = "polygon" in (a_kind, b_kind)
        rows.append({
            "method": "buffer_polygon", "cluster": -1, "ri_a": a["ri"], "record_id_a": a["record_id"],
            "source_id_a": a["source_id"], "name_a": a["name"], "ri_b": b["ri"], "record_id_b": b["record_id"],
            "source_id_b": b["source_id"], "name_b": b["name"],
            "distance_km": round(float(points.iloc[i].distance(points.iloc[j])) / 1000.0, 3),
            "name_similarity": round(fuzz.token_set_ratio(a["name"], b["name"]) / 100.0, 3),
            "uri_a": a["uri"], "uri_b": b["uri"], "geometry_kind_a": a_kind, "geometry_kind_b": b_kind,
            "polygon_distance_m": round(gap_m, 1) if has_polygon else None,
            "_gap": gap_m,
        })
    frame = pd.DataFrame(rows, columns=POLYGON_PAIR_COLUMNS + ["_gap"])
    return frame.sort_values(["_gap", "name_similarity"], ascending=[True, False]).drop(columns="_gap").reset_index(drop=True)


def write_spatial_outputs(df: pd.DataFrame, labels, out_dir) -> None:
    """Persist the clustered stations as GeoPackage + GeoJSON."""
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = to_geodataframe(df)
    gdf["cluster"] = labels
    gdf.to_file(out_dir / "stations_clustered.gpkg", layer="stations", driver="GPKG")
    gdf.to_file(out_dir / "stations_clustered.geojson", driver="GeoJSON")
