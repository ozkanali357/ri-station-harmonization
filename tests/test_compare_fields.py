"""Field-name similarity tables: structure, separation of pairs and pinning, all offline.

The MiniLM model is replaced by a tiny character-trigram hashing embedder that stands in for
``SentenceTransformer.encode`` so the tests need neither the network nor the model weights. These
tests check table structure and rules; they say nothing about MiniLM scores.
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import compare_fields as cf
from scripts import consolidate_dataset as cd

ROOT = Path(__file__).resolve().parents[1]
FLAG = cd.FLAG_TEXT


def trigram_embedder(texts):
    out = np.zeros((len(texts), 64))
    for i, text in enumerate(texts):
        t = f"  {text.lower()}  "
        for k in range(len(t) - 2):
            out[i, sum(ord(c) * (31 ** n) for n, c in enumerate(t[k:k + 3])) % 64] += 1
    return out


FIELDS = pd.DataFrame([
    ("DEIMS", "geographic.coordinates", FLAG),
    ("DEIMS", "title", FLAG),
    ("DEIMS", "contact.siteManager[0].name", FLAG),
    ("ICOS", "hasLatitude", "Decimal degrees in WGS84/GRS80"),
    ("ICOS", "hasName", FLAG),
    ("ACTRIS", "name", FLAG),
    ("ACTRIS", "location.coordinates", FLAG),
], columns=["ri", "field", "definition"])


def test_prepare_fields_drops_contact_and_builds_text():
    prepared = cf.prepare_fields(FIELDS)
    assert not prepared["field"].str.startswith("contact.").any()
    lat = prepared[prepared["field"] == "hasLatitude"].iloc[0]
    assert lat["definition_used"] and lat["text"] == "hasLatitude. Decimal degrees in WGS84/GRS80"
    assert lat["name_text"] == "hasLatitude"
    title = prepared[prepared["field"] == "title"].iloc[0]
    assert not title["definition_used"] and title["text"] == "title"


def test_rank_pair_keeps_the_two_infrastructures_apart_and_sorted():
    prepared = cf.prepare_fields(FIELDS)
    ranked = cf.rank_pair(prepared, "DEIMS", "ICOS", trigram_embedder)
    assert list(ranked.columns) == cf.OUTPUT_COLUMNS
    assert set(ranked["ri_a"]) == {"DEIMS"} and set(ranked["ri_b"]) == {"ICOS"}
    assert len(ranked) == 2 * 2  # contact field excluded: 2 DEIMS x 2 ICOS
    assert ranked["minilm_name_sim"].is_monotonic_decreasing
    used = ranked.set_index(["field_a", "field_b"])
    assert used.loc[("title", "hasLatitude"), "definition_used_b"]
    assert not used.loc[("title", "hasLatitude"), "definition_used_a"]


def test_name_scores_ignore_definitions_text_scores_use_them():
    prepared = cf.prepare_fields(FIELDS)
    ranked = cf.rank_pair(prepared, "DEIMS", "ICOS", trigram_embedder).set_index(["field_a", "field_b"])
    with_definition = ranked.loc[("title", "hasLatitude")]
    without = ranked.loc[("title", "hasName")]
    assert without["minilm_name_sim"] == without["minilm_text_sim"]
    assert without["tfidf_name_sim"] == without["tfidf_text_sim"]
    assert with_definition["minilm_name_sim"] != with_definition["minilm_text_sim"]


def test_one_file_per_pair_and_deims_icos_comes_first():
    assert cf.PAIR_ORDER[0] == ("DEIMS", "ICOS")
    names = [cf.pair_file(a, b, Path("x")).name for a, b in cf.PAIR_ORDER]
    assert names == ["field_similarity_deims_icos.csv", "field_similarity_deims_actris.csv",
                     "field_similarity_icos_actris.csv"]
    assert cf.SCORE_LABEL == "similarity of field names"


def test_version_drift_reports_only_differences():
    pinned = {"torch": "1.0", "numpy": "2.0"}
    assert cf.version_drift(pinned, {"torch": "1.0", "numpy": "2.0"}) == {}
    assert cf.version_drift(pinned, {"torch": "1.1", "numpy": None}) == {
        "torch": {"pinned": "1.0", "installed": "1.1"}, "numpy": {"pinned": "2.0", "installed": None}}


def test_pin_file_names_the_model_and_a_seed_and_is_not_filled_with_guesses():
    pin = cf.load_pin()
    assert pin["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert isinstance(pin["seed"], int)
    # either still unpinned, or pinned with a full 40-hex commit hash and library versions
    if pin["revision"] is not None:
        assert re.fullmatch(r"[0-9a-f]{40}", pin["revision"])
        assert pin["libraries"].get("sentence-transformers")


def test_main_refuses_to_run_without_a_revision(monkeypatch, capsys):
    monkeypatch.setattr(cf, "load_pin", lambda: {"model": "m", "revision": None, "seed": 1, "libraries": {}})
    assert cf.main([]) == 2
    assert "--write-pin" in capsys.readouterr().err


def test_consolidate_overlays_published_definitions_and_drops_contact():
    fields = FIELDS[["ri", "field"]]
    defs = pd.DataFrame(columns=["ri", "field", "definition"])
    icos = pd.DataFrame({"ri": ["ICOS", "ICOS"], "field": ["hasLatitude", "hasName"],
                         "definition": ["Decimal degrees in WGS84/GRS80", ""]})
    out = cd.consolidate(fields, defs, icos).set_index(["ri", "field"])
    assert out.loc[("ICOS", "hasLatitude"), "flagged"] == "no"
    assert out.loc[("ICOS", "hasName"), "definition"] == FLAG
    assert out.loc[("DEIMS", "title"), "flagged"] == "yes"
    assert ("DEIMS", "contact.siteManager[0].name") not in out.index


def test_committed_field_outputs_contain_no_email_address():
    email = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]+")
    files = [p for pattern in ("final_field_comparison.csv", "icos_field_definitions*", "field_similarity_*",
                               "field_definitions_raw/*")
             for p in (ROOT / "outputs").glob(pattern)]
    assert files
    for path in files:
        assert not email.search(path.read_text(encoding="utf-8")), path
    assert not any(line.startswith("DEIMS,contact.") for line in
                   (ROOT / "outputs" / "final_field_comparison.csv").read_text(encoding="utf-8").splitlines())
