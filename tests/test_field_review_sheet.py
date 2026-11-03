"""Review sheet for top-ranked field-name pairs: selection, blinding and reproducibility, offline."""

import pandas as pd

from scripts import make_field_review_sheet as sheet_mod

FLAG = "FLAGGED: No published API definition found"


def tiny_inputs(n_deims=6, n_icos=5):
    rows = []
    for i in range(n_deims):
        for j in range(n_icos):
            rows.append(("DEIMS", f"d{i}", "ICOS", f"i{j}", 0.0, round(0.9 - 0.01 * (i * n_icos + j), 4), 0.0, 0.5))
    table = pd.DataFrame(rows, columns=["ri_a", "field_a", "ri_b", "field_b", "tfidf_name_sim", "minilm_name_sim",
                                        "tfidf_text_sim", "minilm_text_sim"])
    fields = pd.DataFrame([("ICOS", f"i{j}", "Some published comment" if j == 0 else FLAG) for j in range(n_icos)],
                          columns=["ri", "field", "definition"])
    return table, fields


def test_selection_is_top_ten_plus_ten_random_from_the_rest():
    table, fields = tiny_inputs()
    sheet, key = sheet_mod.build(table, fields)
    assert len(sheet) == 20 and sheet["pair_id"].is_unique
    assert key["selection"].value_counts().to_dict() == {"top10": 10, "random": 10}
    assert sorted(key.loc[key["selection"] == "top10", "rank_minilm_name_sim"]) == list(range(1, 11))
    assert (key.loc[key["selection"] == "random", "rank_minilm_name_sim"] > 10).all()


def test_sheet_has_no_scores_and_no_rank_and_leaves_review_columns_empty():
    table, fields = tiny_inputs()
    sheet, key = sheet_mod.build(table, fields)
    assert list(sheet.columns) == sheet_mod.SHEET_COLUMNS
    assert not any("sim" in c or "rank" in c or "selection" in c for c in sheet.columns)
    assert (sheet["reviewer_label"] == "").all() and (sheet["evidence_note"] == "").all()
    assert set(key["pair_id"]) == set(sheet["pair_id"])


def test_pair_ids_do_not_encode_the_rank_and_the_order_is_shuffled():
    table, fields = tiny_inputs()
    _, key = sheet_mod.build(table, fields)
    assert list(key["pair_id"]) == [f"R{i:02d}" for i in range(1, 21)]
    assert list(key["rank_minilm_name_sim"]) != sorted(key["rank_minilm_name_sim"])


def test_definition_is_the_published_comment_or_the_word_flagged():
    table, fields = tiny_inputs()
    sheet, _ = sheet_mod.build(table, fields)
    for row in sheet.itertuples():
        assert row.icos_definition == ("Some published comment" if row.icos_field == "i0" else "FLAGGED")


def test_same_seed_same_sheet_different_seed_different_sample():
    table, fields = tiny_inputs()
    first, _ = sheet_mod.build(table, fields, seed=7)
    again, _ = sheet_mod.build(table, fields, seed=7)
    other, _ = sheet_mod.build(table, fields, seed=8)
    pd.testing.assert_frame_equal(first, again)
    assert not first.equals(other)


def test_committed_sheet_and_key_are_what_the_script_produces_from_the_committed_table():
    table = pd.read_csv(sheet_mod.TABLE)
    fields = pd.read_csv(sheet_mod.FIELDS)
    sheet, key = sheet_mod.build(table, fields)
    committed_sheet = pd.read_csv(sheet_mod.SHEET, keep_default_na=False)
    committed_key = pd.read_csv(sheet_mod.KEY)
    pd.testing.assert_frame_equal(sheet, committed_sheet)
    pd.testing.assert_frame_equal(key.reset_index(drop=True), committed_key)
    assert list(committed_sheet.columns) == sheet_mod.SHEET_COLUMNS
    assert "contact" not in " ".join(committed_sheet["deims_field"].str.lower())
