"""Step 2 (Table A) of site_terms_plan.md: per-field specification table.

For each of the 117 canonical fields in final_field_comparison.csv, produce one
row of field-level metadata. Table B (per-site values) is a separate script.

Status semantics (PM 2026-11-11):
- populated: at least one associated allowlist path has in_allowlist=true
- not_in_cached_response: no allowlist path found
- excluded_by_rule: allowlist paths exist, none with in_allowlist=true

No values content: data_type inferred from cache, observed values summarised
briefly (count-only for DEIMS/EnvThes; short values only for CC0 RIs),
definition from canonical CSV with per-RI overrides (including CC0 ACTRIS
vocabulary definitions), no WKT anywhere.

Requires raw cache present BEFORE opening the output, so a clean clone fails
without clobbering the committed CSV.
"""
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

CANONICAL    = Path("outputs/final_field_comparison.csv")
ALLOWLIST    = Path("outputs/site_terms_field_allowlist.csv")
ACTRIS_DEFS  = Path("outputs/actris_field_definitions.csv")
RAW_DEIMS    = Path("data/raw/deims_detail")
RAW_ICOS     = Path("data/raw")
RAW_ACTRIS   = Path("data/raw/actris_facilities.json")
OUT          = Path("outputs/site_terms_fields.csv")

EXPECTED_ROWS   = 117
MAX_OBSERVED    = 250
MAX_DISTINCT    = 10
MAX_SAMPLE_LEN  = 40

INDEX_RE        = re.compile(r"\[\d+\]")
WKT_RE          = re.compile(r"(POINT|POLYGON|LINESTRING|MULTIPOLYGON|MULTILINESTRING|GEOMETRYCOLLECTION)\s*\(")

DEIMS_MARKER    = "[FLAGGED: pending licence provenance - EnvThes scheme: http://vocabs.lter-europe.net/EnvThes/]"
DEIMS_LICENCE   = "DEIMS site metadata, CC BY-NC 4.0, https://deims.org/terms"
ICOS_LICENCE    = "ontology CC0 (cc:license, ICOS ERIC 2024); per-concept licence not stated; ICOS licence page not verified by us"
ACTRIS_LICENCE  = "ACTRIS vocabulary CC0 1.0 (confirmed)"

ICOS_EXPLICIT_MAP = {
    "lat": "hasLatitude",
    "lon": "hasLongitude",
    "country": "countryCode",
    "wigos": "hasWigosId",
}


def validate_inputs():
    if not CANONICAL.exists():
        sys.exit(f"missing canonical field list: {CANONICAL}")
    if not ALLOWLIST.exists():
        sys.exit(f"missing allowlist: {ALLOWLIST}")
    if not ACTRIS_DEFS.exists():
        sys.exit(f"missing ACTRIS field definitions: {ACTRIS_DEFS}")
    if not list(RAW_DEIMS.glob("*.json")):
        sys.exit(f"no DEIMS detail JSON under {RAW_DEIMS} "
                 f"(gitignored; a clean clone cannot run this script)")


def strip_index(p):
    return INDEX_RE.sub("[]", p)


def norm_deims(p):
    p = p.strip()
    if p.startswith("attributes."):
        p = p[len("attributes."):]
    return strip_index(p).lower()


def norm_actris(p):
    return p.strip().lower()


def norm_icos_canonical(p):
    p = p.strip()
    if "#" in p:
        p = p.split("#", 1)[1]
    if p.startswith("has") and len(p) > 3:
        p = p[3:]
    return p.lower()


def icos_path_to_canonical(p):
    if p in ICOS_EXPLICIT_MAP:
        return ICOS_EXPLICIT_MAP[p]
    return p


def deims_matches(canonical_field, path):
    c = norm_deims(canonical_field)
    pn = norm_deims(path)
    return pn == c or pn.startswith(c + ".")


def icos_matches(canonical_field, path):
    c = norm_icos_canonical(canonical_field)
    pn = norm_icos_canonical(icos_path_to_canonical(path))
    return pn == c


def actris_matches(canonical_field, path):
    c = norm_actris(canonical_field)
    pn = norm_actris(path)
    return pn == c or pn.startswith(c + ".")


def _find_at_path(obj, target):
    def _walk(o, prefix):
        if isinstance(o, dict):
            for k, v in o.items():
                cur = f"{prefix}.{k}" if prefix else k
                if cur == target:
                    yield v
                yield from _walk(v, cur)
        elif isinstance(o, list):
            for item in o:
                yield from _walk(item, prefix)
    yield from _walk(obj, "")


