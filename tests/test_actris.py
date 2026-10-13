"""Offline tests for the ACTRIS adapter.

``tests/data/actris_facilities_sample.json`` holds six real records trimmed from
``GET https://prod-actris-md.nilu.no/api/facilities`` (retrieved 2026-10-12):
Hyytiälä, Sonnblick, a record with 2D coordinates, a record without a location
(a research vessel), an inactive facility, and a record without a ``uri``.
"""

import hashlib
import json
from pathlib import Path

import pytest

from ri_harmonize import actris
from ri_harmonize.schema import COLUMNS

SAMPLE = Path(__file__).parent / "data" / "actris_facilities_sample.json"


@pytest.fixture()
def cache(tmp_path):
    (tmp_path / actris.ACTRIS_CACHE_FILE).write_bytes(SAMPLE.read_bytes())
    return tmp_path


@pytest.fixture()
def frame(cache):
    return actris.fetch_actris(cache, offline=True)


def test_actris_adapter_emits_the_canonical_schema(frame):
    assert list(frame.columns) == COLUMNS
    assert set(frame.ri) == {"ACTRIS"}
    assert frame.lat.between(-90, 90).all() and frame.lon.between(-180, 180).all()


def test_record_without_location_is_dropped_not_guessed(frame):
    assert "bwkw" not in set(frame.record_id)    # RV Helmer Hanssen has no location
    assert len(frame) == 5


def test_coordinates_are_read_longitude_first_with_elevation(frame):
    hyy = frame[frame.record_id == "ko6m"].iloc[0]
    assert hyy["name"] == "Hyytiälä"
    assert (hyy.lat, hyy.lon, hyy.elevation_m) == (61.85, 24.283333, 181.0)   # swapped would give lat ~24


def test_two_dimensional_coordinates_leave_elevation_empty(frame):
    assert frame[frame.record_id == "2bq0"].elevation_m.isna().all()


def test_identifiers_are_verbatim_and_scheme_is_stored(frame):
    hyy = frame[frame.record_id == "ko6m"].iloc[0]
    assert hyy.source_id == "ko6m"
    assert hyy.id_scheme == "ACTRIS DVAS facility identifier"
    assert hyy.uri == "https://data.actris.eu/facility/ko6m"
    extra = json.loads(hyy.extra_ids)
    assert extra["ebas_station_code"] == "FI0050R"
    assert extra["gawid_uri"] == "SMR"
    assert extra["identifier_type"] == "other PID"


def test_status_fields_survive_in_extra_ids_and_inactive_records_are_kept(frame):
    inactive = frame[frame.record_id == "0tlr"].iloc[0]
    assert json.loads(inactive.extra_ids)["active"] is False
    assert json.loads(frame[frame.record_id == "ko6m"].iloc[0].extra_ids)["actris_national_facility"] == "labelled"


def test_missing_uri_stays_empty(frame):
    assert frame[frame.record_id == "tr4b"].iloc[0].uri == ""


def test_offline_mode_refuses_to_invent_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        actris.fetch_actris(tmp_path, offline=True)


def test_live_fetch_caches_bytes_verbatim_and_records_checksum(tmp_path, monkeypatch):
    raw = SAMPLE.read_bytes()

    class Response:
        content = raw

        def raise_for_status(self):
            pass

    monkeypatch.setattr(actris.requests, "get", lambda *a, **k: Response())
    frame = actris.fetch_actris(tmp_path)
    assert (tmp_path / actris.ACTRIS_CACHE_FILE).read_bytes() == raw
    entry = json.loads((tmp_path / "manifest.json").read_text())["sources"]["actris"]
    assert entry["endpoint"] == actris.ACTRIS_FACILITIES
    assert entry["pages"][0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["retrieved_at"] and len(frame) == 5
