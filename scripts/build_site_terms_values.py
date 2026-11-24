"""Step 3 (Table B) of site_terms_plan.md: per-site values table.

Produces:
- outputs/site_terms_values.csv (committed public table; 6-column schema):
    ri, site_id, canonical_concept, field_path, value, value_source
  * ACTRIS (CC0 1.0): observed values for confirmed pairs (same_place == "yes")
    in outputs/finland_candidates_labelled.csv.
  * DEIMS & ICOS: count-only rows (n=<obs> distinct=<distinct>), matching Table A
    licence rules (no DEIMS/ICOS data values, site names, or UUIDs echoed).
- outputs/site_terms_values_run.json (committed run & skip report).
- outputs/site_terms_values_LOCAL.csv (gitignored local-only file with full
  exploded values across DEIMS, ICOS, and ACTRIS for local supervisor demos).

Rules (PM decisions on Table B):
1. Explicit allowlist only (outputs/site_terms_field_allowlist.csv, in_allowlist=true).
2. Pair filter: finland_candidates_labelled.csv filtered to same_place == "yes"
   only (30 rows -> 16 ICOS stations, 9 ACTRIS facilities); DEIMS uses the 20
   Finnish sites in outputs/deims_networks_finland.csv.
3. Values > 80 chars: skipped individually and logged in the skip report (never
   aborts and never modifies the verified allowlist).
4. Containers: scalar lists (e.g. ACTRIS facility_type, DEIMS geographic.country,
   DEIMS geoBonBiome) are exploded into one row per scalar element; dict values
   and non-scalar structures (monthlyAverage, referencePeriod) are skipped and
   logged in the skip report.
5. Coordinates: parsed to numeric lat/lon and emitted as separate .lat and .lon
   rows with numeric string values in the 6-column schema.
6. ACTRIS gawid_uri: literal "None" is treated as missing (data-quality rule).
"""
from collections import Counter, defaultdict
import glob
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

ALLOWLIST    = Path("outputs/site_terms_field_allowlist.csv")
TABLE_A      = Path("outputs/site_terms_fields.csv")
DEIMS_SITES  = Path("outputs/deims_networks_finland.csv")
CANDIDATES   = Path("outputs/finland_candidates_labelled.csv")
RAW_DEIMS    = Path("data/raw/deims_detail")
RAW_ICOS     = Path("data/raw")
RAW_ACTRIS   = Path("data/raw/actris_facilities.json")

OUT_PUBLIC   = Path("outputs/site_terms_values.csv")
OUT_LOCAL    = Path("outputs/site_terms_values_LOCAL.csv")
OUT_REPORT   = Path("outputs/site_terms_values_run.json")

MAX_VALUE_LEN = 80
COLUMNS = ["ri", "site_id", "canonical_concept", "field_path", "value", "value_source"]

