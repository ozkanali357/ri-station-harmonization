"""Tests for scripts/visualize_finland_layers.py."""

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "visualize_finland_layers.py"

spec = importlib.util.spec_from_file_location("visualize_finland_layers", MODULE_PATH)
vfl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vfl)


def make_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(cluster_id=2, ri_a="ACTRIS", record_id_a="A1", name_a="Alpha",
                 ri_b="ICOS", record_id_b="I1", name_b="Iso", match_type="same_station"),
            dict(cluster_id=2, ri_a="ICOS", record_id_a="I1", name_a="Iso",
                 ri_b="eLTER", record_id_b="E1", name_b="Elter One", match_type="same_site"),
            dict(cluster_id=2, ri_a="ACTRIS", record_id_a="A2", name_a="Beta",
                 ri_b="eLTER", record_id_b="E1", name_b="Elter One", match_type="different"),
            dict(cluster_id=3, ri_a="ICOS", record_id_a="I2", name_a="Iso Two",
                 ri_b="eLTER", record_id_b="E2", name_b="Elter Two", match_type="unclear"),
            dict(cluster_id=3, ri_a="ICOS", record_id_a="I2", name_a="Iso Two",
                 ri_b="eLTER", record_id_b="E2", name_b="Elter Two", match_type="same_site"),
        ]
    )


def test_node_count():
    nodes, _ = vfl.build_graph(make_df())
    assert len(nodes) == 6
    layers = sorted(n["layer"] for n in nodes)
    assert layers == ["ACTRIS", "ACTRIS", "DEIMS-SDR", "DEIMS-SDR", "ICOS", "ICOS"]


def test_edge_count_and_types():
    _, edges = vfl.build_graph(make_df())
    assert len(edges) == 5
    from collections import Counter
    c = Counter(e["match_type"] for e in edges)
    assert c["same_station"] == 1
    assert c["same_site"] == 2
    assert c["different"] == 1
    assert c["unclear"] == 1


def test_input_unchanged():
    df = make_df()
    before = df.copy()
    vfl.build_graph(df)
    pd.testing.assert_frame_equal(df, before)


def test_unknown_ri_raises():
    df = make_df()
    df.loc[0, "ri_a"] = "WEIRD"
    with pytest.raises(ValueError, match="Unexpected ri"):
        vfl.build_graph(df)


def test_unknown_match_type_raises():
    df = make_df()
    df.loc[0, "match_type"] = "maybe"
    with pytest.raises(ValueError, match="Unknown match_type"):
        vfl.build_graph(df)


def test_cluster_filter(tmp_path):
    df = make_df()
    in_csv = tmp_path / "in.csv"
    out_png = tmp_path / "out.png"
    df.to_csv(in_csv, index=False)
    vfl.main(["--input", str(in_csv), "--output", str(out_png), "--cluster", "3"])
    assert out_png.exists()


def test_cluster_filter_no_match(tmp_path):
    df = make_df()
    in_csv = tmp_path / "in.csv"
    out_png = tmp_path / "out.png"
    df.to_csv(in_csv, index=False)
    with pytest.raises(SystemExit):
        vfl.main(["--input", str(in_csv), "--output", str(out_png), "--cluster", "999"])


def test_hide_faint(tmp_path):
    df = make_df()
    in_csv = tmp_path / "in.csv"
    out_png = tmp_path / "out.png"
    df.to_csv(in_csv, index=False)
    vfl.main(["--input", str(in_csv), "--output", str(out_png), "--hide-faint"])
    assert out_png.exists()


def test_input_and_output_overrides(tmp_path):
    """Both --input and --output honoured; no defaults used."""
    df = make_df()
    in_csv = tmp_path / "in.csv"
    out_png = tmp_path / "out.png"
    df.to_csv(in_csv, index=False)
    vfl.main(["--input", str(in_csv), "--output", str(out_png)])
    assert out_png.exists()
