"""Generate the Hyytiälä candidate pairs crosswalk for Step 2.

Input: outputs/candidate_pairs_dbscan.csv, candidate_pairs_buffer.csv, candidate_pairs_kmeans.csv
Output: outputs/hyytiala_candidates.csv
"""

import sys
from pathlib import Path
import pandas as pd

# Add src to path to import load_stations
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ri_harmonize.cli import load_stations

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

TARGETS = {
    ("ICOS", "http://meta.icos-cp.eu/resources/stations/AS_SMR"),
    ("ICOS", "http://meta.icos-cp.eu/resources/stations/ES_FI-Hyy"),
    ("ACTRIS", "ko6m"),
    ("eLTER", "663dac80-211d-4c19-a356-04ee0da0f0eb"),
}

def normalize_pair(row):
    a = (row["ri_a"], row["record_id_a"])
    b = (row["ri_b"], row["record_id_b"])
    if a > b:
        a, b = b, a
    return pd.Series([a[0], a[1], b[0], b[1]], index=["ri_a", "record_id_a", "ri_b", "record_id_b"])

def process_candidates(stations: pd.DataFrame):
    methods = ["dbscan", "buffer", "kmeans"]
    dfs = []
    
    for m in methods:
        p = OUT / f"candidate_pairs_{m}.csv"
        if not p.exists():
            print(f"Warning: {p} not found. Skipping.")
            continue
        df = pd.read_csv(p)
        df["method"] = m
        dfs.append(df)

    if not dfs:
        print("No candidate files found.")
        return None

    cands = pd.concat(dfs, ignore_index=True)

    # Normalize pairs so (A,B) and (B,A) are treated the same
    cands[["ri_a", "record_id_a", "ri_b", "record_id_b"]] = cands.apply(normalize_pair, axis=1)

    # Filter to only target pairs where BOTH ends are targets
    is_target_a = cands.apply(lambda r: (r["ri_a"], r["record_id_a"]) in TARGETS, axis=1)
    is_target_b = cands.apply(lambda r: (r["ri_b"], r["record_id_b"]) in TARGETS, axis=1)
    cands = cands[is_target_a & is_target_b].copy()

    # Pivot methods to columns
    dist_df = cands.pivot(index=["ri_a", "record_id_a", "ri_b", "record_id_b"], columns="method", values="distance_km")
    dist_df.columns = [f"distance_km_{c}" for c in dist_df.columns]
    
    sim_df = cands.pivot(index=["ri_a", "record_id_a", "ri_b", "record_id_b"], columns="method", values="name_similarity")
    sim_df.columns = [f"name_similarity_{c}" for c in sim_df.columns]
    
    methods_df = cands.groupby(["ri_a", "record_id_a", "ri_b", "record_id_b"])["method"].apply(lambda x: ",".join(sorted(x))).reset_index()
    methods_df.columns = ["ri_a", "record_id_a", "ri_b", "record_id_b", "methods"]

    merged = methods_df.set_index(["ri_a", "record_id_a", "ri_b", "record_id_b"])
    merged = merged.join(dist_df).join(sim_df).reset_index()

    # Add source_id, name, uri from the candidate files (taking the first occurrence)
    meta_cols = cands.groupby(["ri_a", "record_id_a", "ri_b", "record_id_b"])[["source_id_a", "name_a", "uri_a", "source_id_b", "name_b", "uri_b"]].first().reset_index()
    merged = merged.merge(meta_cols, on=["ri_a", "record_id_a", "ri_b", "record_id_b"], how="left")

    # Join with stations for id_scheme, lat, lon
    stations_a = stations.rename(columns={"id_scheme": "id_scheme_a", "lat": "lat_a", "lon": "lon_a"})
    stations_b = stations.rename(columns={"id_scheme": "id_scheme_b", "lat": "lat_b", "lon": "lon_b"})
    
    merged = merged.merge(stations_a, left_on=["ri_a", "record_id_a"], right_on=["ri", "record_id"], how="left", suffixes=("", "_station_a"))
    merged = merged.merge(stations_b, left_on=["ri_b", "record_id_b"], right_on=["ri", "record_id"], how="left", suffixes=("", "_station_b"))

    # Clean up columns
    merged = merged.drop(columns=["ri_station_a", "record_id_station_a", "ri_station_b", "record_id_station_b"], errors="ignore")

    # Fill empty for missing methods
    for col in merged.columns:
        if col.startswith("distance_km_") or col.startswith("name_similarity_"):
            merged[col] = merged[col].fillna("")

    # Add empty columns
    merged["same_place"] = ""
    merged["checked_by"] = ""
    merged["checked_at"] = ""
    merged["evidence"] = ""

    # Reorder columns to match the requested schema
    final_cols = [
        "ri_a", "record_id_a", "source_id_a", "id_scheme_a", "name_a", "lat_a", "lon_a", "uri_a",
        "ri_b", "record_id_b", "source_id_b", "id_scheme_b", "name_b", "lat_b", "lon_b", "uri_b",
        "distance_km_dbscan", "distance_km_buffer", "distance_km_kmeans",
        "name_similarity_dbscan", "name_similarity_buffer", "name_similarity_kmeans",
        "methods", "same_place", "checked_by", "checked_at", "evidence"
    ]
    
    # Ensure all columns exist
    for c in final_cols:
        if c not in merged.columns:
            merged[c] = ""

    return merged[final_cols]

def main():
    stations = load_stations(offline=True)
    result = process_candidates(stations)
    
    if result is not None:
        OUT.mkdir(parents=True, exist_ok=True)
        out_path = OUT / "hyytiala_candidates.csv"
        result.to_csv(out_path, index=False)
        print(f"Wrote {len(result)} rows to {out_path}")

        # Print the 6 possible target pairs
        targets_list = list(TARGETS)
        print("\nPossible target pairs:")
        for i in range(len(targets_list)):
            for j in range(i + 1, len(targets_list)):
                a, b = targets_list[i], targets_list[j]
                if a[0] == b[0]:
                    continue  # Skip same-RI pairs
                # Check if present
                found = result[
                    ((result.ri_a == a[0]) & (result.record_id_a == a[1]) & (result.ri_b == b[0]) & (result.record_id_b == b[1])) |
                    ((result.ri_a == b[0]) & (result.record_id_a == b[1]) & (result.ri_b == a[0]) & (result.record_id_b == a[1]))
                ]
                status = "PRESENT" if not found.empty else "ABSENT"
                print(f"  {a[0]}:{a[1]} <-> {b[0]}:{b[1]} : {status}")

if __name__ == "__main__":
    main()