POINT_WKT_RE = re.compile(
    r"^\s*POINT\s*\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)\s*$",
    re.IGNORECASE,
)
ANY_WKT_RE = re.compile(
    r"(POINT|POLYGON|LINESTRING|MULTIPOLYGON|MULTILINESTRING|GEOMETRYCOLLECTION)\s*\(",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+")


def validate_inputs():
    for req in (ALLOWLIST, TABLE_A, DEIMS_SITES, CANDIDATES):
        if not req.exists():
            sys.exit(f"missing required input file: {req}")
    if not list(RAW_DEIMS.glob("*.json")):
        sys.exit(
            f"missing raw cache under {RAW_DEIMS} "
            "(gitignored; a clean clone cannot regenerate Table B)"
        )
    if not RAW_ACTRIS.exists():
        sys.exit(f"missing raw ACTRIS cache: {RAW_ACTRIS}")
    if not list(RAW_ICOS.glob("icos_stations_page_*.json")):
        sys.exit(f"missing raw ICOS cache under {RAW_ICOS}")


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_canonical_lookup(table_a: pd.DataFrame) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for _, row in table_a.iterrows():
        ri = str(row["ri"]).strip().upper()
        concept = str(row["canonical_concept"]).strip()
        raw_paths = str(row["ri_field_path"]).strip()
        if not raw_paths:
            continue
        for fp in raw_paths.split("|"):
            fp = fp.strip()
            if fp:
                lookup[(ri, fp)] = concept
    return lookup


def walk_values(obj, target: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target:
                yield v
            elif target.startswith(k + "."):
                yield from walk_values(v, target[len(k) + 1 :])
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_values(item, target)


def is_missing(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s in ("", "None", "nan", "NaN")


def format_num_str(x) -> str:
    f = float(x)
    return str(f)


def parse_deims_point(val) -> tuple[str, str] | None:
    if not isinstance(val, str):
        return None
    m = POINT_WKT_RE.match(val)
    if not m:
        return None
    lon_s, lat_s = m.group(1), m.group(2)
    return format_num_str(lat_s), format_num_str(lon_s)


def parse_actris_coords(val) -> tuple[str, str] | None:
    if isinstance(val, list) and len(val) >= 2:
        lon_v, lat_v = val[0], val[1]
        if lon_v is not None and lat_v is not None:
            return format_num_str(lat_v), format_num_str(lon_v)
    return None


def extract_scalar_items(
    ri: str,
    field_path: str,
    raw_values: list,
    skip_counts: Counter,
) -> list[tuple[str, str]]:
    """Return list of (effective_field_path, clean_scalar_string) pairs."""
    out: list[tuple[str, str]] = []

    for v in raw_values:
        if is_missing(v):
            if ri == "ACTRIS" and field_path == "gawid_uri" and str(v).strip() == "None":
                skip_counts[f"{ri}:{field_path}:literal_None_defect"] += 1
            continue

        # Coordinate parsing -> separate .lat and .lon rows
        if ri == "DEIMS" and field_path == "attributes.geographic.coordinates":
            parsed = parse_deims_point(v)
            if parsed is None:
                skip_counts[f"{ri}:{field_path}:unparseable_geometry"] += 1
            else:
                lat_s, lon_s = parsed
                out.append((f"{field_path}.lat", lat_s))
                out.append((f"{field_path}.lon", lon_s))
            continue

        if ri == "ACTRIS" and field_path == "location.coordinates":
            parsed = parse_actris_coords(v)
            if parsed is None:
                skip_counts[f"{ri}:{field_path}:unparseable_geometry"] += 1
            else:
                lat_s, lon_s = parsed
                out.append((f"{field_path}.lat", lat_s))
                out.append((f"{field_path}.lon", lon_s))
            continue

        # Containers: skip dicts and monthlyAverage structures; explode other scalar lists
        if isinstance(v, dict):
            skip_counts[f"{ri}:{field_path}:dict_container"] += 1
            continue

        if field_path.endswith(".monthlyAverage"):
            skip_counts[f"{ri}:{field_path}:monthlyAverage_container"] += 1
            continue

        if isinstance(v, list):
            non_null = [item for item in v if not is_missing(item)]
            if not non_null:
                continue
            if any(isinstance(item, (dict, list)) for item in non_null):
                skip_counts[f"{ri}:{field_path}:non_scalar_list_container"] += 1
                continue
            for item in non_null:
                s = str(item).strip()
                if len(s) > MAX_VALUE_LEN:
                    skip_counts[f"{ri}:{field_path}:over_80_chars"] += 1
                else:
                    out.append((field_path, s))
            continue

        # Scalar value
        s = str(v).strip()
        if len(s) > MAX_VALUE_LEN:
            skip_counts[f"{ri}:{field_path}:over_80_chars"] += 1
        else:
            out.append((field_path, s))

    return out


def guard_dataframe(df: pd.DataFrame, *, public: bool):
    if list(df.columns) != COLUMNS:
        sys.exit(f"unexpected columns: {list(df.columns)}")
    for col in COLUMNS:
        bad_wkt = df[df[col].astype(str).apply(lambda s: bool(ANY_WKT_RE.search(s)))]
        if len(bad_wkt):
            sys.exit(f"WKT leaked into {col!r}: {bad_wkt.head().to_dict('records')}")
        bad_email = df[df[col].astype(str).apply(lambda s: bool(EMAIL_RE.search(s)))]
        if len(bad_email):
            sys.exit(f"Email leaked into {col!r}")
    too_long = df[df["value"].astype(str).str.len() > MAX_VALUE_LEN]
    if len(too_long):
        sys.exit(f"Value > {MAX_VALUE_LEN} chars leaked: {too_long.head().to_dict('records')}")
    if public:
        non_actris = df[df["ri"] != "ACTRIS"]
        count_re = re.compile(r"^n=\d+ distinct=\d+$")
        bad_public = non_actris[~non_actris["value"].astype(str).str.match(count_re)]
        if len(bad_public):
            sys.exit(f"Non-count value in public DEIMS/ICOS row: {bad_public.head().to_dict('records')}")


def main():
    validate_inputs()

    allow_df = pd.read_csv(ALLOWLIST, keep_default_na=False)
    in_allow = allow_df[allow_df["in_allowlist"] == True].copy()
    table_a = pd.read_csv(TABLE_A, keep_default_na=False)
    canon_lookup = build_canonical_lookup(table_a)

    # 1. Load 20 Finnish DEIMS sites
    deims_df = pd.read_csv(DEIMS_SITES, keep_default_na=False)
    deims_uuids = [u.strip() for u in deims_df["uuid"].tolist() if u.strip()]
    deims_cache = {}
    for uid in deims_uuids:
        p = RAW_DEIMS / f"{uid}.json"
        if not p.exists():
            sys.exit(f"missing DEIMS detail JSON for {uid}: {p}")
        deims_cache[uid] = json.loads(p.read_text()).get("attributes", {})

    # 2. Load confirmed pairs (same_place == "yes" only, 30 rows)
    cand_df = pd.read_csv(CANDIDATES, keep_default_na=False)
    yes_df = cand_df[cand_df["same_place"].astype(str).str.strip() == "yes"].copy()

    icos_targets: dict[str, str] = {}  # uri -> stationId
    actris_target_ids: set[str] = set()
    for _, r in yes_df.iterrows():
        for side in ("a", "b"):
            ri_val = str(r[f"ri_{side}"]).strip().upper()
            rec_id = str(r[f"record_id_{side}"]).strip()
            src_id = str(r[f"source_id_{side}"]).strip()
            if ri_val == "ICOS" and rec_id:
                icos_targets[rec_id] = src_id or rec_id
            elif ri_val == "ACTRIS" and rec_id:
                actris_target_ids.add(rec_id)

    icos_by_uri = {}
    for f in sorted(glob.glob(str(RAW_ICOS / "icos_stations_page_*.json"))):
        d = json.loads(Path(f).read_text())
        for b in d.get("results", {}).get("bindings", []):
            uri = b.get("uri", {}).get("value", "").strip()
            if uri:
                icos_by_uri[uri] = b

    actris_by_id = {
        str(rec["identifier"]).strip(): rec
        for rec in json.loads(RAW_ACTRIS.read_text())
        if "identifier" in rec
    }

    skip_counts: Counter = Counter()
    local_rows: list[dict] = []
    public_rows: list[dict] = []

    # Track per-(ri, canonical_concept, effective_field_path) values for DEIMS & ICOS count summaries
    agg_values: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    # --- Process DEIMS (20 Finnish sites) ---
    for _, arow in in_allow[in_allow["ri"] == "DEIMS"].iterrows():
        fp = str(arow["field_path"]).strip()
        concept = canon_lookup.get(("DEIMS", fp))
        if not concept:
            sys.exit(f"allowlisted DEIMS path missing from Table A: {fp}")
        stripped = fp[len("attributes.") :] if fp.startswith("attributes.") else fp
        target = stripped.replace("[]", "")

        for uid in deims_uuids:
            raw_vals = list(walk_values(deims_cache[uid], target))
            items = extract_scalar_items("DEIMS", fp, raw_vals, skip_counts)
            for eff_fp, val_s in items:
                local_rows.append({
                    "ri": "DEIMS",
                    "site_id": uid,
                    "canonical_concept": concept,
                    "field_path": eff_fp,
                    "value": val_s,
                    "value_source": "data/raw/deims_detail/*.json",
                })
                agg_values[("DEIMS", concept, eff_fp)].append(val_s)

    # --- Process ICOS (confirmed same_place == "yes" stations) ---
    for _, arow in in_allow[in_allow["ri"] == "ICOS"].iterrows():
        fp = str(arow["field_path"]).strip()
        concept = canon_lookup.get(("ICOS", fp))
        if not concept:
            sys.exit(f"allowlisted ICOS path missing from Table A: {fp}")

        for uri, station_id in sorted(icos_targets.items(), key=lambda kv: kv[1]):
            binding = icos_by_uri.get(uri)
            if not binding or fp not in binding:
                continue
            cell = binding[fp]
            raw_val = cell["value"] if isinstance(cell, dict) and "value" in cell else cell
            items = extract_scalar_items("ICOS", fp, [raw_val], skip_counts)
            for eff_fp, val_s in items:
                local_rows.append({
                    "ri": "ICOS",
                    "site_id": station_id,
                    "canonical_concept": concept,
                    "field_path": eff_fp,
                    "value": val_s,
                    "value_source": "data/raw/icos_stations_page_*.json",
                })
                agg_values[("ICOS", concept, eff_fp)].append(val_s)

    # Emit count-only rows for DEIMS and ICOS in public Table B
    for (ri, concept, eff_fp) in sorted(agg_values.keys()):
        vals = agg_values[(ri, concept, eff_fp)]
        n_obs = len(vals)
        n_distinct = len(set(vals))
        site_scope = "ALL_20_DEIMS_SITES" if ri == "DEIMS" else f"ALL_{len(icos_targets)}_ICOS_CONFIRMED_STATIONS"
        src_note = (
            "data/raw/deims_detail/*.json (count-only; CC BY-NC 4.0)"
            if ri == "DEIMS"
            else "data/raw/icos_stations_page_*.json (count-only; per-station licence unverified)"
        )
        public_rows.append({
            "ri": ri,
            "site_id": site_scope,
            "canonical_concept": concept,
            "field_path": eff_fp,
            "value": f"n={n_obs} distinct={n_distinct}",
            "value_source": src_note,
        })

    # --- Process ACTRIS (confirmed same_place == "yes" facilities; CC0 1.0 observed values) ---
    for _, arow in in_allow[in_allow["ri"] == "ACTRIS"].iterrows():
        fp = str(arow["field_path"]).strip()
        concept = canon_lookup.get(("ACTRIS", fp))
        if not concept:
            sys.exit(f"allowlisted ACTRIS path missing from Table A: {fp}")

        for aid in sorted(actris_target_ids):
            rec = actris_by_id.get(aid)
            if not rec:
                continue
            raw_vals = list(walk_values(rec, fp))
            items = extract_scalar_items("ACTRIS", fp, raw_vals, skip_counts)
            for eff_fp, val_s in items:
                row_obj = {
                    "ri": "ACTRIS",
                    "site_id": aid,
                    "canonical_concept": concept,
                    "field_path": eff_fp,
                    "value": val_s,
                    "value_source": "data/raw/actris_facilities.json (CC0 1.0)",
                }
                local_rows.append(row_obj)
                public_rows.append(row_obj)

    pub_df = pd.DataFrame(public_rows, columns=COLUMNS).drop_duplicates().sort_values(
        ["ri", "site_id", "canonical_concept", "field_path", "value"]
    ).reset_index(drop=True)

    loc_df = pd.DataFrame(local_rows, columns=COLUMNS).drop_duplicates().sort_values(
        ["ri", "site_id", "canonical_concept", "field_path", "value"]
    ).reset_index(drop=True)

    guard_dataframe(pub_df, public=True)
    guard_dataframe(loc_df, public=False)

    pub_df.to_csv(OUT_PUBLIC, index=False)
    loc_df.to_csv(OUT_LOCAL, index=False)

    report = {
        "script": "scripts/build_site_terms_values.py",
        "git_head_at_run": git_head(),
        "pair_filter": {
            "source": str(CANDIDATES),
            "rule": "same_place == 'yes' only",
            "total_candidate_rows": int(len(cand_df)),
            "included_rows": int(len(yes_df)),
            "excluded_rows": int(len(cand_df) - len(yes_df)),
            "excluded_reason": "Other pairs are proposed/unreviewed or unclear and excluded from supervisor-facing tables.",
            "included_icos_stations": sorted(icos_targets.values()),
            "included_actris_facilities": sorted(actris_target_ids),
            "included_deims_sites_count": len(deims_uuids),
        },
        "licence_scope": {
            "public_csv": str(OUT_PUBLIC),
            "public_rule": "Observed values emitted for ACTRIS (CC0 1.0) only; DEIMS and ICOS emitted as counts only (n=... distinct=...).",
            "local_csv": str(OUT_LOCAL),
            "local_rule": "Gitignored local-only file containing full exploded values for DEIMS, ICOS, and ACTRIS.",
        },
        "skipped_values_by_rule": dict(sorted(skip_counts.items())),
        "output": {
            "public_file": str(OUT_PUBLIC),
            "public_rows": int(len(pub_df)),
            "public_rows_by_ri": pub_df["ri"].value_counts().to_dict(),
            "public_sha256": sha256_file(OUT_PUBLIC),
            "local_file": str(OUT_LOCAL),
            "local_rows": int(len(loc_df)),
            "local_rows_by_ri": loc_df["ri"].value_counts().to_dict(),
        },
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2) + "\n")

    print(f"wrote {OUT_PUBLIC}: {len(pub_df)} rows (by RI: {pub_df['ri'].value_counts().to_dict()})")
    print(f"wrote {OUT_LOCAL}: {len(loc_df)} rows (gitignored)")
    print(f"wrote {OUT_REPORT}")
    print("skipped_values_by_rule:", dict(sorted(skip_counts.items())))


if __name__ == "__main__":
    main()
