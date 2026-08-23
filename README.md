# ICOS–eLTER station harmonisation pilot

A reproducible pilot for one narrow question: can ICOS station records and eLTER/DEIMS-SDR site records that describe the same physical place be identified automatically and checked by a human?

## Scope and safeguards

- **Implemented sources:** ICOS Carbon Portal SPARQL and eLTER DEIMS-SDR REST API. ACTRIS and LLM workflows are not implemented or claimed.
- **Identity:** candidates use ICOS resource URIs and eLTER UUIDs (`record_id`); short station codes are display data only.
- **Geometry:** the current eLTER input is a site centroid. A buffer result is centroid-distance evidence, not polygon containment.
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

## Manual review

Open `outputs/review_sheet.csv`; for every reviewed row fill `same_place` with `yes` or `no`, `checked_by`, `checked_at` (ISO date), and evidence based on both landing pages. Copy only the ground-truth columns into `data/ground_truth/manual_pairs.csv`, then run offline again. Keep confirmed non-matches.

## Results

The current verified counts and explicit no-label status are in [RESULTS.md](RESULTS.md). Generated outputs are committed only when they correspond to the published code revision. See `data/ground_truth/data_dictionary.csv` for mappings and non-mappings.

## Sources

- ICOS: `https://meta.icos-cp.eu/sparql`
- DEIMS-SDR: `https://deims.org/api/sites`

Use the infrastructures’ own terms and citation guidance for source data. This pilot is MIT-licensed code, not a re-publication of their raw metadata.
