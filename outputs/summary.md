# Run summary

Generated from cached RI responses in `data/raw/`. Parameters: {'eps_km': 5.0, 'min_samples': 2, 'buffer_km': 5.0, 'kmeans_k': 633}.

## Records loaded

| Infrastructure | Records with usable coordinates |
| --- | --- |
| ICOS | 510 |
| eLTER | 1391 |
| **total** | **1901** |

## Choice of eps

|   eps_km |   n_clusters |   n_noise |   noise_fraction |   n_cross_ri_clusters |   n_cross_ri_pairs |   n_same_ri_overmerged |
|---------:|-------------:|----------:|-----------------:|----------------------:|-------------------:|-----------------------:|
|      0.5 |          150 |      1581 |           0.8317 |                   107 |                119 |                     53 |
|      1   |          186 |      1496 |           0.787  |                   119 |                143 |                     85 |
|      2   |          230 |      1383 |           0.7275 |                   142 |                192 |                    119 |
|      3   |          246 |      1328 |           0.6986 |                   146 |                214 |                    138 |
|      5   |          278 |      1232 |           0.6481 |                   150 |                244 |                    176 |
|      7.5 |          302 |      1148 |           0.6039 |                   154 |                271 |                    204 |
|     10   |          307 |      1095 |           0.576  |                   160 |                318 |                    211 |
|     15   |          331 |       944 |           0.4966 |                   162 |                483 |                    246 |
|     20   |          331 |       863 |           0.454  |                   169 |                628 |                    254 |
|     30   |          328 |       690 |           0.363  |                   173 |               1635 |                    259 |

Selected eps = 5.0 km, min_samples = 2.

## Candidate cross-RI pairs

- DBSCAN (haversine): **244** pairs
- k-means baseline (k = 633): **1437** pairs
- Buffer intersection in EPSG:3035 at 5.0 km: **234** pairs

## Scored against the hand-checked ground truth

- `dbscan.reviewed_pairs`: 40
- `dbscan.true_positives`: 10
- `dbscan.false_positives`: 2
- `dbscan.false_negatives`: 0
- `dbscan.true_negatives`: 28
- `dbscan.precision`: 0.8333
- `dbscan.recall`: 1.0
- `dbscan.f1`: 0.9091
- `dbscan.unadjudicated_candidates`: 232
- `dbscan.evaluation_scope`: conditional on reviewed candidate universe; not a population estimate
- `kmeans_baseline.reviewed_pairs`: 40
- `kmeans_baseline.true_positives`: 10
- `kmeans_baseline.false_positives`: 30
- `kmeans_baseline.false_negatives`: 0
- `kmeans_baseline.true_negatives`: 0
- `kmeans_baseline.precision`: 0.25
- `kmeans_baseline.recall`: 1.0
- `kmeans_baseline.f1`: 0.4
- `kmeans_baseline.unadjudicated_candidates`: 1397
- `kmeans_baseline.evaluation_scope`: conditional on reviewed candidate universe; not a population estimate
- `buffer_intersection.reviewed_pairs`: 40
- `buffer_intersection.true_positives`: 10
- `buffer_intersection.false_positives`: 2
- `buffer_intersection.false_negatives`: 0
- `buffer_intersection.true_negatives`: 28
- `buffer_intersection.precision`: 0.8333
- `buffer_intersection.recall`: 1.0
- `buffer_intersection.f1`: 0.9091
- `buffer_intersection.unadjudicated_candidates`: 222
- `buffer_intersection.evaluation_scope`: conditional on reviewed candidate universe; not a population estimate

> **Evaluation scope.** Reviewed pairs were sampled from the candidate sets, so recall is 1.0 by construction and does not measure population recall. Precision is conditional on the reviewed candidate set; see `RESULTS.md` for the interpretation.

## Nearest ten candidates

| ri_a   | source_id_a   | name_a                   | ri_b   | source_id_b                          | name_b                                            |   distance_km |   name_similarity |
|:-------|:--------------|:-------------------------|:-------|:-------------------------------------|:--------------------------------------------------|--------------:|------------------:|
| ICOS   | SE-Htm        | Hyltemossa               | eLTER  | b27549de-1e6f-4f3e-9e22-4d4f3dec61e3 | Hyltemossa - Sweden                               |             0 |                 1 |
| ICOS   | SE-Nor        | Norunda                  | eLTER  | 459284f2-c7cd-4bb1-96c3-2b38c338ff4a | Norunda - Sweden                                  |             0 |                 1 |
| ICOS   | FI-Lom        | Lompolojankka            | eLTER  | e6b372ee-f310-49fd-9d0d-2a8306a06b64 | Lompolojankka - Finland                           |             0 |                 1 |
| ICOS   | BE-Dor        | Dorinne                  | eLTER  | c31d9f9c-7f96-48b8-afe8-96df3e96cbf3 | Dorinne - Belgium                                 |             0 |                 1 |
| ICOS   | BE-Wm1        | Westmalle1               | eLTER  | 80d9d292-dc4f-4d4f-a1b4-417bf468948c | Westmalle1 - Belgium                              |             0 |                 1 |
| ICOS   | BE-Wm2        | Westmalle2               | eLTER  | ab9666a6-6298-472a-b80e-bd95212214a4 | Westmalle2 - Belgium                              |             0 |                 1 |
| ICOS   | CD-Ygb        | Yangambi                 | eLTER  | 29ceeb3a-34c3-42cf-befb-ae461893f4bb | Yangambi - Congo (the Democratic Republic of the) |             0 |                 1 |
| ICOS   | CH-BaK        | Basel Klingelbergstrasse | eLTER  | 3604bab6-0a11-48e9-9b0b-738cb0fbc127 | Basel Klingelbergstrasse - Switzerland            |             0 |                 1 |
| ICOS   | DE-BeR        | Berlin-Rothenburgstrasse | eLTER  | cdbfe5d1-5d30-4937-b63a-40b7f1d2c5b8 | Berlin-Rothenburgstrasse - Germany                |             0 |                 1 |
| ICOS   | DE-Geb        | Gebesee                  | eLTER  | 9cf0edb0-187a-4c5f-a107-41c68e1403c1 | Gebesee - Germany                                 |             0 |                 1 |
