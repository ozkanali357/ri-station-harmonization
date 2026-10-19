"""Command line entry point.

    python -m ri_harmonize.cli run                 # fetch (once), cluster, score, report
    python -m ri_harmonize.cli run --offline       # re-run from cached responses only
    python -m ri_harmonize.cli review              # write the next batch to adjudicate by hand
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import cluster as cl
from . import evaluate as ev
from . import actris, deims_detail, geo, report, sources

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
GROUND_TRUTH = ROOT / "data" / "ground_truth" / "manual_pairs.csv"
OUT = ROOT / "outputs"

DEFAULT_EPS_GRID = [0.5, 1, 2, 3, 5, 7.5, 10, 15, 20, 30]


def load_stations(offline: bool, deims_detail_finland: bool = False) -> pd.DataFrame:
    """Harmonised station table; with ``deims_detail_finland`` the scope-check summary is in ``.attrs``.

    The detail enrichment is opt-in: without it the table and the interim file are
    exactly what earlier runs produced.
    """
    deims = sources.fetch_deims(RAW, offline=offline)
    frames = [sources.fetch_icos(RAW, offline=offline), deims, actris.fetch_actris(RAW, offline=offline)]
    stations = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    name = "stations_harmonised.csv"
    if deims_detail_finland:
        details = deims_detail.fetch_details(RAW, deims_detail.finnish_site_ids(deims), offline=offline)
        stations, scope_check = deims_detail.enrich_stations(stations, details)
        stations.attrs["deims_detail_finland"] = scope_check
        name = "stations_harmonised_deims_detail_finland.csv"
    INTERIM.mkdir(parents=True, exist_ok=True)
    stations.to_csv(INTERIM / name, index=False)
    return stations


def cmd_run(args) -> None:
    stations = load_stations(args.offline, args.deims_detail_finland)
    scope_check = stations.attrs.get("deims_detail_finland")
    out = Path(args.out_dir) if args.out_dir else OUT
    logging.info("%d records with usable coordinates: %s",
                 len(stations), stations.ri.value_counts().to_dict())

    sweep = cl.sweep_eps(stations, DEFAULT_EPS_GRID, min_samples=args.min_samples)
    labels = cl.dbscan_labels(stations, eps_km=args.eps_km, min_samples=args.min_samples)
    candidates = cl.cross_ri_pairs(stations, labels, "dbscan")

    k = max(2, len(stations) // max(args.kmeans_divisor, 1))
    km_labels = cl.kmeans_labels(stations, k=k)
    km_candidates = cl.cross_ri_pairs(stations, km_labels, "kmeans")

    buffer_pairs = geo.buffer_overlap_pairs(stations, radius_km=args.buffer_km)

    polygon_pairs = geo.buffer_overlap_pairs_polygon(stations, radius_km=args.buffer_km) if args.deims_detail_finland else None

    ground_truth = ev.load_ground_truth(GROUND_TRUTH)
    scores = {
        "dbscan": ev.score(candidates, ground_truth),
        "kmeans_baseline": ev.score(km_candidates, ground_truth),
        "buffer_intersection": ev.score(buffer_pairs, ground_truth),
    }
    if polygon_pairs is not None:
        scores["buffer_polygon_intersection"] = ev.score(polygon_pairs, ground_truth)
    flat = {f"{m}.{k2}": v for m, d in scores.items() for k2, v in d.items()}

    out.mkdir(parents=True, exist_ok=True)
    sweep.to_csv(out / "eps_sweep.csv", index=False)
    candidates.to_csv(out / "candidate_pairs_dbscan.csv", index=False)
    km_candidates.to_csv(out / "candidate_pairs_kmeans.csv", index=False)
    buffer_pairs.to_csv(out / "candidate_pairs_buffer.csv", index=False)
    if polygon_pairs is not None:
        polygon_pairs.to_csv(out / "candidate_pairs_buffer_polygon.csv", index=False)

    report.plot_stations(stations, labels, out / "stations_map.png")
    report.plot_eps_sweep(sweep, out / "eps_sweep.png")
    geo.write_spatial_outputs(stations, labels, out)
    report.write_summary(
        out / "summary.md", stations, sweep, candidates, km_candidates, buffer_pairs, flat,
        {"eps_km": args.eps_km, "min_samples": args.min_samples,
         "buffer_km": args.buffer_km, "kmeans_k": k},
        polygon_pairs=polygon_pairs, scope_check=scope_check,
    )
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip()
    raw_manifest = json.loads((RAW / "manifest.json").read_text()) if (RAW / "manifest.json").exists() else {}
    (out / "run_manifest.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_revision": revision, "parameters": {"eps_km": args.eps_km, "min_samples": args.min_samples, "buffer_km": args.buffer_km, "kmeans_k": k},
        "station_validation": sources.validate_stations(stations), "source_cache_manifest": raw_manifest,
        **({"deims_detail_finland": scope_check, "buffer_polygon_pairs": len(polygon_pairs)} if polygon_pairs is not None else {}),
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(candidates)} DBSCAN candidate pairs "
          f"({len(km_candidates)} k-means, {len(buffer_pairs)} buffer"
          + (f", {len(polygon_pairs)} polygon buffer" if polygon_pairs is not None else "") + f") to {out}/")
    print(f"Read {out / 'summary.md'} next.")


def cmd_review(args) -> None:
    stations = load_stations(offline=True)
    labels = cl.dbscan_labels(stations, eps_km=args.eps_km, min_samples=args.min_samples)
    candidates = cl.cross_ri_pairs(stations, labels, "dbscan")
    k = max(2, len(stations) // 3)
    km_candidates = cl.cross_ri_pairs(stations, cl.kmeans_labels(stations, k=k), "kmeans")
    buffer_candidates = geo.buffer_overlap_pairs(stations, radius_km=args.eps_km)
    candidates = pd.concat([candidates, km_candidates, buffer_candidates], ignore_index=True).drop_duplicates(
        ["ri_a", "record_id_a", "ri_b", "record_id_b"]
    )
    sheet = ev.make_review_sheet(candidates, ev.load_ground_truth(GROUND_TRUTH), limit=args.limit)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "review_sheet.csv"
    sheet.to_csv(path, index=False)
    html_sheet = sheet.copy()
    for column, label in (("uri_a", "Open ICOS/eLTER record A"), ("uri_b", "Open ICOS/eLTER record B")):
        html_sheet[column] = html_sheet[column].map(
            lambda url: f'<a href="{html.escape(str(url), quote=True)}" target="_blank" rel="noopener">{label}</a>'
        )
    html_path = OUT / "review_sheet.html"
    html_path.write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>Station review sheet</title>"
        "<style>body{font-family:system-ui;margin:2rem}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #ddd;padding:.45rem;vertical-align:top}th{position:sticky;top:0;background:#f4f4f4}a{color:#0645ad}</style>"
        "<h1>Station review sheet</h1><p>Use this page to open records. Enter decisions and evidence in the CSV, then copy only the ground-truth columns into manual_pairs.csv.</p>"
        + html_sheet.to_html(index=False, escape=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(sheet)} unadjudicated pairs to {path}")
    print(f"Open {html_path} in a browser for reliable clickable record links.")
    print("Fill in the same_place column (yes/no), then append the rows to")
    print(f"{GROUND_TRUTH} and re-run `python -m ri_harmonize.cli run --offline`.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ri_harmonize", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--eps-km", type=float, default=5.0, dest="eps_km")
        p.add_argument("--min-samples", type=int, default=2, dest="min_samples")

    run = sub.add_parser("run", help="full pipeline")
    common(run)
    run.add_argument("--buffer-km", type=float, default=5.0, dest="buffer_km")
    run.add_argument("--kmeans-divisor", type=int, default=3, dest="kmeans_divisor",
                     help="k = n_stations // divisor for the k-means baseline")
    run.add_argument("--offline", action="store_true", help="use cached responses only")
    run.add_argument("--deims-detail-finland", action="store_true", dest="deims_detail_finland",
                     help="fetch DEIMS detail records for the Finnish eLTER sites (title ends ' - Finland'), "
                          "use their boundary polygons, and write candidate_pairs_buffer_polygon.csv")
    run.add_argument("--out-dir", default=None, dest="out_dir",
                     help="write run outputs here instead of outputs/ (use this for any non-default run)")
    run.set_defaults(func=cmd_run)

    review = sub.add_parser("review", help="write the next batch of pairs to check by hand")
    common(review)
    review.add_argument("--limit", type=int, default=60)
    review.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
