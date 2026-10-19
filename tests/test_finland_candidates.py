"""Finland candidate table: scope, polygon-aware distance, thresholds, clusters, empty label columns.

Hyytiälä uses the real DEIMS boundary in ``tests/data/deims_detail_sample.json`` and the point
coordinates quoted in ``test_buffer_polygon.py``; the large-polygon case is synthetic.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from scripts import finland_candidates as fc
from ri_harmonize.schema import COLUMNS
from test_buffer_polygon import _hyytiala, _row

BIG_SQUARE = "POLYGON ((24.0 61.8, 24.3 61.8, 24.3 61.9, 24.0 61.9, 24.0 61.8))"  # about 16 km x 11 km


def _finnish(stations: pd.DataFrame) -> pd.DataFrame:
    stations = stations.copy()
    stations["country"] = "FI"
    return fc.finnish_records(stations)


def _table(stations, methods=None, max_km=fc.MAX_KM):
    fi = _finnish(stations)
    rec = fc.record_table(fi)
    dist = fc.pair_distances(fi, rec)
    return fi, rec, dist, fc.build_candidates(fi, rec, dist, methods, max_km)


def _key(row):
    return frozenset((row.source_id_a, row.source_id_b))


def test_scope_is_country_fi_only():
    stations = _hyytiala()
    stations["country"] = "FI"
    stations.loc[stations.source_id == "FI-Kvr", "country"] = "SE"
    assert "FI-Kvr" not in fc.finnish_records(stations).source_id.tolist()
    assert len(fc.finnish_records(stations)) == 4


def test_hyytiala_pairs_use_polygon_distance_and_skip_same_ri_pairs():
    _, _, _, table = _table(_hyytiala())
    assert len(table) == 7                       # 10 pairs of 5 records minus the 3 ICOS-ICOS pairs
    assert (table.ri_a != table.ri_b).all()
    by = {_key(r): r for r in table.itertuples()}
    elter = "663dac80-211d-4c19-a356-04ee0da0f0eb"
    assert by[frozenset(("SMR", elter))].polygon_distance_m == 0.0
    ko6m = by[frozenset(("ko6m", elter))]
    assert 485 <= ko6m.polygon_distance_m <= 495 and ko6m.distance_km_point > ko6m.distance_km_geometry
    assert 548 <= by[frozenset(("FI-Kvr", elter))].polygon_distance_m <= 558
    assert pd.isna(by[frozenset(("ko6m", "SMR"))].polygon_distance_m)   # neither record has a polygon
    assert frozenset(("ko6m", "FI-Kvr")) in by   # ICOS-ACTRIS pair, no polygon involved


def test_record_facts_are_per_side_and_label_columns_are_empty():
    _, _, _, table = _table(_hyytiala())
    row = table[(table.source_id_a == "SMR") & (table.ri_b == "eLTER")].iloc[0]
    assert not row.has_boundary_a and row.has_boundary_b and row.polygon_area_ha_b > 0
    assert row.site_type_b == "Stationary land-based site" and row.site_type_a == ""
    for column in fc.LABEL_COLUMNS:
        assert (table[column] == "").all()
    assert list(table.columns) == fc.COLUMNS


def test_hyytiala_schema_columns_are_kept_in_order():
    hyytiala = ["ri_a", "record_id_a", "source_id_a", "id_scheme_a", "name_a", "lat_a", "lon_a", "uri_a",
                "ri_b", "record_id_b", "source_id_b", "id_scheme_b", "name_b", "lat_b", "lon_b", "uri_b",
                "distance_km_dbscan", "distance_km_buffer", "distance_km_kmeans",
                "name_similarity_dbscan", "name_similarity_buffer", "name_similarity_kmeans",
                "methods", "same_place", "checked_by", "checked_at", "evidence", "match_type"]
    kept = [c for c in fc.COLUMNS if c in hyytiala]
    assert kept == hyytiala
    for new in ("polygon_distance_m", "polygon_area_ha_a", "site_type_a", "has_boundary_a", "cluster_id"):
        assert new in fc.COLUMNS


def test_distance_is_computed_once_and_thresholds_are_cumulative():
    stations = pd.concat([_hyytiala(), pd.DataFrame([_row("ACTRIS", "far", "Far away", 61.85, 24.60)], columns=COLUMNS)],
                         ignore_index=True)
    fi, _, dist, table = _table(stations)
    counts = fc.cumulative_counts(dist, fi)
    assert counts.threshold_km.tolist() == fc.THRESHOLDS_KM
    assert counts.pairs_geometry.is_monotonic_increasing
    assert int(counts[counts.threshold_km == 5].pairs_geometry.iloc[0]) == len(table)
    assert int(counts[counts.threshold_km == 20].pairs_geometry.iloc[0]) > len(table)   # "far" is ~15-20 km away
    assert not any(frozenset(("far",)) <= _key(r) for r in table.itertuples())
    assert len(dist) == len(dist.drop_duplicates(["i", "j"]))


def test_large_polygon_pairs_everything_inside_at_distance_zero():
    rows = [_row("eLTER", "big", "Big LTER - Finland", 61.85, 24.15, "polygon", {"boundary_wkt": BIG_SQUARE}),
            _row("ICOS", "inside", "Inside", 61.82, 24.28),      # ~14 km from the polygon centre point
            _row("ACTRIS", "outside", "Outside", 62.00, 24.15)]  # ~16.7 km north of the polygon
    fi, rec, dist, table = _table(pd.DataFrame(rows, columns=COLUMNS))
    assert len(table) == 1
    row = table.iloc[0]
    assert {row.source_id_a, row.source_id_b} == {"big", "inside"}
    assert row.polygon_distance_m == 0.0 and row.distance_km_point > fc.MAX_KM
    odd = fc.oddities(fi, rec, dist, table)
    assert len(odd["pairs_in_only_because_of_polygon"]) == 1
    assert odd["polygon_swallow"][0]["pairs_at_distance_0"] == 1


def test_clusters_are_connected_components_numbered_north_to_south():
    rows = [_row("ICOS", "n1", "North", 67.0, 24.0), _row("ACTRIS", "n2", "North b", 67.001, 24.0),
            _row("ICOS", "s1", "South", 60.0, 24.0), _row("ACTRIS", "s2", "South b", 60.001, 24.0),
            _row("eLTER", "s3", "South c", 60.0, 24.002), _row("ICOS", "lone", "Lone", 64.0, 24.0)]
    _, _, _, table = _table(pd.DataFrame(rows, columns=COLUMNS))
    ids = {_key(r): (r.cluster_id, r.cluster_size) for r in table.itertuples()}
    assert ids[frozenset(("n1", "n2"))] == (1, 2)
    assert {v for k, v in ids.items() if "s1" in k} == {(2, 3)}
    assert not any("lone" in k for k in ids)


def test_method_columns_merge_either_pair_order():
    rows = [_row("ICOS", "a", "Same", 61.0, 24.0), _row("ACTRIS", "b", "Same", 61.0, 24.001)]
    methods = pd.DataFrame([
        {"method": "dbscan", "ri_a": "ACTRIS", "record_id_a": "b", "ri_b": "ICOS", "record_id_b": "a", "distance_km": 0.05, "name_similarity": 1.0},
        {"method": "buffer", "ri_a": "ICOS", "record_id_a": "a", "ri_b": "ACTRIS", "record_id_b": "b", "distance_km": 0.06, "name_similarity": 0.9},
    ])
    _, _, _, table = _table(pd.DataFrame(rows, columns=COLUMNS), methods)
    row = table.iloc[0]
    assert (row.ri_a, row.ri_b) == ("ACTRIS", "ICOS")
    assert row.methods == "buffer,dbscan"
    assert row.distance_km_dbscan == 0.05 and row.distance_km_buffer == 0.06 and row.distance_km_kmeans == ""
    assert row.name_similarity_buffer == 0.9


def test_presence_check_reports_missing_records():
    stations = _hyytiala()
    fi = _finnish(stations)
    checks = {c["record"]: c for c in fc.presence_checks(fi, fc.record_table(fi))}
    assert checks["ICOS FI-Kvr (Kuivajärvi)"]["present"] is True
    assert checks["ICOS FI-Lom (Lompolojankka)"]["present"] is False


def _deims_with_icos(site_code, verified=True, name="ICOS"):
    return {"deims_networks": [{"name": name, "id": "x", "siteCode": site_code, "verified": verified},
                               {"name": "LTER Europe", "id": "y", "siteCode": "http://meta.icos-cp.eu/resources/stations/ES_FI-X", "verified": True}]}


def _linked_stations(site_code, verified=True):
    rows = [_row("eLTER", "site", "Some LTER - Finland", 61.0, 24.0, "point", _deims_with_icos(site_code, verified)),
            _row("ICOS", "FI-Hyy", "Hyytiala", 61.0, 24.0),
            _row("ICOS", "FI-Kvr", "Kuivajarvi", 61.001, 24.0),
            _row("ACTRIS", "act", "Act", 61.0, 24.001)]
    for r in rows[1:3]:
        r["record_id"] = f"http://meta.icos-cp.eu/resources/stations/ES_{r['source_id']}"
    return pd.DataFrame(rows, columns=COLUMNS)


def test_deims_icos_link_matches_exact_uri_across_http_https_and_lists_all_codes():
    listed = ("https://meta.icos-cp.eu/resources/stations/ES_FI-Hyy, "
              "http://meta.icos-cp.eu/resources/stations/ES_FI-Kvr/")
    _, _, _, table = _table(_linked_stations(listed, verified=False))
    by = {_key(r): r for r in table.itertuples()}
    hyy = by[frozenset(("FI-Hyy", "site"))]
    assert hyy.deims_lists_icos_station == True and hyy.deims_icos_sitecode_matched == "https://meta.icos-cp.eu/resources/stations/ES_FI-Hyy"  # noqa: E712
    assert hyy.deims_icos_sitecode_verified == False  # noqa: E712
    assert by[frozenset(("FI-Kvr", "site"))].deims_lists_icos_station == True  # noqa: E712
    assert hyy.deims_icos_sitecodes_listed == "https://meta.icos-cp.eu/resources/stations/ES_FI-Hyy;http://meta.icos-cp.eu/resources/stations/ES_FI-Kvr/"


def test_deims_icos_link_is_false_for_unlisted_station_and_blank_for_other_pairs():
    _, _, _, table = _table(_linked_stations("http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy"))
    by = {_key(r): r for r in table.itertuples()}
    kvr = by[frozenset(("FI-Kvr", "site"))]
    assert kvr.deims_lists_icos_station == False and kvr.deims_icos_sitecode_matched == ""  # noqa: E712
    assert "ES_FI-Hyy" in kvr.deims_icos_sitecodes_listed          # what the site does list stays visible
    assert by[frozenset(("act", "FI-Hyy"))].deims_lists_icos_station == ""   # ICOS-ACTRIS: not applicable
    assert by[frozenset(("act", "site"))].deims_lists_icos_station == ""     # ACTRIS-eLTER: not applicable


def test_deims_icos_link_ignores_non_icos_networks_and_suffix_lookalikes():
    stations = _linked_stations("http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy-extra")
    stations.at[0, "extra_ids"] = json.dumps(_deims_with_icos("http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy", name="ICOS Sweden"))
    _, _, _, table = _table(stations)
    assert not table.deims_lists_icos_station.eq(True).any()
