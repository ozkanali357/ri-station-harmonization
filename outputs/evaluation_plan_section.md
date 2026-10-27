# Finland evaluation design (#9), draft, proposed labels

## 1. What is scored

Scored set: the 14 gold rows of outputs/finland_candidates_labelled.csv, i.e. evidence_basis in
{identifier, deims_listing} (identifier 3, deims_listing 11; same_station 3, same_site 11).

Metric: "recall on gold positives" — the share of the 14 pairs a method returns as a candidate
pair. Not "performance"; no precision is reported.

All three methods return all 14 gold pairs. The candidate set is defined by a polygon-aware
distance filter (distance_km_geometry <= MAX_KM = 5.0 km), not by any method, so this is not by
construction. It is also uninformative: the 56 identifier, listing, name and transitive pairs are
found by all three methods. The labels do not discriminate the three at this distance.

Result sentence carried into the thesis: "On the 56 pairs all three methods agree on, the
proposed labels do not discriminate the methods at 5 km. This describes the candidate universe,
not a method ranking."

Two parameters, both 5.0 km but distinct: MAX_KM = 5.0 is the cap on the candidate filter
(distance_km_geometry <= MAX_KM); eps_km = 5.0 and buffer_km = 5.0 are the method parameters
(DBSCAN eps, buffer radius). Confirmed from outputs/finland_candidates_run.json (max_km 5.0,
method_parameters eps_km 5.0, buffer_km 5.0, min_samples 2, kmeans_divisor 3).

## 2. Counted, not scored

- Transitive positives (3: 8h8z, zsf3 with the Pallas LTER record; ko6m with FI-Kvr). These are
  positives whose evidence is indirect (a two-link chain through a third record), so they are
  kept out of the gold set for that reason only. All three methods return them, so they would
  not distinguish the methods if scored; reporting them separately keeps the indirect-evidence
  positives visible without inflating the recall denominator.

- Name-based positives (13): labelled from names. The three methods are distance-based, so their
  recall of these pairs is not a signal of accuracy — the labels rest on names, and name
  agreement is not independent evidence either way.

- Different (29: different_no_name 26, different_region_polygon 3): shown in a table of method
  output vs hand label. Labels rest on names or region-scale polygons, so they are not
  independent of name similarity. They show a false-positive mode (large polygons), not precision.

- Unclear (20): excluded and counted (16 Oct rule).

## 3. Caveats stated in the thesis

- The 79 candidates come from a polygon-aware distance filter at 5 km (distance_km_geometry <= MAX_KM = 5.0; scripts/finland_candidates.py:13, 268-270), not from any single method. DBSCAN (eps_km = 5.0), buffer (buffer_km = 5.0) and k-means (kmeans_divisor = 3) each ran independently on the full three-source table (stations at scripts/finland_candidates.py:388, loaded by load_stations; 3,436 records, previously confirmed from data/interim/stations_harmonised.csv). The candidate table itself is the Finnish subset (fi at line 389: ACTRIS 42, ICOS 25, eLTER 20 = 87 records). The methods column records which of the three produced each pair. Note: n_records in outputs/finland_candidates_run.json reports the 87 Finnish records the candidate table is built from, not the 3,436-record method run.

- DBSCAN and buffer do not return the 3 region-polygon pairs. Those pairs are candidates only
  through polygon containment (point distance above 5 km), and both methods use point/centroid
  distance. That is a structural gap, not a false negative about performance.

- k-means returns all 79 candidates, including all 20 unclear and all 3 region-polygon pairs.
  The labels cannot say whether the unclear and region-polygon pairs are correct, so volume and
  accuracy cannot be separated from the current labels. On the full three-source table, k-means
  returns substantially more pairs than DBSCAN or buffer [CHECK: counts 3,820 / 581 / 537 from
  actris-adapter/three_ri_run_2026-10-12/run_manifest.json in the Library, not re-run here].

- Labels are proposed, not confirmed (#4 open). All numbers carry "proposed labels".

- n = 14 (gold) / 79 (candidates). Report counts, not percentages alone.

- normalise_name strips LTER and LTSER but not ACTRIS or ICOS, and token_set_ratio treats set
  inclusion as full similarity, so name similarity alone cannot separate stations from sites.

- Name_similarity values in outputs generated before a15cda6 come from raw names.

## 4. Conservative validation layer
Counts of candidates surviving each rule (identifier, listing, distance bands, name), with the
rule order fixed in advance. Counts only; no accuracy claim.

## 5. Limit sentence
No Finland label rests on an independent negative, so no precision is reported.

## 6. Future work
A second human labels a blind sample of the "different" rows without names or proposed labels.
