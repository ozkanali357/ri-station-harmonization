"""Step 1 of site_terms_plan.md: enumerate site-terms field paths from cached raw.

Output: outputs/site_terms_field_allowlist.csv
Columns: ri, field_path, in_allowlist, notes

Rules (PM 2026-11-11):
- in_allowlist=true only if path maps to a canonical field AND is not
  prose, not contact, not geometry, not container, not URL, and (for
  narrative-like DEIMS fields) all cached values are short.
- Prose, contact, geometry, container, URL: always false.
- ACTRIS uses exact/last-segment/prefix match for canonical names.
- ICOS uses explicit short-name -> canonical-property map.
- Container demotion: parent-only paths (whole-object values) are false;
  their leaf children remain eligible.
- Narrative-like DEIMS fields kept only if every cached value is a
  string of <= 80 chars; otherwise demoted with a REVIEW note.
- Requires raw cache and canonical field list to exist BEFORE opening
  the output file, so a clean clone fails without clobbering anything.
"""
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

RAW_DEIMS  = Path("data/raw/deims_detail")
RAW_ICOS   = Path("data/raw")
RAW_ACTRIS = Path("data/raw/actris_facilities.json")
CANONICAL  = Path("outputs/final_field_comparison.csv")
OUT        = Path("outputs/site_terms_field_allowlist.csv")

SAMPLE_LIMIT    = 3
MAX_VALUE_LEN   = 80
PROSE_LAST      = {"abstract", "description", "summary", "notes", "note",
                   "citation", "alt", "purpose", "objectives"}
PROSE_SUBSTRING = ("abstract", "description", "summary")
CONTACT_TOKENS  = ("contact", "sitemanager", "metadataprovider", "email", "orcid")
GEOMETRY_LAST   = {"boundaries", "boundary", "geometry", "polygon", "wkt",
                   "vertices", "vertex", "coordinates_wkt", "bbox"}
INDEX_RE        = re.compile(r"\[\d+\]")

# Container demotion: parent-only paths with whole-object values.
ACTRIS_CONTAINERS = {"extra_metadata", "extra_metadata.insitu", "location"}
DEIMS_CONTAINER_TOKENS = ("relatedIdentifiers", "relatedSites", "relatedResources")

# Narrative-like DEIMS fields: keep only if every cached value is short.
# Full paths (after stripping "attributes."), matching the actual cache structure.
NARRATIVE_DEIMS = {
    "environmentalCharacteristics.geology",
    "environmentalCharacteristics.hydrology",
    "environmentalCharacteristics.soils",
    "environmentalCharacteristics.vegetation",
    "focusDesignScale.experiments.design",
    "focusDesignScale.experiments.scale",
    "focusDesignScale.observations.design",
    "focusDesignScale.observations.scale",
}

# Raw ICOS binding key -> canonical dcat property name.
ICOS_EXPLICIT_MAP = {
    "lat":     "hasLatitude",
    "lon":     "hasLongitude",
    "country": "countryCode",
    "wigos":   "hasWigosId",
}


def validate_inputs():
    if not CANONICAL.exists():
        sys.exit(f"missing canonical field list: {CANONICAL}")
    deims_files = list(RAW_DEIMS.glob("*.json"))
    if not deims_files:
        sys.exit(
            f"no DEIMS detail JSON files under {RAW_DEIMS}. "
            f"{RAW_DEIMS} is gitignored, so a clean clone cannot run this script. "
            "Fetch or copy the cache first."
        )


