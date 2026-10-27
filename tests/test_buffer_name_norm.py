"""Tests that the buffer method computes name_similarity on normalised names."""

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from ri_harmonize import cluster, geo
from ri_harmonize.schema import normalise_name

from test_buffer_labels import EXPECTED_PAIRS, _frame


def _two_record_frame():
    a_name = "Hyytiälä Station (SMEAR II)"
    b_name = "HYYTIALA smear-ii"
    return pd.DataFrame([
        dict(ri="ACTRIS", record_id="a1", source_id="a1", name=a_name,
             name_norm=normalise_name(a_name), lat=61.85, lon=24.283, uri="u/a1"),
        dict(ri="ICOS", record_id="i1", source_id="i1", name=b_name,
             name_norm=normalise_name(b_name), lat=61.847, lon=24.294, uri="u/i1"),
    ]), a_name, b_name


def test_buffer_uses_normalised_name_like_dbscan_and_kmeans():
    frame, a_name, b_name = _two_record_frame()
    buffer = geo.buffer_overlap_pairs(frame, radius_km=5.0)
    assert len(buffer) == 1
    row = buffer.iloc[0]
    assert row["name_similarity"] == 1.0

    labels = np.array([0, 0])
    dbscan = cluster.cross_ri_pairs(frame, labels, "dbscan").iloc[0]
    kmeans = cluster.cross_ri_pairs(frame, labels, "kmeans").iloc[0]
    assert dbscan["name_similarity"] == row["name_similarity"]
    assert kmeans["name_similarity"] == row["name_similarity"]

    raw = round(fuzz.token_set_ratio(a_name, b_name) / 100.0, 3)
    assert raw != row["name_similarity"], (
        f"fixture must have different raw and normalised similarities; "
        f"raw={raw}, normalised={row['name_similarity']}"
    )


def test_pair_set_and_distance_unchanged_when_name_norm_blanked():
    pairs_before = geo.buffer_overlap_pairs(_frame(), radius_km=5.0)
    expected_keys = {(r[0], r[1], r[2], r[3]) for r in EXPECTED_PAIRS}
    got_keys = {(r.ri_a, r.record_id_a, r.ri_b, r.record_id_b) for r in pairs_before.itertuples()}
    assert got_keys == expected_keys

    frame = _frame()
    frame["name_norm"] = ""
    pairs_after = geo.buffer_overlap_pairs(frame, radius_km=5.0)

    for col in ("ri_a", "record_id_a", "ri_b", "record_id_b", "distance_km"):
        assert list(pairs_after[col]) == list(pairs_before[col]), (
            f"column {col} changed when name_norm was blanked"
        )
