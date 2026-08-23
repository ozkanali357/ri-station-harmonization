"""Projected-CRS geometry: the non-clustering alternative to Method 2.

Everything here happens in EPSG:3035 (ETRS89 / LAEA Europe), the equal-area
projection used for pan-European reporting.  Buffering in degrees would be
wrong: one degree of longitude is 111 km at the equator and 55 km at 60N, which
is precisely the latitude band most of these stations sit in.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
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
        return pd.DataFrame(columns=["ri_a", "id_a", "ri_b", "id_b", "distance_km"])

    gdf = to_geodataframe(df).to_crs(LAEA_EUROPE)
    gdf = gdf.reset_index(drop=True)
    buffered = gdf.copy()
    buffered["geometry"] = buffered.geometry.buffer(radius_km * 1000.0)

    joined = gpd.sjoin(
        buffered[["ri", "source_id", "name", "geometry"]],
        gdf[["ri", "source_id", "name", "geometry"]].rename(
            columns={"ri": "ri_b", "source_id": "id_b", "name": "name_b"}
        ),
        how="inner",
        predicate="intersects",
    )
    joined = joined[joined.ri != joined.ri_b]

    left_pts = gdf.set_index(["ri", "source_id"]).geometry
    rows = []
    seen = set()
    for _, r in joined.iterrows():
        key = tuple(sorted([(r["ri"], r["source_id"]), (r["ri_b"], r["id_b"])]))
        if key in seen:
            continue
        seen.add(key)
        (ri_a, id_a), (ri_b, id_b) = key
        try:
            dist_m = left_pts.loc[(ri_a, id_a)].distance(left_pts.loc[(ri_b, id_b)])
        except KeyError:
            continue
        rows.append(
            {
                "ri_a": ri_a, "id_a": id_a,
                "ri_b": ri_b, "id_b": id_b,
                "distance_km": round(float(dist_m) / 1000.0, 3),
            }
        )
    frame = pd.DataFrame(rows, columns=["ri_a", "id_a", "ri_b", "id_b", "distance_km"])
    if frame.empty:
        return frame
    return frame.sort_values("distance_km").reset_index(drop=True)


def write_spatial_outputs(df: pd.DataFrame, labels, out_dir) -> None:
    """Persist the clustered stations as GeoPackage + GeoJSON."""
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = to_geodataframe(df)
    gdf["cluster"] = labels
    gdf.to_file(out_dir / "stations_clustered.gpkg", layer="stations", driver="GPKG")
    gdf.to_file(out_dir / "stations_clustered.geojson", driver="GeoJSON")
