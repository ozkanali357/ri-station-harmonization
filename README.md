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

### Variable terms for the Finnish records (Step 3, terms first)

```bash
python scripts/dictionary_terms.py --fetch      # first time; later runs read data/raw/dictionary/
```

Writes `outputs/dictionary_terms_finland.csv` (one row per term an RI publishes, with the Finnish records that use it, the source field, the fetch date and any definition or identifier the source gives) and `outputs/dictionary_terms_finland_run.json` (endpoints, queries, checksums, per-RI coverage). Terms come from ICOS (`dcat:theme` variable concepts on the station resources), ACTRIS (`variables[]` of the dataset records at `/api/metadata/search`) and DEIMS-SDR (`observedProperties` of the detail record). Terms are not mapped across RIs, `domain_published` is empty because none of the three publishes a domain per term, and `scope_candidate` is a keyword pre-filter for review, not a classification. Raw responses are cached in `data/raw/dictionary/` (not committed); ACTRIS dataset records and DEIMS detail records contain person names, which the script never reads. The station-field dictionary `data/ground_truth/data_dictionary.csv` is a different file.

Reference-vocabulary lookups for those terms (`python scripts/dictionary_reference.py --fetch`) write `outputs/dictionary_reference_finland.csv` and `outputs/dictionary_reference_finland_run.json`. Each row is one mechanical lookup against the eLTER thesauri (EnvThes, Standard Observations, Controlled Lists), the two ACTRIS vocabularies or the NERC P07 concept an ICOS term names: a DEIMS term's EnvThes URI resolved to today's concept, a published `skos:closeMatch`, or an exact (case-insensitive) label equality. Label equality is string equality, not a mapping, and a term without a row had no hit. Raw responses are cached in `data/raw/dictionary_reference/` (not committed).

### Reference vocabularies and term-mapping candidates (milestone #8)

```bash
python scripts/dictionary_vocab_fetch.py --fetch   # EnvThes, Standard Observations, eLTER_CL, ACTRIS vocabulary: verbatim dumps + licence/version record
python scripts/dictionary_candidates.py            # needs the pinned MiniLM weights (huggingface.co once)
python scripts/dictionary_candidates.py check outputs/dictionary_candidates_finland.csv   # after hand labelling
```

`dictionary_vocab_fetch.py` caches each vocabulary's own Turtle dump and Skosmos scheme metadata in `data/raw/dictionary_vocabularies/` (not committed) and writes `outputs/dictionary_vocabularies_run.json`: URL, SHA-256, retrieval time, every licence statement found with the file it came from, version, concept counts and whether definition text may be committed. ACTRIS vocabulary: CC0 1.0, definitions may be committed with version and licence per row. EnvThes, Standard Observations and eLTER_CL declare CC BY 4.0 in their metadata, but their definition text (and the ICOS source definitions) is kept out of the repository until the project owner accepts that; EnvThes definitions also carry third-party source tags such as `[Henderson's]` and `[GEMET]`.

`dictionary_candidates.py` proposes, for each keyword-flagged (`scope_candidate`) meteorology or soil term, the best-scoring concepts by MiniLM cosine similarity of labels (pinned in `scripts/field_model_pin.json`). **It proposes only.** `skos_relation`, `broader_side` (which side is the broader concept for `broadMatch`/`narrowMatch`), `evidence_basis`, `evidence_text`, `checked_by` and `checked_at` are written blank and are filled by a person. The `check` command validates a labelled file and prints descriptive counts; it infers nothing. Rows with restricted definition text go to the git-ignored `outputs/dictionary_candidates_finland_LOCAL.csv`.

### Site-schema fields: definitions and similarity of field names

```bash
python scripts/icos_field_definitions.py [--offline]   # ICOS rdfs:comment definitions
python scripts/consolidate_dataset.py                  # field list + published definitions
python scripts/compare_fields.py --write-pin           # first time only, needs huggingface.co
python scripts/compare_fields.py                       # later runs
```

`icos_field_definitions.py` asks the ICOS SPARQL endpoint for the `rdfs:comment` of each predicate of one example station resource and writes `outputs/icos_field_definitions.csv` and a run file. The raw responses are committed in `outputs/field_definitions_raw/` with SHA-256 and retrieval time (they hold only ontology predicates and comments, no station or contact data). A field without a published comment stays flagged; `rdfs:label` is not treated as a definition. `compare_fields.py` writes one table per pair of infrastructures (`outputs/field_similarity_deims_icos.csv` is the primary table, then `deims_actris` and `icos_actris`; the pairs are never pooled) with TF-IDF and MiniLM cosine **similarity of field names**, plus a variant that appends the published definition where one exists. Any field whose name contains "contact" is excluded in all three infrastructures (done in `consolidate_dataset.py`; no contact values are read). The MiniLM revision, seed and library versions are pinned in `scripts/field_model_pin.json` and copied to `outputs/field_similarity_run.json`. A similarity score is not evidence that two fields mean the same thing.

### Site-schema fields: DEIMS model definitions and definition-backed tables

```bash
python scripts/deims_model_definitions.py [--offline]  # DEIMS-SDR Site Metadata Model: Definition, Recommendation, Format, Multiplicity, Example
python scripts/actris_field_definitions.py [--offline] # ACTRIS: API description and vocabulary candidates for the 16 facility fields
python scripts/build_definition_backed_input.py        # field list + definitions, via data/mappings/deims_model_field_mapping.csv
python scripts/compare_fields_definition_backed.py     # second set of three tables (needs the pin and the pinned weights)
```

`https://deims.org/models/?id=site` is a viewer page without field text: its script loads the model from `https://raw.githubusercontent.com/stopopol/deims_apps/master/metadata_models/smm.json`. `deims_model_definitions.py` fetches the viewer page, that JSON and the DEIMS terms page into `data/raw/deims_model/` and extracts Definition, Recommendation, Format, Multiplicity and Example verbatim into `outputs/deims_model_definitions.csv`. The whole Contact group is excluded, nothing is paraphrased, and a model field with an empty `Definition` stays flagged. **The model text is not committed.** The DEIMS terms of use (`https://deims.org/terms`, last updated 7 September 2026) state CC BY-NC 4.0 for the content and also forbid scraping to collect content for re-publication, and the page does not settle which applies to a public repository. So the raw responses, `outputs/deims_model_definitions.csv` and `outputs/final_field_comparison_definition_backed.csv` are git-ignored and produced locally; `build_definition_backed_input.py` runs the extraction itself when the CSV is missing. What is committed: `outputs/deims_model_definitions_run.json` (URL, retrieval time, size and SHA-256 of each response and of the CSV), `outputs/deims_model_field_list.csv` (field paths and machine names, no text) and the mapping. A fresh fetch whose `smm.json` has a different SHA-256 from the record, or an extracted CSV that differs from it, stops the run with `CHECKSUM MISMATCH`; after looking at the change, re-record with `python scripts/deims_model_definitions.py --update-record`. Anything quoted from the model in the thesis needs attribution (Environment Agency Austria / Umweltbundesamt GmbH, DEIMS-SDR Site Metadata Model) and the non-commercial licence checked with the DEIMS contact.

