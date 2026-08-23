"""Scoring automated candidate pairs against a hand-checked ground truth.

The ground truth is the point of the exercise.  Without it a clustering result
is a picture; with it, it is a measurement.  ``data/ground_truth/manual_pairs.csv``
is filled in by hand, one row per candidate that a human actually looked at, and
nothing in this module ever writes to it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

GROUND_TRUTH_COLUMNS = ["ri_a", "id_a", "ri_b", "id_b", "same_place", "checked_by", "evidence"]


def _key(frame: pd.DataFrame) -> pd.Series:
    a = frame.ri_a.astype(str) + "|" + frame.id_a.astype(str)
    b = frame.ri_b.astype(str) + "|" + frame.id_b.astype(str)
    lo = a.where(a <= b, b)
    hi = b.where(a <= b, a)
    return lo + "::" + hi


def load_ground_truth(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=GROUND_TRUTH_COLUMNS)
    gt = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in ("ri_a", "id_a", "ri_b", "id_b", "same_place") if c not in gt.columns]
    if missing:
        raise ValueError(f"ground truth file is missing columns: {missing}")
    gt["same_place"] = gt.same_place.str.strip().str.lower()
    gt = gt[gt.same_place.isin({"yes", "no"})]
    return gt


def score(candidates: pd.DataFrame, ground_truth: pd.DataFrame) -> dict:
    """Precision / recall / F1 of candidate pairs, evaluated only on rows a
    human has adjudicated.

    Candidates outside the reviewed set are counted separately as
    ``unadjudicated`` instead of being silently assumed wrong - assuming would
    inflate or deflate precision depending on which way you guess.
    """
    if ground_truth.empty:
        return {
            "reviewed_pairs": 0,
            "note": "no adjudicated pairs yet - fill data/ground_truth/manual_pairs.csv",
        }

    gt = ground_truth.copy()
    gt["key"] = _key(gt)
    truth = dict(zip(gt.key, gt.same_place == "yes"))

    cand = candidates.copy()
    cand["key"] = _key(cand) if not cand.empty else pd.Series(dtype=str)
    predicted = set(cand.key) if not cand.empty else set()

    tp = sum(1 for k, is_same in truth.items() if is_same and k in predicted)
    fp = sum(1 for k, is_same in truth.items() if not is_same and k in predicted)
    fn = sum(1 for k, is_same in truth.items() if is_same and k not in predicted)
    tn = sum(1 for k, is_same in truth.items() if not is_same and k not in predicted)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "reviewed_pairs": len(truth),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "unadjudicated_candidates": int(len(predicted - set(truth))),
    }


def make_review_sheet(candidates: pd.DataFrame, ground_truth: pd.DataFrame, limit: int = 60) -> pd.DataFrame:
    """Candidates a human has not yet ruled on, nearest first.

    This is the worklist for Method 1: it does not decide anything, it just puts
    the cheapest decisions in front of the reviewer first.
    """
    if candidates.empty:
        return pd.DataFrame(columns=GROUND_TRUTH_COLUMNS + ["distance_km", "name_similarity"])
    cand = candidates.copy()
    cand["key"] = _key(cand)
    if not ground_truth.empty:
        gt = ground_truth.copy()
        gt["key"] = _key(gt)
        cand = cand[~cand.key.isin(set(gt.key))]
    cand = cand.drop_duplicates("key").head(limit)
    sheet = cand[["ri_a", "id_a", "name_a", "ri_b", "id_b", "name_b", "distance_km", "name_similarity", "uri_a", "uri_b"]].copy()
    sheet.insert(6, "same_place", "")      # <- reviewer writes yes / no
    sheet["checked_by"] = ""
    sheet["evidence"] = ""
    return sheet.reset_index(drop=True)
