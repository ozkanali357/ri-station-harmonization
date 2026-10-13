import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.profile_sources as ps  # noqa: E402


INPUT_COLUMNS = [
    "ri",
    "record_id",
    "source_id",
    "id_scheme",
    "uri",
    "name",
    "name_norm",
    "lat",
    "lon",
    "elevation_m",
    "country",
    "geometry_kind",
    "station_class",
    "extra_ids",
]


@pytest.fixture
def tiny_df():
    rows = [
        # ICOS
        {
            "ri": "ICOS",
            "record_id": "r1",
            "source_id": "S1",
            "id_scheme": "ICOS station code",
            "uri": "",
            "name": "Alpha",
            "name_norm": "",
            "lat": "10",
            "lon": "20",
            "elevation_m": "100",
            "country": "DE",
            "geometry_kind": "point",
            "station_class": "A",
            "extra_ids": '{"wigos_id": "0-1"}',
        },
        {
            "ri": "ICOS",
            "record_id": "r2",
            "source_id": "S2",
            "id_scheme": "ICOS station code",
            "uri": "",
            "name": "Beta",
            "name_norm": "",
            "lat": "11",
            "lon": "21",
            "elevation_m": "",
            "country": "",
            "geometry_kind": "point",
            "station_class": "B",
            "extra_ids": "{}",
        },
        {
            "ri": "ICOS",
            "record_id": "r3",
            "source_id": "S3",
            "id_scheme": "ICOS station code",
            "uri": "",
            "name": "",
            "name_norm": "",
            "lat": "12",
            "lon": "22",
            "elevation_m": "300",
            "country": "FR",
            "geometry_kind": "point",
            "station_class": "A",
            "extra_ids": '{"wigos_id": "0-2"}',
        },
        # ACTRIS
        {
            "ri": "ACTRIS",
            "record_id": "a1",
            "source_id": "a1",
            "id_scheme": "ACTRIS DVAS facility identifier",
            "uri": "",
            "name": "Gamma",
            "name_norm": "",
            "lat": "30",
            "lon": "40",
            "elevation_m": "500",
            "country": "AT",
            "geometry_kind": "point",
            "station_class": "X",
            "extra_ids": '{"gawid_uri": "SNB"}',
        },
        {
            "ri": "ACTRIS",
            "record_id": "a2",
            "source_id": "a2",
            "id_scheme": "ACTRIS DVAS facility identifier",
            "uri": "",
            "name": "Delta",
            "name_norm": "",
            "lat": "31",
            "lon": "41",
            "elevation_m": "",
            "country": "",
            "geometry_kind": "point",
            "station_class": "Y",
            "extra_ids": "{}",
        },
        {
            "ri": "ACTRIS",
            "record_id": "a3",
            "source_id": "a3",
            "id_scheme": "ACTRIS DVAS facility identifier",
            "uri": "",
            "name": "Epsilon",
            "name_norm": "",
            "lat": "32",
            "lon": "42",
            "elevation_m": "700",
            "country": "BE",
            "geometry_kind": "point",
            "station_class": "X",
            "extra_ids": '{"gawid_uri": "XXX", "ebas_station_code": "BE01"}',
        },
        # eLTER
        {
            "ri": "eLTER",
            "record_id": "e1",
            "source_id": "e1",
            "id_scheme": "DEIMS-SDR UUID",
            "uri": "",
            "name": "Zeta",
            "name_norm": "",
            "lat": "50",
            "lon": "60",
            "elevation_m": "",
            "country": "",
            "geometry_kind": "centroid_of_polygon",
            "station_class": "LTER site",
            "extra_ids": "{}",
        },
        {
            "ri": "eLTER",
            "record_id": "e2",
            "source_id": "e2",
            "id_scheme": "DEIMS-SDR UUID",
            "uri": "",
            "name": "Eta",
            "name_norm": "",
            "lat": "51",
            "lon": "61",
            "elevation_m": "",
            "country": "",
            "geometry_kind": "centroid_of_polygon",
            "station_class": "LTSER site",
            "extra_ids": "{}",
        },
    ]
    return pd.DataFrame(rows, columns=INPUT_COLUMNS)


