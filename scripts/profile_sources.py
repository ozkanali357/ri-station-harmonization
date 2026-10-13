"""Profile the harmonised station table by source.

This script reports only facts computed from the files it reads.  It never
infers relationships between sources and never decides whether two stations are
the same place.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from ri_harmonize import sources as _ri_sources

    _RI_SOURCES_ERROR = None
except Exception as exc:  # pragma: no cover - depends on repo layout
    _ri_sources = None
    _RI_SOURCES_ERROR = str(exc)

INPUT_CSV = ROOT / "data/interim/stations_harmonised.csv"
RAW_DIR = ROOT / "data/raw"
RAW_ACTRIS = RAW_DIR / "actris_facilities.json"
OUT = ROOT / "outputs"
OUT_CSV = OUT / "source_profile.csv"
OUT_MD = OUT / "source_profile.md"

PROFILE_COLUMNS = ["ri", "section", "key", "value", "count"]


def _add(rows, ri, section, key, value="", count=None):
    rows.append(
        {
            "ri": ri,
            "section": section,
            "key": str(key),
            "value": "" if value is None else str(value),
            "count": count,
        }
    )


def profile(df: pd.DataFrame) -> pd.DataFrame:
    """Return a long-format source profile for the harmonised station table.

    Parameters
    ----------
    df:
        DataFrame read from ``stations_harmonised.csv`` with
        ``dtype=str, keep_default_na=False``.  Empty fields are therefore empty
        strings, not NaN.
    """
    rows = []
    if df.empty:
        return pd.DataFrame(rows, columns=PROFILE_COLUMNS)

    sources = sorted(df["ri"].dropna().unique())

    for ri in sources:
        g = df[df["ri"] == ri]
        n_records = len(g)

        _add(rows, ri, "summary", "n_records", "", n_records)

        for value, count in g["id_scheme"].fillna("").astype(str).value_counts().items():
            _add(rows, ri, "id_scheme", value, "", int(count))

        for value, count in g["geometry_kind"].fillna("").astype(str).value_counts().items():
            _add(rows, ri, "geometry_kind", value, "", int(count))

        station_class = g["station_class"].fillna("").astype(str)
        _add(rows, ri, "station_class", "n_distinct", "", int(station_class.nunique()))
        top = (
            station_class.value_counts()
            .rename_axis("key")
            .reset_index(name="count")
            .sort_values(by=["count", "key"], ascending=[False, True])
            .head(15)
        )
        for _, row in top.iterrows():
            _add(rows, ri, "station_class", row["key"], "", int(row["count"]))

        key_counts = {}
        empty_json = 0
        for raw in g["extra_ids"].fillna("").astype(str):
            text = raw.strip()
            if text == "{}":
                empty_json += 1
            try:
                obj = json.loads(text) if text else {}
            except Exception:
                obj = {}
            if isinstance(obj, dict):
                for key in obj:
                    key_counts[key] = key_counts.get(key, 0) + 1

        for key in sorted(key_counts):
            _add(rows, ri, "extra_ids", key, "", int(key_counts[key]))
        _add(rows, ri, "extra_ids", "empty_json", "{}", int(empty_json))

        country = g["country"].fillna("").astype(str).str.strip()
        non_empty_country = country[country.ne("")]
        distinct_countries = sorted(non_empty_country.unique().tolist())
        _add(rows, ri, "country", "non_empty", "", int(len(non_empty_country)))
        _add(rows, ri, "country", "n_distinct", "", int(len(distinct_countries)))
        _add(
            rows,
            ri,
            "country",
            "distinct_values",
            ", ".join(distinct_countries),
            int(len(distinct_countries)),
        )

        lat_missing = int(pd.to_numeric(g["lat"], errors="coerce").isna().sum())
        lon_missing = int(pd.to_numeric(g["lon"], errors="coerce").isna().sum())
        elevation_missing = int(pd.to_numeric(g["elevation_m"], errors="coerce").isna().sum())
        name_missing = int(g["name"].fillna("").astype(str).str.strip().eq("").sum())

        _add(rows, ri, "missing", "lat", "", lat_missing)
        _add(rows, ri, "missing", "lon", "", lon_missing)
        _add(rows, ri, "missing", "elevation_m", "", elevation_missing)
        _add(rows, ri, "missing", "name", "", name_missing)

    return pd.DataFrame(rows, columns=PROFILE_COLUMNS)


def _compute_actris_dropped(path: Path):
    if not path.exists():
        return None, "raw cache not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"not computed: raw cache unreadable ({exc})"
    if not isinstance(data, list):
        return None, "not computed: raw cache is not a JSON list"

    dropped = 0
    for facility in data:
        if not isinstance(facility, dict):
            dropped += 1
            continue
        location = facility.get("location")
        coords = location.get("coordinates") if isinstance(location, dict) else None
        if not isinstance(coords, list) or len(coords) < 2:
            dropped += 1
    return dropped, "computed from data/raw/actris_facilities.json"


def _count_icos_raw(raw_dir: Path) -> int:
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    pages = manifest["sources"]["icos"]["pages"]
    total = 0
    for page in pages:
        payload = json.loads((raw_dir / page["file"]).read_text(encoding="utf-8"))
        total += len(payload.get("results", {}).get("bindings", []))
    return total


def _count_deims_raw(raw_dir: Path) -> int:
    payload = json.loads((raw_dir / "deims_sites.json").read_text(encoding="utf-8"))
    return len(payload) if isinstance(payload, list) else 0


def _bucket_attribution(rows):
    """Count rows removed by each of _finalise's filters, in order.

    Each row is counted once, in the first filter that removes it.
    Mirrors the exact order in ``ri_harmonize.sources._finalise``:
    blank record_id; missing lat/lon; out-of-range lat/lon;
    duplicate (ri, record_id).
    """
    buckets = {
        "blank_record_id": 0,
        "no_coordinates": 0,
        "out_of_range_coordinates": 0,
        "duplicate_record_id": 0,
    }
    if not rows:
        return buckets

    df = pd.DataFrame(rows)
    if df.empty or "record_id" not in df.columns:
        return buckets

    for col in ("lat", "lon", "elevation_m"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter 1: blank record_id
    mask = df["record_id"].fillna("").astype(str).str.strip().eq("")
    buckets["blank_record_id"] = int(mask.sum())
    df = df.loc[~mask].copy()

    # Filter 2: missing lat/lon
    mask = df["lat"].isna() | df["lon"].isna()
    buckets["no_coordinates"] = int(mask.sum())
    df = df.loc[~mask].copy()

    # Filter 3: out-of-range lat/lon
    mask = ~(df["lat"].between(-90, 90) & df["lon"].between(-180, 180))
    buckets["out_of_range_coordinates"] = int(mask.sum())
    df = df.loc[~mask].copy()

    # Filter 4: duplicate (ri, record_id), keep first
    mask = df.duplicated(subset=["ri", "record_id"], keep="first")
    buckets["duplicate_record_id"] = int(mask.sum())

    return buckets


def _dropped_for_icos_elter(ri, raw_dir):
    """Split dropped rows for ICOS / eLTER into the four _finalise buckets."""
    if _ri_sources is None:
        return None, f"not computed: adapter parsing not importable ({_RI_SOURCES_ERROR})"

    captured = {}
    original = _ri_sources._finalise

    def wrapper(rows):
        captured["rows"] = list(rows)
        return original(rows)

    try:
        _ri_sources._finalise = wrapper
        try:
            if ri == "ICOS":
                harmonised = _ri_sources.fetch_icos(raw_dir, offline=True)
                raw_count = _count_icos_raw(raw_dir)
            elif ri == "eLTER":
                harmonised = _ri_sources.fetch_deims(raw_dir, offline=True)
                raw_count = _count_deims_raw(raw_dir)
            else:
                return None, f"not computed: no adapter for {ri}"
        finally:
            _ri_sources._finalise = original
    except Exception as exc:
        return None, f"not computed: {exc}"

    captured_rows = captured.get("rows", [])
    buckets = _bucket_attribution(captured_rows)

    return {
        "raw_rows": raw_count,
        "passed_to_finalise": len(captured_rows),
        "blank_record_id": buckets["blank_record_id"],
        "no_coordinates": buckets["no_coordinates"],
        "out_of_range_coordinates": buckets["out_of_range_coordinates"],
        "duplicate_record_id": buckets["duplicate_record_id"],
        "harmonised": len(harmonised),
    }, "computed via ri_harmonize.sources._finalise"


def dropped_facts(sources, raw_dir: Path, actris_path: Path) -> pd.DataFrame:
    rows = []
    for ri in sources:
        if ri == "ACTRIS":
            count, desc = _compute_actris_dropped(actris_path)
            if count is None:
                _add(rows, ri, "dropped_before_harmonisation", "not_computed", desc, None)
            else:
                _add(rows, ri, "dropped_before_harmonisation", "dropped", desc, int(count))
        elif ri in ("ICOS", "eLTER"):
            data, desc = _dropped_for_icos_elter(ri, raw_dir)
            if data is None:
                _add(rows, ri, "dropped_before_harmonisation", "not_computed", desc, None)
            else:
                for key in (
                    "raw_rows",
                    "passed_to_finalise",
                    "blank_record_id",
                    "no_coordinates",
                    "out_of_range_coordinates",
                    "duplicate_record_id",
                    "harmonised",
                ):
                    _add(rows, ri, "dropped_before_harmonisation", key, "", int(data[key]))

                passed = data["passed_to_finalise"]
                harm = data["harmonised"]
                buckets = (
                    data["blank_record_id"]
                    + data["no_coordinates"]
                    + data["out_of_range_coordinates"]
                    + data["duplicate_record_id"]
                )
                if passed - harm != buckets:
                    _add(
                        rows,
                        ri,
                        "dropped_before_harmonisation",
                        "unattributed",
                        "",
                        passed - harm - buckets,
                    )
        else:
            _add(
                rows,
                ri,
                "dropped_before_harmonisation",
                "not_computed",
                "unknown source",
                None,
            )
    return pd.DataFrame(rows, columns=PROFILE_COLUMNS)


def _get_count(prof: pd.DataFrame, ri: str, section: str, key: str):
    row = prof[(prof["ri"] == ri) & (prof["section"] == section) & (prof["key"] == key)]
    if row.empty:
        return None
    return row.iloc[0]["count"]


def _build_notes(base_prof: pd.DataFrame, df: pd.DataFrame):
    notes = []
    if df.empty:
        return notes

    sources = sorted(df["ri"].dropna().unique())

    all_lat_zero = all(_get_count(base_prof, ri, "missing", "lat") == 0 for ri in sources)
    all_lon_zero = all(_get_count(base_prof, ri, "missing", "lon") == 0 for ri in sources)
    if all_lat_zero and all_lon_zero:
        notes.append(
            "Rows without coordinates are dropped before the CSV is written, so "
            "missing lat/lon in this table is 0 by construction."
        )

    for ri in sources:
        n_records = _get_count(base_prof, ri, "summary", "n_records")
        country_non_empty = _get_count(base_prof, ri, "country", "non_empty")
        elevation_missing = _get_count(base_prof, ri, "missing", "elevation_m")

        if country_non_empty == 0:
            notes.append(f"{ri}: country coverage is 0; adapter did not provide this field.")
        if elevation_missing == n_records:
            notes.append(
                f"{ri}: elevation_m is 100% missing; adapter did not provide this field."
            )

    return notes


def _md_cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).replace("|", "\\|").replace("\n", " ")


def _key_count_table(lines, rows):
    lines.append("| key | count |")
    lines.append("| --- | --- |")
    if rows.empty:
        lines.append("| | |")
    else:
        for _, row in rows.iterrows():
            lines.append(f"| {_md_cell(row['key'])} | {_md_cell(row['count'])} |")
    lines.append("")


def _value_count_table(lines, rows):
    lines.append("| value | count |")
    lines.append("| --- | --- |")
    if rows.empty:
        lines.append("| | |")
    else:
        for _, row in rows.iterrows():
            lines.append(f"| {_md_cell(row['key'])} | {_md_cell(row['count'])} |")
    lines.append("")


def _dropped_sentence(rows) -> str:
    if rows.empty:
        return ""
    d = {}
    for _, r in rows.iterrows():
        key = str(r["key"])
        cnt = r["count"]
        try:
            if cnt is None or pd.isna(cnt) or cnt == "":
                d[key] = None
            else:
                d[key] = int(cnt)
        except Exception:
            d[key] = None

    if "not_computed" in d:
        row = rows[rows["key"] == "not_computed"].iloc[0]
        return f"not computed: {row['value']}"

    if d.get("passed_to_finalise") is not None and d.get("harmonised") is not None:
        dropped = d["passed_to_finalise"] - d["harmonised"]
        buckets = sum(
            d.get(k, 0) or 0
            for k in (
                "blank_record_id",
                "no_coordinates",
                "out_of_range_coordinates",
                "duplicate_record_id",
            )
        )
        if dropped == buckets:
            return (
                f"Dropped = passed - harmonised = {dropped}; "
                f"the buckets sum to {buckets}."
            )
        return (
            f"Dropped = passed - harmonised = {dropped}; "
            f"the buckets sum to {buckets}; "
            f"unattributed: {dropped - buckets}."
        )

    if d.get("dropped") is not None:
        return f"Dropped = {d['dropped']}."

    return ""


def render_markdown(prof: pd.DataFrame, df: pd.DataFrame, base_prof: pd.DataFrame) -> str:
    lines = ["# Source profile", ""]

    for ri in sorted(prof["ri"].unique()):
        lines.append(f"## {ri}")
        lines.append("")
        sub = prof[prof["ri"] == ri]

        # summary: key | count
        lines.append("### summary")
        lines.append("")
        _key_count_table(lines, sub[sub["section"] == "summary"])

        # id_scheme: value | count
        lines.append("### id_scheme")
        lines.append("")
        _value_count_table(lines, sub[sub["section"] == "id_scheme"])

        # geometry_kind: value | count
        lines.append("### geometry_kind")
        lines.append("")
        _value_count_table(lines, sub[sub["section"] == "geometry_kind"])

        # station_class: aggregate key | count, then value | count
        sc = sub[sub["section"] == "station_class"]
        lines.append("### station_class")
        lines.append("")
        _key_count_table(lines, sc[sc["key"] == "n_distinct"])
        _value_count_table(lines, sc[sc["key"] != "n_distinct"])

        # extra_ids: key | count
        lines.append("### extra_ids")
        lines.append("")
        _key_count_table(lines, sub[sub["section"] == "extra_ids"])

        # country: aggregate key | count, then one distinct-values line
        country = sub[sub["section"] == "country"]
        lines.append("### country")
        lines.append("")
        agg = country[country["key"].isin(["non_empty", "n_distinct"])]
        _key_count_table(lines, agg)
        dv = country[country["key"] == "distinct_values"]
        if not dv.empty:
            row = dv.iloc[0]
            n = _md_cell(row["count"])
            vals = row["value"] if row["value"] else ""
            lines.append(f"Distinct values ({n}): {vals}")
            lines.append("")

        # missing: key | count
        lines.append("### missing")
        lines.append("")
        _key_count_table(lines, sub[sub["section"] == "missing"])

        # dropped_before_harmonisation: key | count, plus computed sentence
        dropped = sub[sub["section"] == "dropped_before_harmonisation"]
        lines.append("### dropped_before_harmonisation")
        lines.append("")
        _key_count_table(lines, dropped)
        sentence = _dropped_sentence(dropped)
        if sentence:
            lines.append(f"_{sentence}_")
            lines.append("")

    lines.append("## Notes")
    lines.append("")
    notes = _build_notes(base_prof, df)
    if notes:
        for note in notes:
            lines.append(f"- {note}")
    else:
        lines.append("- None.")
    lines.append("")

    return "\n".join(lines)


def main():
    df = pd.read_csv(INPUT_CSV, dtype=str, keep_default_na=False)

    base_prof = profile(df)
    sources = sorted(df["ri"].dropna().unique()) if not df.empty else []
    drop_prof = dropped_facts(sources, RAW_DIR, RAW_ACTRIS)
    prof = pd.concat([base_prof, drop_prof], ignore_index=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    prof.to_csv(OUT_CSV, index=False)
    OUT_MD.write_text(render_markdown(prof, df, base_prof), encoding="utf-8")

    for ri in sources:
        n_records = _get_count(base_prof, ri, "summary", "n_records")
        country_non_empty = _get_count(base_prof, ri, "country", "non_empty")
        elevation_missing = _get_count(base_prof, ri, "missing", "elevation_m")
        print(
            f"{ri}: n_records={n_records}, "
            f"country_non_empty={country_non_empty}, "
            f"elevation_m_missing={elevation_missing}"
        )


if __name__ == "__main__":
    main()