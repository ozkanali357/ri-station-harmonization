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


def _dropped_for_icos_elter(ri: str, raw_dir: Path):
    if _ri_sources is None:
        return None, f"not computed: adapter parsing not importable ({_RI_SOURCES_ERROR})"

    try:
        if ri == "ICOS":
            harmonised = _ri_sources.fetch_icos(raw_dir, offline=True)
            raw_count = _count_icos_raw(raw_dir)
        elif ri == "eLTER":
            harmonised = _ri_sources.fetch_deims(raw_dir, offline=True)
            raw_count = _count_deims_raw(raw_dir)
        else:
            return None, "not computed: no adapter for this source"

        dropped = raw_count - len(harmonised)
        return (
            dropped,
            f"computed via ri_harmonize.sources (raw {raw_count}, harmonised {len(harmonised)})",
        )
    except Exception as exc:
        return None, f"not computed: {exc}"


def dropped_facts(sources, raw_dir: Path, actris_path: Path) -> pd.DataFrame:
    rows = []
    for ri in sources:
        if ri == "ACTRIS":
            count, description = _compute_actris_dropped(actris_path)
        elif ri in ("ICOS", "eLTER"):
            count, description = _dropped_for_icos_elter(ri, raw_dir)
        else:
            count, description = None, "not computed: unknown source"
        _add(rows, ri, "dropped_before_harmonisation", "dropped", description, count)
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
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(prof: pd.DataFrame, df: pd.DataFrame, base_prof: pd.DataFrame) -> str:
    lines = ["# Source profile", ""]

    for ri in sorted(prof["ri"].unique()):
        lines.append(f"## {ri}")
        lines.append("")
        sub = prof[prof["ri"] == ri]

        for section in pd.unique(sub["section"]):
            lines.append(f"### {section}")
            lines.append("")
            lines.append("| key | value | count |")
            lines.append("| --- | --- | --- |")
            for _, row in sub[sub["section"] == section].iterrows():
                lines.append(
                    f"| {_md_cell(row['key'])} | {_md_cell(row['value'])} | "
                    f"{_md_cell(row['count'])} |"
                )
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