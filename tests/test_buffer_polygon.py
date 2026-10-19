"""Polygon-aware buffer matching (opt-in sibling of ``buffer_overlap_pairs``).

The Hyytiälä case uses the real DEIMS boundary from ``tests/data/deims_detail_sample.json``
and the coordinates of the other records as pulled on 2026-10-19: ICOS ``SMR``
(61.8474, 24.2947), ICOS ``FI-Hyy`` (61.84741, 24.29477), ACTRIS ``ko6m`` (61.85, 24.283333,
as in ``tests/data/actris_facilities_sample.json``) and ICOS ``FI-Kvr`` (61.84662, 24.2804).
Distances to the polygon were cross-checked in a local azimuthal-equidistant projection
(ko6m 488.7 m, FI-Kvr 553.1 m; EPSG:3035 gives about 0.5 % more for ko6m).
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import wkt

from ri_harmonize import deims_detail, geo
from ri_harmonize.schema import COLUMNS, normalise_name
from test_buffer_labels import EXPECTED_PAIRS, _frame

SAMPLE = json.loads((Path(__file__).parent / "data" / "deims_detail_sample.json").read_text(encoding="utf-8"))
HYY = "663dac80-211d-4c19-a356-04ee0da0f0eb"


def _row(ri, rid, name, lat, lon, kind="point", extra=None):
    return dict(ri=ri, record_id=rid, source_id=rid, id_scheme="x", uri=f"http://example.org/{rid}", name=name,
                name_norm=normalise_name(name), lat=lat, lon=lon, elevation_m=None, country="", geometry_kind=kind,
                station_class="x", extra_ids=json.dumps(extra or {}))


def _hyytiala() -> pd.DataFrame:
    rows = [
        _row("eLTER", HYY, "Hyytiälä SMEAR II LTER - Finland", 61.8474, 24.295, "centroid_of_polygon"),
        _row("ICOS", "SMR", "Hyytiälä", 61.8474, 24.2947),
        _row("ICOS", "FI-Hyy", "Hyytiala", 61.84741, 24.29477),
        _row("ACTRIS", "ko6m", "Hyytiälä", 61.85, 24.283333),
        _row("ICOS", "FI-Kvr", "Kuivajarvi", 61.84662, 24.2804),
    ]
    stations = pd.DataFrame(rows, columns=COLUMNS)
    return deims_detail.enrich_stations(stations, {HYY: SAMPLE[HYY]})[0]


def _distances(pairs):
    return {r.source_id_a if r.ri_b == "eLTER" else r.source_id_b: r.polygon_distance_m
            for r in pairs[(pairs.ri_a == "eLTER") | (pairs.ri_b == "eLTER")].itertuples()}


def test_hyytiala_inside_points_are_at_zero_and_outside_points_at_their_distance():
    pairs = geo.buffer_overlap_pairs_polygon(_hyytiala(), radius_km=5.0)
    got = _distances(pairs)
    assert got["SMR"] == 0.0 and got["FI-Hyy"] == 0.0
    assert 485 <= got["ko6m"] <= 495          # about 487-491 m outside
    assert 548 <= got["FI-Kvr"] <= 558        # about 552 m outside
    assert set(pairs.geometry_kind_a) | set(pairs.geometry_kind_b) == {"point", "polygon"}


def test_polygon_is_evidence_with_a_buffer_not_a_strict_inside_test():
    stations = _hyytiala()
    narrow = _distances(geo.buffer_overlap_pairs_polygon(stations, radius_km=0.4))
    assert set(narrow) == {"SMR", "FI-Hyy"}                          # both outside points need more than 400 m
    middle = _distances(geo.buffer_overlap_pairs_polygon(stations, radius_km=0.5))
    assert set(middle) == {"SMR", "FI-Hyy", "ko6m"}                  # ko6m (about 490 m) in, FI-Kvr (about 553 m) out
    wide = _distances(geo.buffer_overlap_pairs_polygon(stations, radius_km=0.6))
    assert set(wide) == {"SMR", "FI-Hyy", "ko6m", "FI-Kvr"}


def test_centre_point_distance_is_kept_alongside_the_polygon_distance():
    pairs = geo.buffer_overlap_pairs_polygon(_hyytiala(), radius_km=5.0)
    smr = pairs[(pairs.source_id_a == "SMR") | (pairs.source_id_b == "SMR")].iloc[0]
    assert smr.distance_km == 0.016 and smr.polygon_distance_m == 0.0
    assert smr.method == "buffer_polygon"


def test_pairs_without_any_polygon_match_the_plain_buffer_and_leave_polygon_distance_empty():
    pairs = geo.buffer_overlap_pairs_polygon(_frame(), radius_km=5.0)
    got = list(pairs[["ri_a", "record_id_a", "ri_b", "record_id_b", "distance_km", "name_similarity"]]
               .itertuples(index=False, name=None))
    assert sorted(got) == sorted(EXPECTED_PAIRS)
    assert pairs.polygon_distance_m.isna().all()


def test_a_large_polygon_matches_through_its_edge_not_its_centre():
    # 0.2 deg x 0.1 deg box at 60N; the point sits ~3 km east of the box edge but ~8 km from its centre.
    box = "POLYGON ((23.9 59.95, 24.1 59.95, 24.1 60.05, 23.9 60.05, 23.9 59.95))"
    far_east = 24.1 + 3.0 / (111.32 * np.cos(np.radians(60.0)))
    rows = [_row("eLTER", "big", "Big site", 60.0, 24.0, "polygon", {"boundary_wkt": box}),
            _row("ICOS", "pt", "Station", 60.0, far_east)]
    frame = pd.DataFrame(rows, columns=COLUMNS)
    pairs = geo.buffer_overlap_pairs_polygon(frame, radius_km=5.0)
    assert len(pairs) == 1 and 2900 < pairs.polygon_distance_m.iloc[0] < 3100
    assert pairs.distance_km.iloc[0] > 5.0
    assert geo.buffer_overlap_pairs(frame, radius_km=5.0).empty     # the plain point buffer misses it


def test_multipolygon_boundary_is_used_and_same_ri_pairs_are_never_emitted():
    pai = "28a399bc-e90f-43c2-a17d-2556b9644868"
    inside = wkt.loads(SAMPLE[pai]["attributes"]["geographic"]["boundaries"]).representative_point()
    rows = [_row("eLTER", pai, "Lake Päijänne LTER - Finland", 61.85, 25.48, "centroid_of_polygon"),
            _row("eLTER", "twin", "Another eLTER", 61.85, 25.48),
            _row("ICOS", "in", "Inside the lake polygon", inside.y, inside.x)]
    frame = deims_detail.enrich_stations(pd.DataFrame(rows, columns=COLUMNS), {pai: SAMPLE[pai]})[0]
    assert frame.set_index("record_id").loc[pai, "geometry_kind"] == "polygon"
    pairs = geo.buffer_overlap_pairs_polygon(frame, radius_km=0.1)
    assert list(zip(pairs.ri_a, pairs.ri_b)) == [("ICOS", "eLTER")]       # no eLTER-eLTER pair
    assert pairs.polygon_distance_m.iloc[0] == 0.0 and pairs.distance_km.iloc[0] > 0.1


def test_empty_frame_returns_the_documented_columns():
    assert list(geo.buffer_overlap_pairs_polygon(pd.DataFrame(columns=COLUMNS)).columns) == geo.POLYGON_PAIR_COLUMNS
