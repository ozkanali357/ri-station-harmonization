"""3-layer Finland station graph: ICOS, ACTRIS, DEIMS-SDR.

Reads outputs/finland_candidates_labelled.csv (read-only) and draws nodes =
records, edges = labelled pairs coloured by match_type. Plain matplotlib,
no networkx. Title states that the labels are proposed, not confirmed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "outputs" / "finland_candidates_labelled.csv"
OUT_PATH = ROOT / "outputs" / "finland_layers.png"

LAYER_ORDER = ["ICOS", "ACTRIS", "DEIMS-SDR"]
LAYER_FOR_RI = {"ICOS": "ICOS", "ACTRIS": "ACTRIS", "eLTER": "DEIMS-SDR"}
MATCH_TYPES = ["same_station", "same_site", "different", "unclear"]
MATCH_COLORS = {
    "same_station": "#1f77b4",
    "same_site": "#2ca02c",
    "different": "#d62728",
    "unclear": "#7f7f7f",
}
FAINT_TYPES = {"different", "unclear"}


def _shorten(s: str, n: int = 26) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def build_graph(df: pd.DataFrame):
    """Return (nodes, edges) without modifying df."""
    work = df.copy()

    unknown = set(work["match_type"].dropna().unique()) - set(MATCH_TYPES)
    if unknown:
        raise ValueError(f"Unknown match_type values: {sorted(unknown)}")

    records: dict[tuple[str, str], dict] = {}

    def _add(ri, record_id, name):
        layer = LAYER_FOR_RI.get(ri)
        if layer is None:
            raise ValueError(f"Unexpected ri value: {ri!r}")
        key = (layer, str(record_id))
        if key not in records:
            records[key] = {
                "layer": layer,
                "ri": ri,
                "record_id": str(record_id),
                "name": str(name) if pd.notna(name) else str(record_id),
            }

    for _, row in work.iterrows():
        _add(row["ri_a"], row["record_id_a"], row["name_a"])
        _add(row["ri_b"], row["record_id_b"], row["name_b"])

    nodes: list[dict] = []
    for layer_idx, layer in enumerate(LAYER_ORDER):
        layer_nodes = [r for r in records.values() if r["layer"] == layer]
        layer_nodes.sort(key=lambda r: (r["name"], r["record_id"]))
        n = len(layer_nodes)
        for i, r in enumerate(layer_nodes):
            x = 0.0 if n <= 1 else i / (n - 1)
            y = float(len(LAYER_ORDER) - 1 - layer_idx)
            nodes.append({**r, "x": x, "y": y})

    pos = {(n["layer"], n["record_id"]): (n["x"], n["y"]) for n in nodes}

    edges: list[dict] = []
    for _, row in work.iterrows():
        la = LAYER_FOR_RI[row["ri_a"]]
        lb = LAYER_FOR_RI[row["ri_b"]]
        ka = (la, str(row["record_id_a"]))
        kb = (lb, str(row["record_id_b"]))
        x0, y0 = pos[ka]
        x1, y1 = pos[kb]
        edges.append(
            {
                "src": ka,
                "dst": kb,
                "match_type": row["match_type"],
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            }
        )

    return nodes, edges


def draw(nodes, edges, out_path: Path, hide_faint: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(24, 10))

    for e in edges:
        mt = e["match_type"]
        if hide_faint and mt in FAINT_TYPES:
            continue
        faint = mt in FAINT_TYPES
        ax.plot(
            [e["x0"], e["x1"]],
            [e["y0"], e["y1"]],
            color=MATCH_COLORS[mt],
            alpha=0.25 if faint else 0.85,
            linewidth=0.8 if faint else 2.0,
            zorder=1 if faint else 2,
        )

    for layer_idx, layer in enumerate(LAYER_ORDER):
        y = float(len(LAYER_ORDER) - 1 - layer_idx)
        ax.axhline(y, color="#dddddd", linewidth=0.5, zorder=0)
        ax.annotate(
            layer,
            xy=(-0.03, y),
            ha="right",
            va="center",
            fontsize=11,
            fontweight="bold",
        )
        ln = [n for n in nodes if n["layer"] == layer]
        if ln:
            ax.scatter(
                [n["x"] for n in ln],
                [n["y"] for n in ln],
                s=220,
                c="#333333",
                zorder=3,
                edgecolors="white",
                linewidths=0.8,
            )

    for i, n in enumerate(nodes):
        if i % 2 == 0:
            xytext, va, rot = (0, -12), "top", 30
        else:
            xytext, va, rot = (0, 12), "bottom", 30
        ax.annotate(
            _shorten(n["name"], 22),
            xy=(n["x"], n["y"]),
            xytext=xytext,
            textcoords="offset points",
            ha="center",
            va=va,
            rotation=rot,
            rotation_mode="anchor",
            fontsize=5.8,
            color="#222222",
        )

    handles = []
    for mt in MATCH_TYPES:
        faint = mt in FAINT_TYPES
        handles.append(
            Line2D(
                [0],
                [0],
                color=MATCH_COLORS[mt],
                lw=0.8 if faint else 2.0,
                alpha=0.25 if faint else 0.85,
                label=mt,
            )
        )
    ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9, title="match_type")

    ax.set_xlim(-0.10, 1.05)
    ax.set_ylim(-0.8, len(LAYER_ORDER) - 0.2)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Finland station cross-RI graph \u2014 proposed labels, not confirmed", fontsize=12)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="3-layer Finland station graph.")
    parser.add_argument("--input", type=Path, default=CSV_PATH)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    parser.add_argument("--cluster", type=int, default=None)
    parser.add_argument("--hide-faint", action="store_true", dest="hide_faint")
    args = parser.parse_args(argv)

    df = pd.read_csv(args.input)
    if args.cluster is not None:
        df = df[df["cluster_id"] == args.cluster]
        if df.empty:
            raise SystemExit(f"No rows with cluster_id = {args.cluster}")

    nodes, edges = build_graph(df)

    print(f"Nodes: {len(nodes)}")
    for layer in LAYER_ORDER:
        cnt = sum(1 for n in nodes if n["layer"] == layer)
        print(f"  {layer}: {cnt}")
    print(f"Edges: {len(edges)}")
    c = Counter(e["match_type"] for e in edges)
    for mt in MATCH_TYPES:
        print(f"  {mt}: {c.get(mt, 0)}")

    draw(nodes, edges, args.output, hide_faint=args.hide_faint)
    print(f"Saved visual to {args.output}")


if __name__ == "__main__":
    main()
