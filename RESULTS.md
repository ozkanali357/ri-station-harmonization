# Results

<!--
Fill this in after your first real run (`python -m ri_harmonize.cli run -v`), then delete
this comment. Copy the actual numbers out of outputs/summary.md — do not estimate them.
Keep it short: five honest bullets beat two vague paragraphs.
-->

**Run date:** _YYYY-MM-DD_ · **Parameters:** eps = _ km, min_samples = _, buffer = _ km

## Records loaded

_N_ ICOS stations, _N_ eLTER sites, _N_ ACTRIS facilities with usable coordinates
(_N_ total). _Say here how many records had to be dropped for missing or invalid
coordinates — that number is itself a data-quality finding._

## Candidate cross-infrastructure matches

- DBSCAN (haversine, eps = _ km): **_N_** candidate pairs
- k-means baseline (k = _): **_N_** candidate pairs
- Buffer intersection (EPSG:3035, _ km): **_N_** candidate pairs

_One sentence on where the methods disagreed and which was more useful._

## Choice of eps

_Which radius you chose and why, referring to the over-merge column in
`outputs/eps_sweep.csv`. Name the eps at which same-infrastructure stations start
collapsing into one cluster._

## Scored against hand-checked ground truth

_N_ pairs adjudicated by hand. DBSCAN: precision _, recall _, F1 _.
_N_ candidates not yet reviewed.

_One sentence on the errors: what did the false positives have in common?_

## What surprised me

_Two or three lines. Concrete observations only — a station present in one registry and
absent from another, an identifier that exists for some station classes and not others, a
placeholder elevation, a name that matches perfectly while the coordinates disagree._
