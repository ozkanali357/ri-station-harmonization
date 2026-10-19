# Source profile

## ACTRIS

### summary

| key | count |
| --- | --- |
| n_records | 1518 |

### id_scheme

| value | count |
| --- | --- |
| ACTRIS DVAS facility identifier | 1518 |

### geometry_kind

| value | count |
| --- | --- |
| point | 1518 |

### station_class

| key | count |
| --- | --- |
| n_distinct | 3 |

| value | count |
| --- | --- |
| observation platform, fixed | 1468 |
| simulation chamber | 31 |
| observation platform, mobile | 19 |

### extra_ids

| key | count |
| --- | --- |
| active | 1518 |
| actris_national_facility | 1518 |
| actris_nf_uri | 102 |
| ebas_station_code | 1446 |
| ebas_station_lat | 1446 |
| ebas_station_lon | 1446 |
| gawid_uri | 251 |
| identifier_type | 1518 |
| empty_json | 0 |

### country

| key | count |
| --- | --- |
| non_empty | 1518 |
| n_distinct | 88 |

Distinct values (88): AM, AR, AT, AU, BA, BB, BE, BG, BM, BO, BR, BY, CA, CH, CI, CL, CN, CU, CV, CY, CZ, DE, DK, DZ, EE, EG, ES, FI, FR, GB, GE, GR, HK, HR, HU, ID, IE, IL, IN, IS, IT, JP, KE, KG, KH, KR, KZ, LA, LT, LV, MD, ME, MK, MN, MT, MV, MX, MY, NE, NL, NO, NP, NZ, PE, PH, PL, PR, PT, PY, RO, RS, RU, SC, SE, SH, SI, SK, SN, SR, TH, TJ, TR, TW, UA, US, VE, VN, ZA

### missing

| key | count |
| --- | --- |
| lat | 0 |
| lon | 0 |
| elevation_m | 21 |
| name | 0 |

### dropped_before_harmonisation

| key | count |
| --- | --- |
| dropped | 6 |

_Dropped = 6._

## ICOS

### summary

| key | count |
| --- | --- |
| n_records | 519 |

### id_scheme

| value | count |
| --- | --- |
| ICOS station code | 519 |

### geometry_kind

| value | count |
| --- | --- |
| point | 519 |

### station_class

| key | count |
| --- | --- |
| n_distinct | 1 |

| value | count |
| --- | --- |
| ICOS station resource | 519 |

### extra_ids

| key | count |
| --- | --- |
| wigos_id | 57 |
| empty_json | 462 |

### country

| key | count |
| --- | --- |
| non_empty | 517 |
| n_distinct | 59 |

Distinct values (59): AS, AT, AU, BB, BE, BJ, BR, BW, CA, CD, CG, CH, CN, CR, CV, CZ, DE, DK, EE, ES, FI, FR, GB, GF, GH, GL, GR, HK, HU, ID, IE, IL, IS, IT, JP, KE, KH, KR, ML, MN, MY, NL, NO, NZ, PA, PL, PT, RO, RU, SD, SE, SJ, SN, TH, US, VE, VU, ZA, ZM

### missing

| key | count |
| --- | --- |
| lat | 0 |
| lon | 0 |
| elevation_m | 62 |
| name | 0 |

### dropped_before_harmonisation

| key | count |
| --- | --- |
| raw_rows | 536 |
| passed_to_finalise | 536 |
| blank_record_id | 0 |
| no_coordinates | 17 |
| out_of_range_coordinates | 0 |
| duplicate_record_id | 0 |
| harmonised | 519 |

_Dropped = passed - harmonised = 17; the buckets sum to 17._

## eLTER

### summary

| key | count |
| --- | --- |
| n_records | 1399 |

### id_scheme

| value | count |
| --- | --- |
| DEIMS-SDR UUID | 1399 |

### geometry_kind

| value | count |
| --- | --- |
| centroid_of_polygon | 1399 |

### station_class

| key | count |
| --- | --- |
| n_distinct | 1 |

| value | count |
| --- | --- |
| eLTER site | 1399 |

### extra_ids

| key | count |
| --- | --- |
| empty_json | 1399 |

### country

| key | count |
| --- | --- |
| non_empty | 0 |
| n_distinct | 0 |

Distinct values (0): 

### missing

| key | count |
| --- | --- |
| lat | 0 |
| lon | 0 |
| elevation_m | 1399 |
| name | 0 |

### dropped_before_harmonisation

| key | count |
| --- | --- |
| raw_rows | 1399 |
| passed_to_finalise | 1399 |
| blank_record_id | 0 |
| no_coordinates | 0 |
| out_of_range_coordinates | 0 |
| duplicate_record_id | 0 |
| harmonised | 1399 |

_Dropped = passed - harmonised = 0; the buckets sum to 0._

## Notes

- Rows without coordinates are dropped before the CSV is written, so missing lat/lon in this table is 0 by construction.
- eLTER: country coverage is 0; adapter did not provide this field.
- eLTER: elevation_m is 100% missing; adapter did not provide this field.
