# Results

**Run date:** 2026-08-24 · **Parameters:** DBSCAN eps = 5 km, min_samples = 2; one-sided buffer = 5 km; k-means k = 633.

## Records loaded

510 ICOS records and 1,391 eLTER records with usable coordinates were loaded (1,901 total). No duplicate `(ri, record_id)` pairs remained after validation. The pilot does not include ACTRIS.

## Candidate cross-infrastructure matches

- DBSCAN (haversine): **244** pairs.
- k-means baseline: **1,437** pairs.
- One-sided 5 km buffer intersection in EPSG:3035: **234** pairs.

The 5 km DBSCAN sweep point contains 176 clusters with more than one record from the same infrastructure, an explicit warning that proximity alone is not identity.

## Reviewed reference set and conditional evaluation

40 candidate pairs were adjudicated by hand: 10 matches and 30 non-matches. Scores are conditional on this reviewed candidate universe, not population-wide estimates or a held-out test set.

| Method | Precision | Recall | F1 | False positives | Unreviewed candidates |
| --- | ---: | ---: | ---: | ---: | ---: |
| DBSCAN | 0.8333 | 1.0000 | 0.9091 | 2 | 232 |
| One-sided buffer | 0.8333 | 1.0000 | 0.9091 | 2 | 222 |
| k-means baseline | 0.2500 | 1.0000 | 0.4000 | 30 | 1,397 |

The DBSCAN/buffer false positives were nearby but distinct stations: Storjarn versus Degero, and Zeppelin versus Sverdrup Research Station. This shows why spatial distance must be combined with record-level verification.

Every number is traceable to `outputs/summary.md`, `outputs/run_manifest.json`, and `data/ground_truth/manual_pairs.csv` from the same offline run.
