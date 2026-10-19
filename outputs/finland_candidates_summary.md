# Finland candidate pairs (unreviewed)

Generated 2026-10-19T22:53:09+00:00 from git revision `c813124`. This is a candidate table for hand labelling: `same_place`, `match_type`, `evidence`, `checked_by` and `checked_at` are empty. Nothing in it is a result.

## Scope

- Records: 87 Finnish harmonised records (ACTRIS 42, ICOS 25, eLTER 20); country FI, eLTER by title suffix ` - Finland` confirmed by the DEIMS detail country.
- Candidate rule: cross-RI pair, polygon-aware distance at most 5 km (EPSG:3035; DEIMS polygon where a boundary exists, 0 when the other record is inside, else points).
- Table: 79 pairs in 13 clusters (connected components of the pair graph, numbered north to south).
- Method columns (DBSCAN eps 5 km, buffer 5 km, k-means k = n // 3) are the CLI defaults run on the full three-source table; blank means that method did not pair the two records. Their `name_similarity` uses different name inputs per method (normalised for DBSCAN and k-means, raw for the buffer), so the three can disagree for one pair.

## Cumulative candidate pairs

Each pair's distance was computed once; the rows count pairs at or below the threshold. `geometry` = polygon-aware, `point` = point to point.

|   threshold_km |   pairs_geometry |   pairs_point |   geometry_ACTRIS-eLTER |   geometry_ACTRIS-ICOS |   geometry_eLTER-ICOS |
|---------------:|-----------------:|--------------:|------------------------:|-----------------------:|----------------------:|
|           0.25 |               41 |            12 |                      23 |                      4 |                    14 |
|           0.5  |               45 |            16 |                      25 |                      6 |                    14 |
|           1    |               52 |            26 |                      26 |                     11 |                    15 |
|           2    |               62 |            41 |                      29 |                     17 |                    16 |
|           5    |               79 |            68 |                      37 |                     22 |                    20 |
|          10    |               98 |            91 |                      45 |                     31 |                    22 |
|          20    |              110 |           108 |                      51 |                     37 |                    22 |

## Presence checks

- ICOS FI-Kvr (Kuivajärvi): present (Kuivajarvi; 61.84662, 24.28040; point only)
- ICOS FI-Lom (Lompolojankka): present (Lompolojankka; 67.99724, 24.20918; point only)
- DEIMS Lompolojankka: present (Lompolojankka - Finland; 67.99724, 24.20918; point only)
- DEIMS Pallas LTER observatory: present (Pallas LTER observatory - Finland; 67.99725, 24.20910; polygon 4,869 ha)
- DEIMS Helsinki HMA-LTSER platform: present (Helsinki Metropolitan Area HMA-LTSER - Finland; 60.16670, 24.93330; polygon 148,975 ha)

## Oddities

Sites with a boundary polygon (every record inside a polygon is at distance 0, so a large polygon pairs with everything in it):

- Helsinki Metropolitan Area HMA-LTSER - Finland: 148,975 ha, 14 pairs, 14 at distance 0
- Kumpula Helsinki / SMEAR III - Finland: 25 ha, 8 pairs, 2 at distance 0
- Pallas LTER observatory - Finland: 4,869 ha, 6 pairs, 6 at distance 0
- SMEAR-Agri Viikki - Finland: 7 ha, 5 pairs, 0 at distance 0
- Hyytiälä SMEAR II LTER - Finland: 13 ha, 4 pairs, 2 at distance 0
- Oulanka Research Station (Oulanka LTER) - Finland: 496,576 ha, 3 pairs, 3 at distance 0
- Värriö Research Station (Värriö LTER) - Finland: 134,181 ha, 2 pairs, 2 at distance 0
- Kevo Research Station (Kevo LTER) - Finland: 2,870 ha, 2 pairs, 2 at distance 0
- Lammi LTER - Finland: 31,400 ha, 2 pairs, 2 at distance 0
- Western Gulf of Finland LTER site WelFin - Finland: 634 ha, 1 pairs, 1 at distance 0
- Kilpisjärvi Biological Station (Kilpisjärvi LTER) - Finland: 17,159 ha, 0 pairs, 0 at distance 0
- Lake Päijänne LTER - Finland: 8,854 ha, 0 pairs, 0 at distance 0
- Archipelago Research Institute (Seili LTER) - Finland: 561 ha, 0 pairs, 0 at distance 0

Pairs that are in only because of the polygon (point distance above 5 km): 11
- ACTRIS:9w63 / eLTER:f81f30bb-6e2b-4a11-9b65-266fee2ae330: point 6.496 km, geometry 0.0 km
- ACTRIS:yd9c / eLTER:f81f30bb-6e2b-4a11-9b65-266fee2ae330: point 11.212 km, geometry 0.0 km
- ACTRIS:d3ma / eLTER:a43d31c8-6219-4ab8-ac41-6088cb56b12b: point 20.062 km, geometry 0.0 km
- ICOS:FI-Rk2 / eLTER:a43d31c8-6219-4ab8-ac41-6088cb56b12b: point 18.589 km, geometry 0.0 km
- ACTRIS:1DUI / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 7.562 km, geometry 0.0 km
- ACTRIS:8KFQ / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 14.896 km, geometry 0.0 km
- ACTRIS:C83W / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 9.777 km, geometry 0.0 km
- ACTRIS:IQ7I / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 9.067 km, geometry 0.0 km
- ACTRIS:J2W9 / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 19.921 km, geometry 0.0 km
- ACTRIS:LVQZ / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 17.04 km, geometry 0.0 km
- ACTRIS:f5ms / eLTER:35e3775a-88bc-483f-aed0-b614ce7736e2: point 21.569 km, geometry 0.0 km

DEIMS sites that list several ICOS stations (one site to many stations):

- Hyytiälä SMEAR II LTER - Finland: ES_FI-Hyy, ES_FI-Kvr; in harmonised records: {'ES_FI-Hyy': True, 'ES_FI-Kvr': True}
- Pallas LTER observatory - Finland: AS_PAL, ES_FI-Ken; in harmonised records: {'AS_PAL': True, 'ES_FI-Ken': True}

Finnish records with no candidate pair at this threshold (no match is implied or ruled out):

- ACTRIS (15): Haapasaari, Hailuoto, Hailuoto II, Hietajärvi, Jokioinen, Jomala, Kuopio, Kökar, Puumala, Virolahti, Virolahti Harju, Virolahti II, Virolahti III, Ähtäri, Ähtäri II
- ICOS (6): Jokioinen, Naarasneva, Qvidja, Ruukki, Siikaneva, Siikaneva-2 Bog
- eLTER (7): Archipelago Research Institute (Seili LTER) - Finland, Kainuu Fisheries Research Station - Finland, Kilpisjärvi Biological Station (Kilpisjärvi LTER) - Finland, Kolari Field Site - Finland, Konnevesi Research Station - Finland, Kuusamo LTSER - Finland, Lake Päijänne LTER - Finland

## Sources

- elter: https://deims.org/api/sites retrieved 2026-10-19T22:48:26+00:00
- icos: https://meta.icos-cp.eu/sparql retrieved 2026-10-19T22:48:28+00:00
- actris: https://prod-actris-md.nilu.no/api/facilities retrieved 2026-10-19T22:48:30+00:00
- deims_detail: https://deims.org/api/sites/{uuid} retrieved 2026-10-19T22:49:07+00:00

Raw responses are cached in `data/raw/` (not committed; DEIMS detail records carry site-manager personal data) with SHA-256 in `outputs/finland_candidates_run.json`.
