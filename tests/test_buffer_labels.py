"""Buffer pairs must carry the labels of the record named in each column.

The frame lists eLTER, then ICOS, then ACTRIS rows, which is the input order that
made the earlier code attach side-b labels to side-a columns (pairs are keyed
alphabetically: ACTRIS < ICOS < eLTER). ``EXPECTED_PAIRS`` is the pair set,
ordering and distances that code produced for this frame; the fix must not
change any of it, only the label columns.
"""

import pandas as pd

from ri_harmonize import geo

_ROWS = [
    ("eLTER", "e1", "e1", "Alpha LTER", 60.00, 24.02),
    ("ICOS", "i1", "I1", "Alpha ICOS", 60.01, 24.00),
    ("ICOS", "i2", "I2", "Beta ICOS", 50.02, 10.00),
    ("ACTRIS", "a1", "a1", "Alpha ACTRIS", 60.00, 24.00),
    ("ACTRIS", "a2", "a2", "Beta ACTRIS", 50.00, 10.00),
    ("ACTRIS", "a3", "a3", "Far away", 40.00, 0.00),
]
# ri_a, record_id_a, ri_b, record_id_b, distance_km, name_similarity
EXPECTED_PAIRS = [
    ("ACTRIS", "a1", "eLTER", "e1", 1.115, 0.727),
    ("ACTRIS", "a1", "ICOS", "i1", 1.115, 0.727),
    ("ICOS", "i1", "eLTER", "e1", 1.584, 0.667),
    ("ACTRIS", "a2", "ICOS", "i2", 2.224, 0.700),
]


def _frame() -> pd.DataFrame:
    return pd.DataFrame([
        dict(ri=ri, record_id=rid, source_id=sid, name=name, name_norm=name.lower(), lat=lat, lon=lon,
             uri=f"http://example.org/{rid}")
        for ri, rid, sid, name, lat, lon in _ROWS
    ])


def test_buffer_pairs_distances_and_similarity_are_unchanged():
    pairs = geo.buffer_overlap_pairs(_frame(), radius_km=5.0)
    got = list(pairs[["ri_a", "record_id_a", "ri_b", "record_id_b", "distance_km", "name_similarity"]]
               .itertuples(index=False, name=None))
    assert got == EXPECTED_PAIRS


def test_buffer_labels_belong_to_the_record_in_the_same_column():
    stations = _frame().set_index(["ri", "record_id"])
    pairs = geo.buffer_overlap_pairs(_frame(), radius_km=5.0)
    assert len(pairs) == len(EXPECTED_PAIRS)
    for _, row in pairs.iterrows():
        for side in ("a", "b"):
            rec = stations.loc[(row[f"ri_{side}"], row[f"record_id_{side}"])]
            assert row[f"source_id_{side}"] == rec.source_id
            assert row[f"name_{side}"] == rec["name"]
            assert row[f"uri_{side}"] == rec.uri
