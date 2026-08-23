import numpy as np
import pandas as pd
import pytest

from ri_harmonize import cluster as cl
from ri_harmonize import evaluate as ev
from ri_harmonize import geo, sources
from ri_harmonize.schema import COLUMNS, normalise_name

import fixtures


@pytest.fixture()
def stations(tmp_path):
    fixtures.write_all(tmp_path)
    icos = sources.fetch_icos(tmp_path, offline=True)
    deims = sources.fetch_deims(tmp_path, offline=True)
    return pd.concat([icos, deims], ignore_index=True)


def test_adapters_emit_the_canonical_schema(stations):
    assert list(stations.columns) == COLUMNS
    assert set(stations.ri) == {"ICOS", "eLTER"}
    assert stations.lat.between(-90, 90).all()
    assert stations.lon.between(-180, 180).all()


def test_wkt_is_parsed_longitude_first(stations):
    hyy = stations[(stations.ri == "eLTER") & stations.name.str.contains("Hyytiala")].iloc[0]
    assert 61 < hyy.lat < 63          # would be ~24 if lon/lat were swapped
    assert 23 < hyy.lon < 26


def test_wigos_id_is_kept_as_a_secondary_identifier(stations):
    wao = stations[(stations.ri == "ICOS") & (stations.source_id == "WAO")].iloc[0]
    assert "0-20008-0-WAO" in wao.extra_ids
    assert wao.id_scheme == "ICOS station code"


def test_haversine_matches_a_known_distance():
    # Helsinki -> Tampere is roughly 160 km.
    d = cl.haversine_km(60.1699, 24.9384, 61.4978, 23.7610)
    assert 150 < d < 175


def test_dbscan_finds_colocated_pairs_and_leaves_isolated_records_alone(stations):
    labels = cl.dbscan_labels(stations, eps_km=5.0)
    pairs = cl.cross_ri_pairs(stations, labels, "dbscan")
    matched = set(pairs.id_a) | set(pairs.id_b)
    assert {"SMR", "ZOT", "HPB"} <= matched      # the three genuinely co-located places
    assert "KRE" not in matched                  # 38 km apart: correctly not merged
    assert (labels < 0).sum() > 0                # isolated records stay noise


def test_only_cross_infrastructure_pairs_are_emitted(stations):
    labels = cl.dbscan_labels(stations, eps_km=50.0)
    pairs = cl.cross_ri_pairs(stations, labels, "dbscan")
    assert (pairs.ri_a != pairs.ri_b).all()


def test_larger_eps_never_finds_fewer_pairs(stations):
    sweep = cl.sweep_eps(stations, [1, 5, 25])
    assert sweep.n_cross_ri_pairs.is_monotonic_increasing
    assert sweep.noise_fraction.is_monotonic_decreasing


def test_kmeans_baseline_forces_every_record_into_a_cluster(stations):
    labels = cl.kmeans_labels(stations, k=4)
    assert (labels >= 0).all()
    assert len(set(labels)) == 4


def test_buffer_intersection_agrees_with_dbscan_on_the_obvious_cases(stations):
    pairs = geo.buffer_overlap_pairs(stations, radius_km=3.0)
    assert {"SMR", "ZOT"} <= (set(pairs.id_a) | set(pairs.id_b))
    assert (pairs.ri_a != pairs.ri_b).all()


def test_scoring_is_order_independent_and_counts_only_reviewed_pairs():
    candidates = pd.DataFrame([
        {"ri_a": "ICOS", "id_a": "SMR", "ri_b": "eLTER", "id_b": "u1"},
        {"ri_a": "ICOS", "id_a": "KRE", "ri_b": "eLTER", "id_b": "u2"},
    ])
    truth = pd.DataFrame([
        {"ri_a": "eLTER", "id_a": "u1", "ri_b": "ICOS", "id_b": "SMR", "same_place": "yes"},
        {"ri_a": "ICOS", "id_a": "KRE", "ri_b": "eLTER", "id_b": "u2", "same_place": "no"},
        {"ri_a": "ICOS", "id_a": "MHD", "ri_b": "eLTER", "id_b": "u9", "same_place": "yes"},
    ])
    s = ev.score(candidates, truth)
    assert s["true_positives"] == 1 and s["false_positives"] == 1 and s["false_negatives"] == 1
    assert s["precision"] == 0.5 and s["recall"] == 0.5


def test_review_sheet_excludes_already_adjudicated_pairs(stations):
    labels = cl.dbscan_labels(stations, eps_km=5.0)
    candidates = cl.cross_ri_pairs(stations, labels, "dbscan")
    first = candidates.iloc[0]
    truth = pd.DataFrame([{"ri_a": first.ri_a, "id_a": first.id_a, "ri_b": first.ri_b,
                           "id_b": first.id_b, "same_place": "yes"}])
    sheet = ev.make_review_sheet(candidates, truth)
    assert len(sheet) == len(candidates) - 1
    assert "same_place" in sheet.columns


def test_name_normalisation_drops_noise_tokens_and_diacritics():
    assert normalise_name("Hyytiälä Station (SMEAR II)") == "hyytiala smear ii"
    assert normalise_name(None) == ""


def test_offline_mode_refuses_to_invent_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        sources.fetch_icos(tmp_path, offline=True)
