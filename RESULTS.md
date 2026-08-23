# Results

**Run date:** 2026-08-23 · **Parameters:** DBSCAN eps = 5 km, min_samples = 2; buffer = 5 km; k-means k = 633.

## Records loaded

510 ICOS records and 1,391 eLTER records with usable coordinates were loaded (1,901 total). No duplicate `(ri, record_id)` pairs remained after validation. The current run does not include ACTRIS.

## Candidate cross-infrastructure matches

- DBSCAN (haversine): **244** pairs.
- k-means baseline: **1,437** pairs.
- One-sided 5 km buffer intersection in EPSG:3035: **234** pairs.

At 5 km, DBSCAN produces 244 pairs and 176 clusters containing more than one record from the same infrastructure; the epsilon sweep is recorded in `outputs/eps_sweep.csv`.

## Hand-checked reference set

No pairs have been adjudicated yet. Metrics must not be reported until `data/ground_truth/manual_pairs.csv` contains manual yes/no decisions with evidence. Future precision, recall, and F1 are conditional on the reviewed candidate universe, not population-wide estimates.

All numbers above are traceable to `outputs/summary.md` and `outputs/run_manifest.json` from the same run.
