# Results

**Run date:** 2026-08-24 · **Parameters:** DBSCAN eps = 5 km, min_samples = 2; one-sided buffer = 5 km; k-means k = 633.

## Records loaded

510 ICOS records and 1,391 eLTER records with usable coordinates were loaded (1,901 total). No duplicate `(ri, record_id)` pairs remained after validation. The pilot does not include ACTRIS.

## Candidate cross-infrastructure matches

- DBSCAN (haversine): **244** pairs.
- k-means baseline: **1,437** pairs.
- One-sided 5 km buffer intersection in EPSG:3035: **234** pairs.

At eps = 5 km, **176 DBSCAN clusters contained more than one record from the same infrastructure**. This is the main negative result: spatial proximity alone is not identity.

## Reviewed candidate set

40 candidate pairs were adjudicated by hand: 10 matches and 30 non-matches. The review sample was stratified by distance and name similarity, not randomly drawn from all possible station-site pairs.

| Method | Conditional precision | Reviewed false proposals | Total proposed pairs | Unreviewed proposals |
| --- | ---: | ---: | ---: | ---: |
| DBSCAN | 0.8333 | 2 | 244 | 232 |
| One-sided buffer | 0.8333 | 2 | 234 | 222 |
| k-means baseline | 0.2500 | 30 | 1,437 | 1,397 |

Recall is 1.0 for every method by construction: every reviewed pair was sampled from the candidate sets, so false negatives outside those sets are unobservable. Recall against the full population is not measured here, and F1 inherits that limitation. Precision is also conditional on the reviewed candidate set rather than a population estimate. The meaningful comparison is that DBSCAN and the buffer matcher tied on the reviewed set while making two false proposals each, versus 30 for k-means; their candidate sets diverge outside the reviewed subset.

The DBSCAN/buffer false proposals were nearby but distinct stations: Storjarn versus Degero, and Zeppelin versus Sverdrup Research Station. The Degero eLTER record explicitly points to the distinct ICOS record `SE-Deg`, demonstrating why record-level verification is necessary.

Every number is traceable to `outputs/summary.md`, `outputs/run_manifest.json`, and `data/ground_truth/manual_pairs.csv` from the same offline run.