def values_deims(path, attrs_list):
    t = path
    if t.startswith("attributes."):
        t = t[len("attributes."):]
    t = strip_index(t).replace("[]", "")
    out = []
    for attrs in attrs_list:
        for v in _find_at_path(attrs, t):
            out.append(v)
    return out


def values_actris(path, records):
    out = []
    for rec in records:
        for v in _find_at_path(rec, path):
            out.append(v)
    return out


def values_icos(key, bindings):
    out = []
    for b in bindings:
        if key in b:
            v = b[key]
            if isinstance(v, dict) and "value" in v:
                out.append(v["value"])
            else:
                out.append(v)
    return out


def _unwrap_scalar_list(values, path=""):
    if path.split(".")[-1] == "facility_type":
        unwrapped = []
        for v in values:
            if isinstance(v, list):
                unwrapped.extend(v)
            else:
                unwrapped.append(v)
        return unwrapped
    return values


def infer_data_type(values, path=""):
    if "coordinates" in path.lower():
        return "geometry"
    if not values:
        return "unknown"
    values = _unwrap_scalar_list(values, path)
    clean = [v for v in values if v is not None and str(v).strip() not in ("", "None", "nan")]
    if not clean:
        return "unknown"
    if any(isinstance(v, (dict, list)) for v in clean):
        return "container"
    if all(isinstance(v, (int, float)) for v in clean):
        return "number"
    try:
        for v in clean:
            float(v)
        return "number"
    except (ValueError, TypeError):
        pass
    if all(str(v).lower() in ("true", "false") for v in clean):
        return "boolean"
    if all(isinstance(v, str) and WKT_RE.match(v.strip()) for v in clean):
        return "geometry"
    return "string"


def summarize(values, path="", ri=""):
    values = _unwrap_scalar_list(values, path)
    clean = [v for v in values if v is not None and str(v).strip() not in ("", "None", "nan")]
    if not clean:
        return ""
    n_obs = len(clean)

    # Geometry / coordinate values are NEVER echoed (PM 2026-11-11):
    # Table A carries the field spec only; Table B parses to numeric lat/lon.
    if "coordinates" in path.lower():
        return f"n={n_obs} (geometry; parsed to numeric lat/lon in Table B; not echoed here)"
    if any(isinstance(v, str) and WKT_RE.match(v.strip()) for v in clean):
        return f"n={n_obs} (geometry; parsed to numeric lat/lon in Table B; not echoed here)"

    # DEIMS and EnvThes values are NEVER echoed (CC BY-NC / provenance rule):
    # output counts only, never string values, UUIDs, or EnvThes terms.
    if str(ri).strip().upper() in ("DEIMS", "ENVTHES"):
        n_distinct = len({json.dumps(v, sort_keys=True, default=str) for v in clean})
        return f"n={n_obs} distinct={n_distinct}"

    try:
        nums = sorted({float(v) for v in clean})
        return f"n={n_obs} distinct={len(nums)} range={nums[0]}..{nums[-1]}"
    except (ValueError, TypeError):
        pass
    distinct = sorted({str(v) for v in clean})
    if len(distinct) <= MAX_DISTINCT and all(len(d) <= MAX_SAMPLE_LEN for d in distinct):
        s = " | ".join(distinct)
        return s if len(s) <= MAX_OBSERVED else s[:MAX_OBSERVED] + "..."
    sample = " | ".join(d[:MAX_SAMPLE_LEN] for d in distinct[:5])
    return f"n={n_obs} distinct={len(distinct)} sample={sample[:MAX_OBSERVED]}"


def load_actris_definitions():
    df = pd.read_csv(ACTRIS_DEFS, keep_default_na=False)
    defs = {}
    for _, row in df.iterrows():
        field_name = str(row.get("field", "")).strip()
        if field_name:
            defs[field_name] = {
                "used": str(row.get("used_as_field_definition", "")).strip().lower() == "yes",
                "definition": str(row.get("vocabulary_definition", "")).strip(),
                "concept_uri": str(row.get("vocabulary_concept_uri", "")).strip(),
            }
    return defs


