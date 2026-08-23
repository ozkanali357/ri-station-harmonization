"""Spatial grouping of stations across research infrastructures.

Two clustering methods and one geometric method, all producing the same
artefact: a set of candidate groups, each of which is a claim that several
records from different infrastructures describe the same physical place.

Method choice is argued rather than assumed:

* DBSCAN on the haversine metric is the default.  The number of co-located
  groups is not known in advance, the groups are irregular, and an isolated
  station must be allowed to stay isolated.  eps is a real distance in
  kilometres, which makes it a scientific parameter rather than a knob.
* k-means is run as a baseline.  It needs k, forces every station into a
  cluster, and minimises Euclidean distance, so it is run on 3-D unit-sphere
  coordinates rather than on raw latitude/longitude - otherwise it is wrong
  near the poles and across the antimeridian.
* Buffer intersection in a projected CRS is the geometric alternative and does
  not involve clustering at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans

EARTH_RADIUS_KM = 6371.0088


def _radians(df: pd.DataFrame) -> np.ndarray:
    return np.radians(df[["lat", "lon"]].to_numpy(dtype=float))


def dbscan_labels(df: pd.DataFrame, eps_km: float, min_samples: int = 2) -> np.ndarray:
    """Density-based grouping.  Label -1 means 'left alone as noise'."""
    if df.empty:
        return np.empty(0, dtype=int)
    model = DBSCAN(
        eps=eps_km / EARTH_RADIUS_KM,
        min_samples=min_samples,
        metric="haversine",
        algorithm="ball_tree",
    )
    return model.fit_predict(_radians(df))


def kmeans_labels(df: pd.DataFrame, k: int, seed: int = 0) -> np.ndarray:
    """Baseline.  Operates on unit-sphere xyz so that Euclidean distance is a
    monotone function of great-circle distance."""
    if df.empty:
        return np.empty(0, dtype=int)
    rad = _radians(df)
    lat, lon = rad[:, 0], rad[:, 1]
    xyz = np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    k = max(1, min(k, len(df)))
    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(xyz)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    p1, p2 = np.radians([lat1, lon1]), np.radians([lat2, lon2])
    dlat, dlon = p2[0] - p1[0], p2[1] - p1[1]
    a = np.sin(dlat / 2) ** 2 + np.cos(p1[0]) * np.cos(p2[0]) * np.sin(dlon / 2) ** 2
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def cross_ri_pairs(df: pd.DataFrame, labels: np.ndarray, method: str) -> pd.DataFrame:
    """Turn cluster labels into candidate cross-RI record pairs.

    Only pairs whose two members come from *different* infrastructures are
    emitted: two ICOS stations 3 km apart are two stations, not a harmonisation
    problem.  Each pair carries the evidence that produced it, so a reviewer can
    judge it without re-running anything.
    """
    from rapidfuzz import fuzz

    work = df.copy()
    work["label"] = labels
    out = []
    for label, group in work[work.label >= 0].groupby("label"):
        if group.ri.nunique() < 2:
            continue
        records = group.to_dict("records")
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                if a["ri"] == b["ri"]:
                    continue
                a, b = sorted((a, b), key=lambda r: r["ri"])
                out.append(
                    {
                        "method": method,
                        "cluster": int(label),
                        "ri_a": a["ri"],
                        "record_id_a": a["record_id"],
                        "source_id_a": a["source_id"],
                        "name_a": a["name"],
                        "ri_b": b["ri"],
                        "record_id_b": b["record_id"],
                        "source_id_b": b["source_id"],
                        "name_b": b["name"],
                        "distance_km": round(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), 3),
                        "name_similarity": round(
                            fuzz.token_set_ratio(a["name_norm"], b["name_norm"]) / 100.0, 3
                        ),
                        "uri_a": a["uri"],
                        "uri_b": b["uri"],
                    }
                )
    cols = [
        "method", "cluster", "ri_a", "record_id_a", "source_id_a", "name_a",
        "ri_b", "record_id_b", "source_id_b", "name_b",
        "distance_km", "name_similarity", "uri_a", "uri_b",
    ]
    frame = pd.DataFrame(out, columns=cols)
    if frame.empty:
        return frame
    return frame.sort_values(["distance_km", "name_similarity"], ascending=[True, False]).reset_index(drop=True)


def sweep_eps(df: pd.DataFrame, eps_values, min_samples: int = 2) -> pd.DataFrame:
    """Run DBSCAN across a range of eps and record what each choice buys.

    Reported per eps: how many clusters, how much of the data is left as noise,
    how many candidate cross-RI pairs appear, and how many clusters swallow more
    than one station from the *same* RI - the signature of over-merging.
    """
    rows = []
    for eps in eps_values:
        labels = dbscan_labels(df, eps_km=eps, min_samples=min_samples)
        work = df.copy()
        work["label"] = labels
        clustered = work[work.label >= 0]
        by_label = clustered.groupby("label")
        n_clusters = int(clustered.label.nunique())
        cross = int(sum(1 for _, g in by_label if g.ri.nunique() >= 2))
        over = int(sum(1 for _, g in by_label if (g.ri.value_counts() > 1).any()))
        rows.append(
            {
                "eps_km": eps,
                "n_clusters": n_clusters,
                "n_noise": int((work.label < 0).sum()),
                "noise_fraction": round(float((work.label < 0).mean()), 4),
                "n_cross_ri_clusters": cross,
                "n_cross_ri_pairs": len(cross_ri_pairs(df, labels, "dbscan")),
                "n_same_ri_overmerged": over,
            }
        )
    return pd.DataFrame(rows)
