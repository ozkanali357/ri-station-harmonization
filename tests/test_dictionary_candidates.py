"""Offline tests for ``scripts/dictionary_candidates.py`` with a fake embedder and tiny tables."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from scripts import dictionary_candidates as dc

EMB = {  # hand-made 2-d vectors: "temperature" words point one way, "wind" words the other
    "air temperature": [1.0, 0.0], "soil temperature": [0.9, 0.1], "temperature": [0.95, 0.05],
    "wind speed": [0.0, 1.0], "wind": [0.05, 0.95], "air velocity magnitude": [0.1, 0.9],
    "soil water content": [0.5, 0.5], "unrelated list item": [-1.0, -1.0], "Temperature of air": [0.99, 0.01],
}


def embed(texts):
    return np.array([EMB[t] for t in texts], dtype=float)


def _terms():
    cols = ["ri", "term_label", "term_uri", "definition", "scope_candidate", "scope_rule", "n_finnish_records"]
    rows = [
        ("ICOS", "wind speed", "http://icos/WS", "Mean wind speed.", "meteorology", "wind", "5"),
        ("ICOS", "wind speed", "http://icos/WS_F", "", "meteorology", "wind", "3"),
        ("ACTRIS", "air temperature", "", "", "meteorology", "air temperature", "4"),
        ("eLTER", "soil temperature", "http://vocabs.lter-europe.net/EnvThes/10", "", "soil", "soil", "2"),
        ("eLTER", "soil water content", "http://vocabs.lter-europe.net/EnvThes/11", "", "soil", "soil", "2"),
        ("eLTER", "not in scope", "http://vocabs.lter-europe.net/EnvThes/12", "", "", "", "1"),
    ]
    return pd.DataFrame(rows, columns=cols)


def _concepts():
    cols = ["vocabulary", "concept_uri", "pref_label", "alt_labels", "definition", "deprecated", "replaced_by",
            "vocabulary_version", "vocabulary_licence"]
    e, a = "http://vocabs.lter-europe.net/EnvThes/", "https://vocabulary.actris.nilu.no/actris_vocab/"
    rows = [
        ("EnvThes", e + "1", "temperature", "", "[GEMET] restricted-for-now text", False, "", "5.0.16", "by"),
        ("EnvThes", e + "10", "soil temperature", "", "own concept of the DEIMS term", False, "", "5.0.16", "by"),
        ("EnvThes", e + "2", "wind", "", "restricted", False, "", "5.0.16", "by"),
        ("EnvThes", e + "3", "air temperature", "", "deprecated twin", True, "", "5.0.16", "by"),
        ("so", "http://so/1", "unrelated list item", "", "", False, "", "1.1.5", "by"),
        ("actris_vocab", a + "airtemperature", "air temperature", "Temperature of air", "CC0 definition", False, "", "1.2.2", "cc0"),
        ("actris_vocab", a + "windspeed", "wind speed", "", "CC0 wind", False, "", "1.2.2", "cc0"),
        ("actris_vocab", a + "mag", "air velocity magnitude", "", "CC0 magnitude", False, "", "1.2.2", "cc0"),
    ]
    return pd.DataFrame(rows, columns=cols)


def test_source_terms_group_labels_and_keep_only_flagged_domains():
    s = dc.source_terms(_terms()).set_index(["source_ri", "source_label"])
    assert len(s) == 4                                     # "not in scope" dropped
    ws = s.loc[("ICOS", "wind speed")]
    assert ws["n_source_uris"] == 2 and ws["source_term_uris"] == "http://icos/WS | http://icos/WS_F"
    assert ws["source_definition_icos"] == "Mean wind speed."
    assert s.loc[("eLTER", "soil temperature"), "source_definition_icos"] == ""


def test_candidates_rank_by_similarity_exclude_own_vocabulary_deprecated_and_own_uri():
    committed, local, counts = dc.generate(_terms(), _concepts(), embed, top_k=2)
    air = committed[committed["source_label"] == "air temperature"]
    assert set(air["target_vocabulary"]) <= {"EnvThes", "so"}          # ACTRIS term: never its own vocabulary
    assert "http://vocabs.lter-europe.net/EnvThes/3" not in set(committed["target_concept_uri"])   # deprecated
    soil = committed[committed["source_label"] == "soil temperature"]
    assert "http://vocabs.lter-europe.net/EnvThes/10" not in set(soil["target_concept_uri"])      # own URI
    assert "EnvThes" not in set(soil["target_vocabulary"])             # DEIMS term: never EnvThes
    ws = committed[(committed["source_ri"] == "ICOS")].sort_values("rank_for_term")
    assert ws.iloc[0]["target_pref_label"] == "wind speed" and ws.iloc[0]["minilm_label_sim"] == 1.0
    assert bool(ws.iloc[0]["label_equal"]) is True and ws.iloc[0]["rank_for_term"] == 1
    assert counts["candidates"] == len(committed) == 8 and counts["rounds_over_cap"] == {}


def test_altlabel_can_give_the_score_and_is_reported():
    committed, _, _ = dc.generate(_terms(), _concepts(), embed, top_k=5)
    row = committed[(committed["source_label"] == "soil temperature") & (committed["target_pref_label"] == "air temperature")
                    & (committed["target_vocabulary"] == "actris_vocab")]
    assert len(row) == 1 and row.iloc[0]["matched_label"] == "Temperature of air"   # altLabel scored higher
    assert row.iloc[0]["target_alt_labels"] == "Temperature of air" and bool(row.iloc[0]["label_equal"]) is False


def test_human_columns_are_blank_and_restricted_definitions_stay_in_the_local_table():
    committed, local, _ = dc.generate(_terms(), _concepts(), embed, top_k=3)
    for col in dc.HUMAN_COLUMNS:
        assert (committed[col] == "").all(), col
    assert list(committed.columns) == dc.CANDIDATE_COLUMNS
    shown = committed[committed["target_definition"] != ""]
    assert set(shown["target_vocabulary"]) == {"actris_vocab"} and set(shown["target_licence"]) == {"cc0"}
    assert not committed["target_definition"].str.contains("restricted|GEMET").any()
    assert "source_definition_icos" not in committed.columns
    assert local["target_definition_local"].str.contains("restricted").any()
    assert local["source_definition_icos"].str.contains("Mean wind speed").any()


def test_rounds_follow_source_ri_and_domain_and_ids_are_stable():
    committed, _, counts = dc.generate(_terms(), _concepts(), embed, top_k=2)
    rounds = committed.drop_duplicates("source_label").set_index("source_label")["labelling_round"].to_dict()
    assert rounds == {"air temperature": "R1", "wind speed": "R1", "soil temperature": "R3", "soil water content": "R3"}
    again, _, _ = dc.generate(_terms(), _concepts(), embed, top_k=2)
    assert list(committed["candidate_id"]) == list(again["candidate_id"]) and committed["candidate_id"].is_unique
    assert counts["target_deprecated_excluded"]["EnvThes"] == 1


def _labelled(**changes):
    row = {"candidate_id": "C0001", "source_ri": "ICOS", "source_label": "wind speed", "rank_for_term": "1",
           "skos_relation": "closeMatch", "broader_side": "", "evidence_basis": "label_fallback",
           "evidence_text": "labels agree; URI is recorded, not the evidence", "checked_by": "AOO", "checked_at": "2026-11-04"}
    row.update(changes)
    return pd.DataFrame([row])


def test_check_accepts_a_complete_row_and_counts_descriptively():
    problems, counts = dc.check_labelled(_labelled())
    assert problems == [] and counts["by_relation"] == {"closeMatch": 1} and "not ground truth" in counts["note"]


@pytest.mark.parametrize("changes, fragment", [
    ({"skos_relation": "sameAs"}, "not one of"),
    ({"skos_relation": "broadMatch"}, "needs broader_side"),
    ({"skos_relation": "closeMatch", "broader_side": "source"}, "broader_side is set"),
    ({"checked_by": ""}, "checked_by and checked_at"),
    ({"evidence_text": ""}, "evidence_text is required"),
    ({"evidence_basis": "gut feeling"}, "evidence_basis"),
])
def test_check_reports_incomplete_or_inconsistent_labels(changes, fragment):
    problems, _ = dc.check_labelled(_labelled(**changes))
    assert any(fragment in p for p in problems), problems


def test_a_broad_match_with_a_named_side_is_accepted():
    problems, _ = dc.check_labelled(_labelled(skos_relation="broadMatch", broader_side="target"))
    assert problems == []


def test_debug_embedder_cannot_write_into_outputs(capsys):
    assert dc.main(["--debug-embedder"]) == 2
    assert "must not go to outputs" in capsys.readouterr().err

def test_no_elter_in_candidates_source_ri(tmp_path):
    # after running generate(), assert 'eLTER' not in df['source_ri'].unique()
    df = pd.read_csv("outputs/dictionary_candidates_finland.csv")
    assert 'eLTER' not in set(df['source_ri'])
    assert 'DEIMS' in set(df['source_ri'])

def test_no_elter_in_reference_ri(tmp_path):
    ref = pd.read_csv("outputs/dictionary_reference_finland.csv")
    assert 'eLTER' not in set(ref['ri'])