def main():
    validate_inputs()

    canon = pd.read_csv(CANONICAL, keep_default_na=False)
    allow = pd.read_csv(ALLOWLIST, keep_default_na=False)
    actris_defs = load_actris_definitions()

    deims_attrs = [json.loads(f.read_text()).get("attributes", {})
                   for f in sorted(RAW_DEIMS.glob("*.json"))]

    icos_bindings = []
    for f in sorted(glob.glob(str(RAW_ICOS / "icos_stations_page_*.json"))):
        d = json.loads(Path(f).read_text())
        if isinstance(d, dict) and "results" in d:
            icos_bindings.extend(d["results"].get("bindings", []))

    actris_records = []
    if RAW_ACTRIS.exists():
        d = json.loads(RAW_ACTRIS.read_text())
        actris_records = d if isinstance(d, list) else [d]

    rows = []
    for _, r in canon.iterrows():
        ri = str(r["ri"]).strip().upper()
        field = str(r["field"]).strip()
        definition_src = str(r.get("definition", "") or "").strip()
        if definition_src.lower() == "nan":
            definition_src = ""
        controlled_vocab = ""

        if ri == "DEIMS":
            sub = allow[(allow["ri"] == "DEIMS") & (allow["field_path"].apply(lambda p: deims_matches(field, p)))]
            getter = lambda p: values_deims(p, deims_attrs)
            definition = DEIMS_MARKER
            licence = DEIMS_LICENCE
        elif ri == "ICOS":
            sub = allow[(allow["ri"] == "ICOS") & (allow["field_path"].apply(lambda p: icos_matches(field, p)))]
            getter = lambda p: values_icos(p if p in ICOS_EXPLICIT_MAP else p, icos_bindings)
            if definition_src:
                definition = f"{definition_src} [{ICOS_LICENCE}]"
            else:
                definition = f"[NO DEFINITION] [{ICOS_LICENCE}]"
            licence = ICOS_LICENCE
        elif ri == "ACTRIS":
            sub = allow[(allow["ri"] == "ACTRIS") & (allow["field_path"].apply(lambda p: actris_matches(field, p)))]
            getter = lambda p: values_actris(p, actris_records)
            adef = actris_defs.get(field)
            if adef and adef["used"] and adef["definition"]:
                definition = adef["definition"]
                controlled_vocab = adef["concept_uri"]
            else:
                definition = definition_src if definition_src else "[NO DEFINITION]"
            licence = ACTRIS_LICENCE
        else:
            continue

        populated = sub[sub["in_allowlist"] == True]["field_path"].tolist()
        all_paths = sub["field_path"].tolist()

        if len(sub) == 0:
            status = "not_in_cached_response"
            ri_field_path = ""
            data_type = "unknown"
            observed = ""
        elif populated:
            status = "populated"
            ri_field_path = "|".join(populated)
            if len(populated) == 1:
                vals = getter(populated[0])
                data_type = infer_data_type(vals, populated[0])
                observed = summarize(vals, populated[0], ri=ri)
            else:
                data_type = "container"
                observed = f"populated via {len(populated)} children"
        else:
            status = "excluded_by_rule"
            ri_field_path = "|".join(all_paths)
            if all_paths:
                vals = getter(all_paths[0])
                data_type = infer_data_type(vals, all_paths[0])
            else:
                data_type = "unknown"
            observed = ""  # excluded_by_rule never echoes values

        rows.append({
            "canonical_concept": field,
            "ri": ri,
            "ri_field_path": ri_field_path,
            "ri_field_name": field,
            "data_type": data_type,
            "controlled_vocabulary": controlled_vocab,
            "controlled_values_observed": observed,
            "definition": definition,
            "in_scope": True,
            "status": status,
            "licence": licence,
        })

    df = pd.DataFrame(rows)

    # Guards before writing
    if len(df) != EXPECTED_ROWS:
        sys.exit(f"expected {EXPECTED_ROWS} rows, built {len(df)}")
    for col in ("controlled_values_observed", "definition"):
        bad = df[df[col].apply(lambda s: bool(WKT_RE.search(str(s))))]
        if len(bad):
            sys.exit(f"WKT text leaked into column {col!r}: {bad.head().to_dict('records')}")

    df.to_csv(OUT, index=False)

    print(f"wrote {OUT}: {len(df)} rows")
    print("\nby RI + status:")
    print(df.groupby(["ri", "status"]).size().to_string())
    print("\nby data_type:")
    print(df.groupby(["ri", "data_type"]).size().to_string())


if __name__ == "__main__":
    main()