def walk(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f"{prefix}.{k}" if prefix else k
            yield cur
            yield from walk(v, cur)
    elif isinstance(obj, list):
        for item in obj[:SAMPLE_LIMIT]:
            yield from walk(item, f"{prefix}[]")


def collect_deims():
    paths = set()
    for f in sorted(RAW_DEIMS.glob("*.json")):
        d = json.loads(f.read_text())
        for p in walk(d.get("attributes", {})):
            paths.add(f"attributes.{p}")
    return paths


def collect_icos():
    paths = set()
    for f in sorted(glob.glob(str(RAW_ICOS / "icos_stations_page_*.json"))):
        d = json.loads(Path(f).read_text())
        if isinstance(d, dict) and "results" in d:
            for binding in d["results"].get("bindings", [])[:SAMPLE_LIMIT]:
                for k in binding.keys():
                    paths.add(k)
        elif isinstance(d, list) and d and isinstance(d[0], dict):
            for p in walk(d[0]):
                paths.add(p)
    return paths


def collect_actris():
    if not RAW_ACTRIS.exists():
        return set()
    d = json.loads(RAW_ACTRIS.read_text())
    sample = d[0] if isinstance(d, list) and d else d
    return set(walk(sample))


def load_canonical():
    df = pd.read_csv(CANONICAL, keep_default_na=False)
    for col in ("ri", "field"):
        if col not in df.columns:
            sys.exit(f"{CANONICAL} missing required column {col!r}")
    out = {"DEIMS": set(), "ICOS": set(), "ACTRIS": set()}
    for _, r in df.iterrows():
        ri = str(r["ri"]).strip().upper()
        name = str(r["field"]).strip()
        if ri in out and name:
            out[ri].add(name)
    return out


def find_all_values(obj, target_norm):
    def _walk(o, prefix):
        if isinstance(o, dict):
            for k, v in o.items():
                cur = f"{prefix}.{k}" if prefix else k
                if cur == target_norm:
                    yield v
                yield from _walk(v, cur)
        elif isinstance(o, list):
            for item in o:
                yield from _walk(item, prefix)
    yield from _walk(obj, "")


def narrative_values_are_short(deims_attrs_list, target_path):
    """True if every cached value at target is a short string (<= MAX_VALUE_LEN)."""
    target = target_path.replace("[]", "")
    seen_any = False
    for attrs in deims_attrs_list:
        for v in find_all_values(attrs, target):
            seen_any = True
            if isinstance(v, (dict, list)):
                return False
            if len(str(v)) > MAX_VALUE_LEN:
                return False
    return seen_any  # False if no values found at all


def norm_deims(p: str) -> str:
    p = p.strip()
    if p.startswith("attributes."):
        p = p[len("attributes."):]
    return INDEX_RE.sub("[]", p).lower()


def norm_actris(p: str) -> str:
    return p.strip().lower()


def norm_icos_canonical(p: str) -> str:
    p = p.strip()
    if "#" in p:
        p = p.split("#", 1)[1]
    if p.startswith("has") and len(p) > 3:
        p = p[3:]
    return p.lower()


def is_prose(path: str) -> bool:
    last = path.replace("[]", "").split(".")[-1].lower()
    return last in PROSE_LAST or any(t in last for t in PROSE_SUBSTRING)


def is_contact(path: str) -> bool:
    return any(t in path.lower() for t in CONTACT_TOKENS)


def is_geometry(path: str) -> bool:
    last = path.replace("[]", "").split(".")[-1].lower()
    return last in GEOMETRY_LAST


def is_url_field(path: str) -> bool:
    if "url" not in path.lower():
        return False
    last = path.replace("[]", "").split(".")[-1].lower()
    return last in {"url", "value"}


def is_container(path: str, ri: str) -> bool:
    if ri == "ACTRIS":
        return path in ACTRIS_CONTAINERS
    if ri == "DEIMS":
        stripped = path[len("attributes."):] if path.startswith("attributes.") else path
        for token in DEIMS_CONTAINER_TOKENS:
            if stripped == token or stripped.endswith("." + token):
                return True
    return False


def classify(path: str, canonical_name, ri: str, deims_attrs_list) -> tuple[bool, str]:
    if is_prose(path):
        return False, f"PROSE (canonical={canonical_name})" if canonical_name else "prose"
    if is_contact(path):
        return False, f"CONTACT (canonical={canonical_name})" if canonical_name else "contact"
    if is_container(path, ri):
        return False, f"CONTAINER (canonical={canonical_name})" if canonical_name else "container"
    if is_url_field(path):
        return False, f"URL field (canonical={canonical_name})" if canonical_name else "url"
    if is_geometry(path):
        return False, f"REVIEW: possible geometry (canonical={canonical_name})" if canonical_name else "REVIEW: possible geometry"
    if ri == "DEIMS" and canonical_name is not None:
        stripped = path[len("attributes."):] if path.startswith("attributes.") else path
        if stripped in NARRATIVE_DEIMS:
            if not narrative_values_are_short(deims_attrs_list, stripped):
                return False, f"REVIEW: narrative-like (values >{MAX_VALUE_LEN} chars or objects; canonical={canonical_name})"
    if canonical_name is None:
        return False, "no canonical match"
    return True, f"canonical={canonical_name}"


def find_actris_canonical(pn: str, c_actris: dict):
    if pn in c_actris:
        return c_actris[pn], "exact"
    last = pn.split(".")[-1]
    if last in c_actris:
        return c_actris[last], "last-segment"
    for canon_norm, canon_name in c_actris.items():
        if pn.startswith(canon_norm + "."):
            return canon_name, f"prefix={canon_norm}"
    return None, None


def main():
    validate_inputs()

    deims, icos, actris = collect_deims(), collect_icos(), collect_actris()
    print(f"enumerated: DEIMS={len(deims)} ICOS={len(icos)} ACTRIS={len(actris)}")

    canon = load_canonical()
    print(f"canonical:  DEIMS={len(canon['DEIMS'])} ICOS={len(canon['ICOS'])} ACTRIS={len(canon['ACTRIS'])}")

    # Load all DEIMS attrs once for narrative value checks
    deims_attrs = [json.loads(f.read_text()).get("attributes", {})
                   for f in sorted(RAW_DEIMS.glob("*.json"))]

    c_deims  = {norm_deims(c): c for c in canon["DEIMS"]}
    c_actris = {norm_actris(c): c for c in canon["ACTRIS"]}
    c_icos   = {norm_icos_canonical(c): c for c in canon["ICOS"]}

    rows = []
    hits = {"DEIMS": set(), "ICOS": set(), "ACTRIS": set()}

    for p in sorted(deims):
        name = c_deims.get(norm_deims(p))
        if name: hits["DEIMS"].add(name)
        allowed, note = classify(p, name, "DEIMS", deims_attrs)
        rows.append({"ri": "DEIMS", "field_path": p, "in_allowlist": allowed, "notes": note})

    for p in sorted(actris):
        pn = norm_actris(p)
        name, how = find_actris_canonical(pn, c_actris)
        if name: hits["ACTRIS"].add(name)
        allowed, note = classify(p, name, "ACTRIS", deims_attrs)
        if allowed and how and how != "exact":
            note = f"{note} via {how}"
        rows.append({"ri": "ACTRIS", "field_path": p, "in_allowlist": allowed, "notes": note})

    for p in sorted(icos):
        if p in ICOS_EXPLICIT_MAP:
            name = ICOS_EXPLICIT_MAP[p]
            how = "explicit-map"
        else:
            pn = norm_icos_canonical(p)
            name = c_icos.get(pn)
            how = "normalized" if name else None
        if name: hits["ICOS"].add(name)
        allowed, note = classify(p, name, "ICOS", deims_attrs)
        if allowed and how:
            note = f"{note} via {how}"
        rows.append({"ri": "ICOS", "field_path": p, "in_allowlist": allowed, "notes": note})

    if not rows:
        sys.exit("no rows enumerated — check that data/raw caches exist")

    df = pd.DataFrame(rows)
    required = {"ri", "field_path", "in_allowlist", "notes"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        sys.exit(f"missing required output columns: {missing_cols}")

    df.to_csv(OUT, index=False)

    print(f"\nwrote {OUT}: {len(df)} rows")
    for ri in ("DEIMS", "ICOS", "ACTRIS"):
        n = int(df[df["ri"] == ri]["in_allowlist"].sum())
        total = len([p for p in rows if p["ri"] == ri])
        print(f"  {ri:7s} {total:4d} paths, {n:3d} in_allowlist")

    print("\ncanonical names with NO matching path (review to add manual overrides):")
    for ri in ("DEIMS", "ICOS", "ACTRIS"):
        missing = canon[ri] - hits[ri]
        if missing:
            print(f"\n  {ri}: {len(missing)} / {len(canon[ri])}")
            for m in sorted(missing):
                print(f"    {m}")
        else:
            print(f"\n  {ri}: all {len(canon[ri])} matched")


if __name__ == "__main__":
    main()
