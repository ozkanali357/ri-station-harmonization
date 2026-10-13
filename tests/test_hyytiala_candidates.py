import sys
from pathlib import Path

# Add the root directory to sys.path so pytest can find the scripts folder
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Then your existing imports:
import pandas as pd
import pytest
from scripts.hyytiala_candidates import process_candidates, TARGETS

@pytest.fixture
def dummy_stations():
    return pd.DataFrame({
        "ri": ["ICOS", "ICOS", "eLTER", "ACTRIS"],
        "record_id": [
            "http://meta.icos-cp.eu/resources/stations/AS_SMR",
            "http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy",
            "663dac80-211d-4c19-a356-04ee0da0f0eb",
            "ko6m"
        ],
        "id_scheme": ["ICOS station code", "ICOS station code", "DEIMS-SDR UUID", "ACTRIS DVAS facility identifier"],
        "lat": [61.84740, 61.84741, 61.84740, 61.85000],
        "lon": [24.294700, 24.294770, 24.295000, 24.283333],
        "uri": ["", "", "", ""]
    })

@pytest.fixture
def dummy_candidates(tmp_path, monkeypatch):
    # Override OUT path
    monkeypatch.setattr("scripts.hyytiala_candidates.OUT", tmp_path)
    
    # Create dummy CSVs
    dbscan = pd.DataFrame({
        "method": ["dbscan"],
        "ri_a": ["ACTRIS"], "record_id_a": ["ko6m"], "source_id_a": ["ko6m"], "name_a": ["Hyytiälä"],
        "ri_b": ["ICOS"], "record_id_b": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"], "source_id_b": ["SMR"], "name_b": ["Hyytiälä"],
        "distance_km": [0.663], "name_similarity": [1.0], "uri_a": ["https://data.actris.eu/facility/ko6m"], "uri_b": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"]
    })
    dbscan.to_csv(tmp_path / "candidate_pairs_dbscan.csv", index=False)
    
    buffer = pd.DataFrame({
        "method": ["buffer"],
        "ri_a": ["ICOS"], "record_id_a": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"], "source_id_a": ["SMR"], "name_a": ["Hyytiälä"],
        "ri_b": ["eLTER"], "record_id_b": ["663dac80-211d-4c19-a356-04ee0da0f0eb"], "source_id_b": ["663dac80-211d-4c19-a356-04ee0da0f0eb"], "name_b": ["Hyytiälä SMEAR II LTER - Finland"],
        "distance_km": [0.016], "name_similarity": [1.0], "uri_a": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"], "uri_b": ["https://deims.org/663dac80-211d-4c19-a356-04ee0da0f0eb"]
    })
    buffer.to_csv(tmp_path / "candidate_pairs_buffer.csv", index=False)

    kmeans = pd.DataFrame({
        "method": ["kmeans"],
        "ri_a": ["ACTRIS"], "record_id_a": ["ko6m"], "source_id_a": ["ko6m"], "name_a": ["Hyytiälä"],
        "ri_b": ["ICOS"], "record_id_b": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"], "source_id_b": ["SMR"], "name_b": ["Hyytiälä"],
        "distance_km": [0.670], "name_similarity": [0.9], "uri_a": ["https://data.actris.eu/facility/ko6m"], "uri_b": ["http://meta.icos-cp.eu/resources/stations/AS_SMR"]
    })
    kmeans.to_csv(tmp_path / "candidate_pairs_kmeans.csv", index=False)

def test_hyytiala_candidates_filtering_and_merging(dummy_stations, dummy_candidates):
    result = process_candidates(dummy_stations)
    
    assert result is not None
    assert len(result) == 2  # ACTRIS-ICOS and ICOS-eLTER
    
    # Check ACTRIS-ICOS row
    actris_icos = result[(result.ri_a == "ACTRIS") & (result.ri_b == "ICOS")].iloc[0]
    assert actris_icos["distance_km_dbscan"] == 0.663
    assert actris_icos["distance_km_kmeans"] == 0.670
    assert actris_icos["distance_km_buffer"] == ""
    assert actris_icos["methods"] == "dbscan,kmeans"
    assert actris_icos["id_scheme_a"] == "ACTRIS DVAS facility identifier"
    assert actris_icos["lat_a"] == 61.85000

    # Check ICOS-eLTER row
    icos_elter = result[(result.ri_a == "ICOS") & (result.ri_b == "eLTER")].iloc[0]
    assert icos_elter["distance_km_dbscan"] == ""
    assert icos_elter["distance_km_buffer"] == 0.016
    assert icos_elter["methods"] == "buffer"
    assert icos_elter["id_scheme_b"] == "DEIMS-SDR UUID"

    # Check empty columns
    assert "same_place" in result.columns
    assert (result["same_place"] == "").all()