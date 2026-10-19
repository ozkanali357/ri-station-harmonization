"""Match ICOS source_ids to ACTRIS gawid_uri values and output a CSV."""
import json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data/interim/stations_harmonised.csv"
OUT_CSV = ROOT / "outputs/gawid_matches.csv"

def main():
    df = pd.read_csv(INPUT_CSV, dtype=str, keep_default_na=False)
    
    icos = df[df["ri"] == "ICOS"].copy()
    actris = df[df["ri"] == "ACTRIS"].copy()
    
    # Extract gawid_uri and drop empty/None strings
    actris["gawid_uri"] = actris["extra_ids"].apply(
        lambda s: (json.loads(s).get("gawid_uri") or "").strip() if s.strip() else ""
    )
    actris = actris[~actris["gawid_uri"].isin(["", "None"])]
    
    # Merge
    merged = icos.merge(
        actris[["source_id", "uri", "lat", "lon", "gawid_uri"]], 
        left_on="source_id", right_on="gawid_uri", 
        suffixes=("_icos", "_actris")
    )
    
    # Calculate distance
    merged["lat_icos"] = pd.to_numeric(merged["lat_icos"])
    merged["lon_icos"] = pd.to_numeric(merged["lon_icos"])
    merged["lat_actris"] = pd.to_numeric(merged["lat_actris"])
    merged["lon_actris"] = pd.to_numeric(merged["lon_actris"])
    
    merged["distance_km"] = np.sqrt(
        ((merged["lat_icos"] - merged["lat_actris"]) * 111)**2 + 
        ((merged["lon_icos"] - merged["lon_actris"]) * 111 * np.cos(np.radians(merged["lat_icos"])))**2
    )
    
    # Select and sort (using the new suffixed names)
    cols = ["source_id_icos", "gawid_uri", "distance_km", "uri_icos", "uri_actris", "lat_icos", "lon_icos", "lat_actris", "lon_actris"]
    merged = merged[cols].sort_values("distance_km")
    
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(merged)} matches to {OUT_CSV}")
    print(f"Within 5km: {(merged['distance_km'] < 5).sum()}")
    print(f"Within 10km: {(merged['distance_km'] < 10).sum()}")

if __name__ == "__main__":
    main()