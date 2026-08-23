# Cross-infrastructure station harmonisation (ACTRIS / ICOS / eLTER)

A small, reproducible pilot that answers one question with real data:

> **Which station and site records held by different European environmental research
> infrastructures actually describe the same physical place — and can that be found
> automatically instead of by hand?**

ACTRIS, ICOS and eLTER were built independently, so the same monitoring location can
appear three times under three identifier schemes, three geometry conventions and three
vocabularies. This repository pulls the station metadata from each infrastructure's own
machine-readable endpoint, harmonises it into one schema, proposes cross-infrastructure
matches with three different automated methods, and scores those proposals against a
ground-truth set that a human checked by hand.

The point is not the clustering. The point is that the clustering is **measured** against
something a person verified.

---

## The mismatch, concretely

The three registries disagree in ways that are visible in the raw responses:

| | ICOS | eLTER (DEIMS-SDR) |
| --- | --- | --- |
| Primary identifier | short station code, e.g. `WAO` | 36-character UUID, e.g. `fcbf044b-20e2-…` |
| Secondary identifier | WMO WIGOS ID, e.g. `0-20008-0-WAO` — **only for atmospheric stations** | — |
| Geometry | one point, one elevation | centroid **plus** a downloadable boundary polygon, area in hectares, min/max elevation |
| Time semantics | ICOS labelling date (when the station was certified) | year the research site was established |
| Access | SPARQL over an OWL model (`cpmeta`) | REST/JSON |

Note the asymmetry inside a single infrastructure: in the ICOS ontology `hasWigosId` is
defined on the atmospheric-station class only, so an identifier that looks like a natural
join key exists for some stations and not others. That is the kind of thing a harmonisation
schema has to decide about explicitly rather than discover at query time.

---

## What the pipeline does

**1 — Harmonise.** Each infrastructure gets an adapter that emits exactly the schema in
`src/ri_harmonize/schema.py`: `ri, source_id, id_scheme, uri, name, name_norm, lat, lon,
elevation_m, country, geometry_kind, station_class, extra_ids`. Identifiers are never
rewritten — the *scheme* is recorded alongside the value, and secondary identifiers
(WIGOS and thematic-centre ids) are preserved in `extra_ids` rather than dropped.

**2 — Propose matches, three ways.**

- **DBSCAN on the haversine metric** (default). `eps` is a real distance in kilometres.
  Density-based clustering is the right default here because the number of co-located
  groups is unknown in advance, the groups are irregular, and a station that genuinely
  stands alone must be allowed to stay alone as noise.
- **k-means baseline.** Needs `k`, forces every record into a cluster, and has no concept
  of noise. Run on 3-D unit-sphere coordinates rather than raw lat/lon, otherwise the
  Euclidean objective is wrong at high latitude and across the antimeridian. It is here to
  be beaten, and the comparison is reported.
- **Buffer intersection in EPSG:3035** (ETRS89 / LAEA Europe). Purely geometric, no
  clustering, and — importantly — non-transitive, so a chain of stations 4 km apart cannot
  fuse into one 40 km blob the way DBSCAN can. Buffering in degrees would be wrong:
  one degree of longitude is 111 km at the equator and 55 km at 60 °N, which is exactly
  where most of these stations sit.

Every proposed pair carries its evidence: great-circle distance, normalised-name
similarity (RapidFuzz token-set ratio), and both landing-page URIs, so a reviewer can
adjudicate it without re-running anything.

**3 — Score against hand-checked ground truth.** `data/ground_truth/manual_pairs.csv` holds
one row per pair a human has actually ruled on. `cli.py review` writes the next batch of
un-adjudicated candidates, nearest first; you fill in `same_place` (yes/no) and append.
Precision, recall and F1 are then computed **only over reviewed pairs** — candidates nobody
has looked at are reported separately as `unadjudicated_candidates` rather than being
silently assumed wrong, which would flatter or punish the score depending on which way you
guess.

---

## Quickstart

```bash
git clone https://github.com/<your-username>/ri-station-harmonization
cd ri-station-harmonization
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m ri_harmonize.cli run -v          # fetches once, caches to data/raw/, then analyses
open outputs/summary.md                    # numbers, tables, chosen parameters
```