`data/mappings/deims_model_field_mapping.csv` links model fields to DEIMS API field paths by hand with a `relation`: `direct` (exact string rule), `curated` (judgement from names) and `component` / `candidate` (listed, never used to copy a definition). Only `direct` and `curated` rows give a DEIMS API field the model's definition; `outputs/deims_model_mapping_unmapped.csv` lists what is left on both sides. ACTRIS: the OpenAPI `Facility` schema has no `description` for any property. Three vocabulary concepts have a label equal to a field name (`facility_type`, `identifier`, `identifier_type`); `outputs/actris_field_definitions.csv` lists them by label and URI only, as candidates. **No ACTRIS vocabulary text is stored or fetched**: the vocabulary's licence is unknown, so the concepts' definitions are never read, and all 16 ACTRIS fields stay flagged. `compare_fields_definition_backed.py` writes `outputs/field_similarity_definition_backed_*.csv` (field names and scores, no text) and a manifest next to the name-only tables, which are not changed: its text is the definition alone where a field has one, else the field name.

## Manual review

Open `outputs/review_sheet.csv`; for every reviewed row fill `same_place` with `yes` or `no`, `checked_by`, `checked_at` (ISO date), and evidence based on both landing pages. Copy only the ground-truth columns into `data/ground_truth/manual_pairs.csv`, then run offline again. Keep confirmed non-matches.

## Results

The current verified counts and conditional reviewed-set evaluation are in [RESULTS.md](RESULTS.md). Generated outputs are committed only when they correspond to the published code revision. See `data/ground_truth/data_dictionary.csv` for mappings and non-mappings.

## Sources

- ICOS: `https://meta.icos-cp.eu/sparql`
- DEIMS-SDR: `https://deims.org/api/sites`
- ACTRIS facilities: `https://prod-actris-md.nilu.no/api/facilities` (OpenAPI spec at `/v3/api-docs`)

Use the infrastructures’ own terms and citation guidance for source data. This pilot is MIT-licensed code, not a re-publication of their raw metadata, and the DEIMS model text is not committed (see above).

*Note: DEIMS definitions are CC BY-NC 4.0 (not committed). ACTRIS definitions are CC0 1.0 (facility_type, identifier, identifier_type) via SKOSMOS.*
