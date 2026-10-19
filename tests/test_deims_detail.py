"""Offline tests for the DEIMS detail enrichment of the Finnish eLTER sites.

``tests/data/deims_detail_sample.json`` holds three real records trimmed from
``GET https://deims.org/api/sites/{uuid}`` (retrieved 2026-10-19): Hyytiälä (a
12-vertex polygon, eleven networks), Lompolojankka (no boundary) and Lake Päijänne
(a MultiPolygon). Only title, id, siteType, boundary, centre point, country and the
network list were kept; the ``contact`` block (site-manager names and e-mails) was
dropped on purpose and a test below guards against it coming back.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from ri_harmonize import deims_detail as dd
from ri_harmonize.schema import COLUMNS

SAMPLE = Path(__file__).parent / "data" / "deims_detail_sample.json"
HYY = "663dac80-211d-4c19-a356-04ee0da0f0eb"
LOM = "e6b372ee-f310-49fd-9d0d-2a8306a06b64"
PAI = "28a399bc-e90f-43c2-a17d-2556b9644868"


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _stations(sample) -> pd.DataFrame:
    rows = [dict(ri="eLTER", record_id=u, source_id=u, id_scheme="DEIMS-SDR UUID", uri=f"https://deims.org/{u}",
                 name=p["title"], name_norm="", lat=61.0, lon=24.0, elevation_m=None, country="",
                 geometry_kind="centroid_of_polygon", station_class="eLTER site", extra_ids="{}")
            for u, p in sample.items()]
    rows.append(dict(ri="eLTER", record_id="other", source_id="other", id_scheme="DEIMS-SDR UUID", uri="",
                     name="Wadden Sea - Netherlands", name_norm="", lat=53.0, lon=5.0, elevation_m=None, country="",
                     geometry_kind="centroid_of_polygon", station_class="eLTER site", extra_ids="{}"))
    rows.append(dict(ri="ICOS", record_id="i1", source_id="I1", id_scheme="ICOS station code", uri="",
                     name="Suffix - Finland", name_norm="", lat=61.0, lon=24.0, elevation_m=None, country="FI",
                     geometry_kind="point", station_class="x", extra_ids="{}"))
    return pd.DataFrame(rows, columns=COLUMNS)


def test_fixture_carries_no_contact_data():
    text = SAMPLE.read_text(encoding="utf-8").lower()
    assert "@" not in text and "contact" not in text and "orcid" not in text


def test_extract_detail_reads_boundary_type_country_and_networks(sample):
    hyy = dd.extract_detail(sample[HYY])
    assert hyy["site_type"] == "Stationary land-based site"
    assert hyy["country"] == "Finland"
    assert hyy["boundary_wkt"].startswith("POLYGON ((24.295192 61.850177")
    assert len(hyy["networks"]) == 11
    icos = next(n for n in hyy["networks"] if n["name"] == "ICOS")
    assert icos["verified"] is True and "ES_FI-Hyy" in icos["siteCode"] and "ES_FI-Kvr" in icos["siteCode"]
    assert dd.extract_detail(sample[PAI])["boundary_wkt"].startswith("MULTIPOLYGON")


def test_missing_boundary_and_site_type_give_none(sample):
    lom = dd.extract_detail(sample[LOM])
    assert lom["boundary_wkt"] is None and lom["site_type"] is None and lom["country"] == "Finland"


def test_extract_detail_never_copies_the_contact_block(sample):
    payload = json.loads(json.dumps(sample[HYY]))
    payload["attributes"]["contact"] = {"siteManager": [{"name": "Test Person", "email": "placeholder-address"}]}
    assert "Test Person" not in json.dumps(dd.extract_detail(payload))
    assert "placeholder-address" not in json.dumps(dd.extract_detail(payload))


def test_finnish_site_ids_use_the_title_suffix_for_elter_only(sample):
    stations = _stations(sample)
    assert dd.finnish_site_ids(stations) == sorted([HYY, LOM, PAI])    # not 'other', not the ICOS row


def test_enrich_sets_polygon_or_point_country_and_extra_ids(sample):
    stations = _stations(sample)
    out, check = dd.enrich_stations(stations, sample)
    assert list(out.columns) == COLUMNS
    by = out.set_index("record_id")
    assert by.loc[HYY, "geometry_kind"] == "polygon" and by.loc[PAI, "geometry_kind"] == "polygon"
    assert by.loc[LOM, "geometry_kind"] == "point"
    assert by.loc[HYY, "country"] == "FI"
    extra = json.loads(by.loc[HYY, "extra_ids"])
    assert extra["boundary_wkt"].startswith("POLYGON") and extra["deims_country"] == "Finland"
    assert extra["deims_site_type"] == "Stationary land-based site" and len(extra["deims_networks"]) == 11
    assert "boundary_wkt" not in json.loads(by.loc[LOM, "extra_ids"])
    assert by.loc["other", "geometry_kind"] == "centroid_of_polygon" and by.loc["other", "country"] == ""
    assert check == {"n_title_suffix": 3, "n_detail_country_finland": 3, "country_mismatches": [], "n_polygon": 2,
                     "n_without_polygon": 1, "without_polygon": [{"record_id": LOM, "name": "Lompolojankka - Finland"}]}
    assert stations.loc[stations.record_id == HYY, "geometry_kind"].iloc[0] == "centroid_of_polygon"   # input untouched


def test_country_disagreement_is_reported_not_hidden(sample):
    odd = json.loads(json.dumps(sample))
    odd[LOM]["attributes"]["geographic"]["country"] = ["Sweden"]
    out, check = dd.enrich_stations(_stations(sample), odd)
    assert check["n_detail_country_finland"] == 2
    assert check["country_mismatches"] == [{"record_id": LOM, "name": "Lompolojankka - Finland", "detail_country": "Sweden"}]
    assert out.set_index("record_id").loc[LOM, "country"] == ""


def test_unknown_record_raises(sample):
    with pytest.raises(KeyError):
        dd.enrich_stations(_stations(sample), {"not-in-table": sample[HYY]})


def test_offline_mode_refuses_to_invent_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        dd.fetch_details(tmp_path, [HYY], offline=True)


def test_live_fetch_caches_bytes_verbatim_and_records_checksum(tmp_path, monkeypatch, sample):
    raws = {u: json.dumps(p, ensure_ascii=False).encode("utf-8") for u, p in sample.items()}
    calls = []

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response(raws[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(dd.requests, "get", fake_get)
    monkeypatch.setattr(dd, "PAUSE_SECONDS", 0)
    payloads = dd.fetch_details(tmp_path, [HYY, LOM])
    assert calls == [f"https://deims.org/api/sites/{HYY}", f"https://deims.org/api/sites/{LOM}"]
    assert (tmp_path / "deims_detail" / f"{HYY}.json").read_bytes() == raws[HYY]
    assert payloads[HYY]["title"] == sample[HYY]["title"]
    entry = json.loads((tmp_path / "manifest.json").read_text())["sources"]["deims_detail"]
    page = next(p for p in entry["pages"] if p["id"] == HYY)
    assert page["sha256"] == hashlib.sha256(raws[HYY]).hexdigest() and page["bytes"] == len(raws[HYY])
    assert page["retrieved_at"] and entry["endpoint"].startswith("https://deims.org/api/sites/")

    dd.fetch_details(tmp_path, [HYY, LOM], offline=True)            # served from the cache
    assert len(calls) == 2
