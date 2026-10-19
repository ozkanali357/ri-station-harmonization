# ICOS–eLTER station harmonisation pilot

A reproducible pilot for one narrow question: can ICOS station records and eLTER/DEIMS-SDR site records that describe the same physical place be identified automatically and checked by a human?

## Scope and safeguards

- **Implemented sources:** ICOS Carbon Portal SPARQL, eLTER DEIMS-SDR REST API, and (adapter only) the ACTRIS Metadata facilities API. The ACTRIS adapter (`src/ri_harmonize/actris.py`) is tested offline on a six-record fixture; ACTRIS is not part of the evaluated pilot in `RESULTS.md`, and no ACTRIS ground truth exists. LLM workflows are not implemented or claimed.
- **Identity:** candidates use ICOS resource URIs and eLTER UUIDs (`record_id`); short station codes are display data only.
- **Geometry:** by default the eLTER input is a site centroid, and a buffer result is centroid-distance evidence, not polygon containment. The opt-in `--deims-detail-finland` run adds DEIMS boundary polygons for the Finnish eLTER sites (see below).
- **Evaluation:** scores are conditional on manually reviewed candidates and are not population-wide estimates.

## Methods

1. A documented canonical schema and data dictionary, including unresolved semantic conflicts.
2. Haversine DBSCAN, unit-sphere k-means baseline, and a one-sided EPSG:3035 buffer intersection.
3. A stratified review sheet with landing pages and evidence fields for manual yes/no adjudication.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q
python -m ri_harmonize.cli -v run
python -m ri_harmonize.cli review --limit 40
```

The first run caches raw source responses in `data/raw/` (ignored by Git) and writes query, endpoint, retrieval time, checksums, parameters, validation facts, and Git revision to `outputs/run_manifest.json`. Re-run with `run --offline` after the cache exists.

### Finnish eLTER polygons (opt-in, new run)

```bash
python -m ri_harmonize.cli -v run --deims-detail-finland --out-dir outputs/finland_polygon_run
```

Fetches `GET https://deims.org/api/sites/{id}` for the eLTER records whose title ends in ` - Finland`, caches each response byte-for-byte in `data/raw/deims_detail/` (SHA-256 and retrieval time in `data/raw/manifest.json`), and sets `geometry_kind` to `polygon` where a boundary exists (`point` where it does not). `candidate_pairs_buffer_polygon.csv` then holds pairs whose geometry distance in EPSG:3035 is within `--buffer-km`; `polygon_distance_m` is the distance from the other record's point to the polygon (0 when inside). A polygon is evidence, not a hard inside/outside cut. The raw cache is not committed because DEIMS detail records contain site-manager names and e-mail addresses; nothing from the `contact` block is read or written. Without the flag nothing changes. A polygon run is a new, unreviewed run and is not comparable with `RESULTS.md`.

## Manual review

Open `outputs/review_sheet.csv`; for every reviewed row fill `same_place` with `yes` or `no`, `checked_by`, `checked_at` (ISO date), and evidence based on both landing pages. Copy only the ground-truth columns into `data/ground_truth/manual_pairs.csv`, then run offline again. Keep confirmed non-matches.

## Results

The current verified counts and conditional reviewed-set evaluation are in [RESULTS.md](RESULTS.md). Generated outputs are committed only when they correspond to the published code revision. See `data/ground_truth/data_dictionary.csv` for mappings and non-mappings.

## Sources

- ICOS: `https://meta.icos-cp.eu/sparql`
- DEIMS-SDR: `https://deims.org/api/sites`
- ACTRIS facilities: `https://prod-actris-md.nilu.no/api/facilities` (OpenAPI spec at `/v3/api-docs`)

Use the infrastructures’ own terms and citation guidance for source data. This pilot is MIT-licensed code, not a re-publication of their raw metadata.
