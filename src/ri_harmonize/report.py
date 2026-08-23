"""Figures and the written summary."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .geo import LAEA_EUROPE, to_geodataframe  # noqa: E402

RI_COLOURS = {"ICOS": "#1f3864", "eLTER": "#2e7d32", "ACTRIS": "#b8541a"}


def plot_stations(df: pd.DataFrame, labels, out_path: Path) -> None:
    """Two panels: who is where, and which records got grouped together."""
    gdf = to_geodataframe(df).to_crs(LAEA_EUROPE)
    gdf["cluster"] = labels

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2))

    for ri, sub in gdf.groupby("ri"):
        axes[0].scatter(sub.geometry.x, sub.geometry.y, s=7, alpha=0.65,
                        c=RI_COLOURS.get(ri, "#666666"), label=f"{ri} (n={len(sub)})")
    axes[0].set_title("Stations and sites by research infrastructure")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")

    noise = gdf[gdf.cluster < 0]
    grouped = gdf[gdf.cluster >= 0]
    axes[1].scatter(noise.geometry.x, noise.geometry.y, s=5, c="#cccccc", label=f"unclustered (n={len(noise)})")
    if not grouped.empty:
        rng = np.random.default_rng(0)
        palette = rng.random((int(grouped.cluster.max()) + 1, 3)) * 0.75
        axes[1].scatter(grouped.geometry.x, grouped.geometry.y, s=18,
                        c=palette[grouped.cluster.to_numpy()], label=f"clustered (n={len(grouped)})")
    axes[1].set_title("DBSCAN groups (haversine metric)")
    axes[1].legend(frameon=False, fontsize=8, loc="upper left")

    for ax in axes:
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_xlabel("EPSG:3035 (ETRS89 / LAEA Europe)", fontsize=8)
        for spine in ax.spines.values():
            spine.set_color("#bbbbbb")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_eps_sweep(sweep: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(sweep.eps_km, sweep.n_cross_ri_pairs, marker="o", color="#1f3864",
            label="candidate cross-RI pairs")
    ax.plot(sweep.eps_km, sweep.n_same_ri_overmerged, marker="s", color="#b8541a",
            label="clusters merging >1 station of the same RI")
    ax.set_xlabel("DBSCAN eps (km)")
    ax.set_ylabel("count")
    ax.set_title("Choosing eps: candidates gained against over-merging")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def write_summary(path: Path, stations, sweep, candidates, buffer_pairs, scores, params) -> None:
    counts = stations.ri.value_counts().to_dict()
    lines = [
        "# Run summary",
        "",
        f"Generated from cached RI responses in `data/raw/`. Parameters: {params}.",
        "",
        "## Records loaded",
        "",
        "| Infrastructure | Records with usable coordinates |",
        "| --- | --- |",
    ]
    lines += [f"| {ri} | {n} |" for ri, n in sorted(counts.items())]
    lines += [
        f"| **total** | **{len(stations)}** |",
        "",
        "## Choice of eps",
        "",
        sweep.to_markdown(index=False),
        "",
        f"Selected eps = {params.get('eps_km')} km, min_samples = {params.get('min_samples')}.",
        "",
        "## Candidate cross-RI pairs",
        "",
        f"- DBSCAN (haversine): **{len(candidates)}** pairs",
        f"- Buffer intersection in EPSG:3035 at {params.get('buffer_km')} km: **{len(buffer_pairs)}** pairs",
        "",
        "## Scored against the hand-checked ground truth",
        "",
    ]
    lines += [f"- `{k}`: {v}" for k, v in scores.items()]
    lines += ["", "## Nearest ten candidates", ""]
    if candidates.empty:
        lines.append("_none_")
    else:
        cols = ["ri_a", "id_a", "name_a", "ri_b", "id_b", "name_b", "distance_km", "name_similarity"]
        lines.append(candidates[cols].head(10).to_markdown(index=False))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