Re-running is offline and deterministic:

```bash
python -m ri_harmonize.cli run --offline --eps-km 3
python -m ri_harmonize.cli review --limit 60     # next pairs to check by hand
pytest -q                                        # 13 tests, no network required
```

### Outputs

| File | Contents |
| --- | --- |
| `outputs/summary.md` | run report: record counts, eps sweep, scores, nearest candidates |
| `outputs/candidate_pairs_{dbscan,kmeans,buffer}.csv` | proposed matches per method, with evidence |
| `outputs/eps_sweep.csv` / `eps_sweep.png` | candidates gained against over-merging, per eps |
| `outputs/stations_map.png` | stations by infrastructure, and the resulting groups |
| `outputs/stations_clustered.gpkg` / `.geojson` | clustered stations for QGIS or further GIS work |
| `outputs/review_sheet.csv` | the human worklist |

---

## Choosing eps honestly

`sweep_eps` reports, for each candidate radius: number of clusters, noise fraction, number
of cross-infrastructure clusters, number of candidate pairs, and **the number of clusters
that swallowed more than one station from the same infrastructure**. That last column is
the over-merge alarm: two ICOS stations landing in one cluster is not a harmonisation
finding, it is evidence that `eps` has grown past the physical scale of a monitoring site.
The radius is chosen from that trade-off and recorded in `summary.md`, not tuned until the
map looks tidy.

---

## Results

See `outputs/summary.md` for the numbers from the latest run — it is regenerated on every
run so it cannot drift away from the code. Findings from the first full run are recorded in
[`RESULTS.md`](RESULTS.md).

---

## Limitations

- **Coordinates only.** Records without usable coordinates are dropped, so a station that
  exists in a registry with no location is invisible to every method here.
- **Centroids, not polygons.** eLTER sites are reduced to their DEIMS centroid. A large
  site (the Wadden Sea LTSER platform is over 500 000 ha) is not well represented by a
  point, and a point-to-point distance to a station inside it is close to meaningless.
  Pulling real boundary polygons and testing point-in-polygon containment is the obvious
  next step and the natural continuation of this work.
- **ACTRIS is best-effort.** The ACTRIS metadata service is less stable than the other two
  and its response shape has changed between releases; a failure downgrades to a warning
  and a two-infrastructure run rather than killing the pipeline. `summary.md` always
  records which infrastructures were actually loaded.
- **Spatial proximity is not identity.** Two instruments 800 m apart may be one facility or
  two. That is why the ground-truth loop exists, and why name similarity is reported next
  to distance instead of being folded into a single opaque score.
- **The scores are only as good as the review.** With a handful of adjudicated pairs,
  precision and recall are indicative, not conclusive. The count is printed alongside them
  so nobody reads more into the number than it can carry.

---

## Data sources

| Infrastructure | Endpoint | Notes |
| --- | --- | --- |
| ICOS | `https://meta.icos-cp.eu/sparql` | SPARQL over the `cpmeta` OWL ontology; every object carries a Handle PID |
| eLTER | `https://deims.org/api/sites` | DEIMS-SDR REST API; WKT centroid per site, boundaries on the detail records |
| ACTRIS | `https://prod-actris-md.nilu.no/facilities` | optional, best-effort |

Raw responses are cached verbatim in `data/raw/` so any row can be traced back to an
unedited response. Data belongs to the respective infrastructures and is used here under
their own terms; please cite them, not this repository, if you use the data.

## Repository layout

```
src/ri_harmonize/
  schema.py     canonical station schema + name normalisation
  sources.py    one adapter per infrastructure, with response caching
  cluster.py    haversine DBSCAN, unit-sphere k-means baseline, eps sweep, pair extraction
  geo.py        projected-CRS buffering, spatial joins, GeoPackage/GeoJSON output
  evaluate.py   ground-truth loading, scoring, review-sheet generation
  report.py     figures and the written run summary
  cli.py        `run` and `review`
data/ground_truth/manual_pairs.csv   hand-checked pairs (tracked in git — it is the asset)
tests/                               13 tests, synthetic fixtures, no network
```

MIT licensed. Built as a pilot for a Master's thesis on data harmonisation across European
research infrastructures.