def _count(prof, ri, section, key):
    row = prof[(prof["ri"] == ri) & (prof["section"] == section) & (prof["key"] == key)]
    assert len(row) == 1, f"expected exactly one row for {ri}/{section}/{key}"
    return int(row.iloc[0]["count"])


def test_profile_counts(tiny_df):
    prof = ps.profile(tiny_df)

    assert _count(prof, "ICOS", "summary", "n_records") == 3
    assert _count(prof, "ACTRIS", "summary", "n_records") == 3
    assert _count(prof, "eLTER", "summary", "n_records") == 2

    assert _count(prof, "ICOS", "id_scheme", "ICOS station code") == 3
    assert _count(prof, "ACTRIS", "id_scheme", "ACTRIS DVAS facility identifier") == 3
    assert _count(prof, "eLTER", "id_scheme", "DEIMS-SDR UUID") == 2

    assert _count(prof, "ICOS", "geometry_kind", "point") == 3
    assert _count(prof, "eLTER", "geometry_kind", "centroid_of_polygon") == 2

    assert _count(prof, "ICOS", "extra_ids", "wigos_id") == 2
    assert _count(prof, "ICOS", "extra_ids", "empty_json") == 1
    assert _count(prof, "ACTRIS", "extra_ids", "gawid_uri") == 2
    assert _count(prof, "ACTRIS", "extra_ids", "ebas_station_code") == 1
    assert _count(prof, "ACTRIS", "extra_ids", "empty_json") == 1
    assert _count(prof, "eLTER", "extra_ids", "empty_json") == 2

    assert _count(prof, "ICOS", "country", "non_empty") == 2
    assert _count(prof, "ICOS", "country", "n_distinct") == 2
    icos_countries = prof[
        (prof["ri"] == "ICOS")
        & (prof["section"] == "country")
        & (prof["key"] == "distinct_values")
    ].iloc[0]
    assert icos_countries["value"] == "DE, FR"
    assert int(icos_countries["count"]) == 2

    assert _count(prof, "ACTRIS", "country", "non_empty") == 2
    actris_countries = prof[
        (prof["ri"] == "ACTRIS")
        & (prof["section"] == "country")
        & (prof["key"] == "distinct_values")
    ].iloc[0]
    assert actris_countries["value"] == "AT, BE"

    assert _count(prof, "eLTER", "country", "non_empty") == 0
    assert _count(prof, "eLTER", "country", "n_distinct") == 0

    assert _count(prof, "ICOS", "missing", "lat") == 0
    assert _count(prof, "ICOS", "missing", "lon") == 0
    assert _count(prof, "ICOS", "missing", "elevation_m") == 1
    assert _count(prof, "ICOS", "missing", "name") == 1
    assert _count(prof, "ACTRIS", "missing", "elevation_m") == 1
    assert _count(prof, "eLTER", "missing", "elevation_m") == 2

    elter_sc = prof[
        (prof["ri"] == "eLTER")
        & (prof["section"] == "station_class")
        & (prof["key"] != "n_distinct")
    ]
    assert list(elter_sc["key"]) == ["LTER site", "LTSER site"]
    assert list(elter_sc["count"].astype(int)) == [1, 1]
    assert _count(prof, "eLTER", "station_class", "n_distinct") == 2

    icos_sc = prof[
        (prof["ri"] == "ICOS")
        & (prof["section"] == "station_class")
        & (prof["key"] != "n_distinct")
    ]
    assert list(icos_sc["key"]) == ["A", "B"]
    assert list(icos_sc["count"].astype(int)) == [2, 1]


def test_main_writes_outputs(tmp_path, monkeypatch, tiny_df):
    input_csv = tmp_path / "stations_harmonised.csv"
    tiny_df.to_csv(input_csv, index=False)

    monkeypatch.setattr(ps, "INPUT_CSV", input_csv)
    monkeypatch.setattr(ps, "OUT_CSV", tmp_path / "source_profile.csv")
    monkeypatch.setattr(ps, "OUT_MD", tmp_path / "source_profile.md")
    monkeypatch.setattr(ps, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(ps, "RAW_ACTRIS", tmp_path / "raw" / "actris_facilities.json")

    ps.main()

    assert (tmp_path / "source_profile.csv").exists()
    assert (tmp_path / "source_profile.md").exists()

    md = (tmp_path / "source_profile.md").read_text(encoding="utf-8")
    assert "shared GAW" not in md