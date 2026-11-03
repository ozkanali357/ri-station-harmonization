"""Pin and weight-verification behaviour of scripts/compare_fields.py, offline.

No network and no Hugging Face: snapshots are small temporary folders, the model is a stand-in class,
and ``resolve_revision_and_weights`` is replaced. These tests check the script's rules, not MiniLM.
"""

import hashlib
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from scripts import compare_fields as cf

REV = "a" * 40
OTHER_REV = "b" * 40


def make_snapshot(tmp_path, files=None):
    files = files or {"model.safetensors": b"weights-one", "onnx/model.onnx": b"weights-two"}
    snap = tmp_path / "snapshot"
    for name, content in files.items():
        (snap / name).parent.mkdir(parents=True, exist_ok=True)
        (snap / name).write_bytes(content)
    weights = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    return snap, weights


def pin_with(weights, revision=REV):
    return {"model": "org/model", "revision": revision, "seed": 42, "libraries": {}, "weights": weights}


def locator(path):
    return lambda pin: path


def missing_snapshot(pin):
    raise OSError("Cannot find the requested files in the disk cache")


# --- weight check and transformers commit hash -----------------------------------------------------

def test_weights_match_without_a_transformers_hash(tmp_path):
    snap, weights = make_snapshot(tmp_path)
    loaded, text, verified, error = cf.verify_loaded_model(None, pin_with(weights), False, locator(snap))
    assert (loaded, verified, error) == (REV, True, None)
    assert text == "verified 2/2 weight file(s) against pin"


def test_transformers_hash_is_compared_and_weights_are_still_checked(tmp_path):
    snap, weights = make_snapshot(tmp_path)
    loaded, text, verified, error = cf.verify_loaded_model(REV, pin_with(weights), False, locator(snap))
    assert (loaded, verified, error) == (REV, True, None)
    assert text.startswith("transformers commit hash equals pin") and "verified 2/2" in text

    # equal transformers hash does not excuse a tampered weight file
    (snap / "model.safetensors").write_bytes(b"tampered")
    loaded, text, verified, error = cf.verify_loaded_model(REV, pin_with(weights), False, locator(snap))
    assert loaded is None and not verified and "model.safetensors" in error


def test_transformers_hash_that_differs_from_the_pin_is_an_error_before_any_snapshot_lookup():
    def must_not_be_called(pin):
        raise AssertionError("snapshot lookup should not happen")

    loaded, text, verified, error = cf.verify_loaded_model(OTHER_REV, pin_with({"f": "0" * 64}), True, must_not_be_called)
    assert loaded is None and not verified
    assert OTHER_REV in error and REV in error


def test_weight_mismatch_and_missing_file_always_fail_even_with_the_allow_flag(tmp_path):
    snap, weights = make_snapshot(tmp_path)
    (snap / "onnx" / "model.onnx").write_bytes(b"changed")
    for allow in (False, True):
        _, text, verified, error = cf.verify_loaded_model(None, pin_with(weights), allow, locator(snap))
        assert error and "onnx/model.onnx" in error and not verified
    (snap / "onnx" / "model.onnx").unlink()
    _, _, verified, error = cf.verify_loaded_model(None, pin_with(weights), True, locator(snap))
    assert error and "missing onnx/model.onnx" in error and not verified


# --- missing snapshot or missing hashes -------------------------------------------------------------

def test_missing_snapshot_fails_loudly_by_default():
    loaded, text, verified, error = cf.verify_loaded_model(None, pin_with({"f": "0" * 64}), False, missing_snapshot)
    assert loaded is None and not verified
    assert "--allow-unverified-snapshot" in error and "Cannot verify" in error
    assert text.startswith("NOT verified")


def test_missing_snapshot_with_the_flag_runs_and_says_so():
    loaded, text, verified, error = cf.verify_loaded_model(None, pin_with({"f": "0" * 64}), True, missing_snapshot)
    assert error is None and loaded is None and verified is False
    assert "NOT verified" in text and "--allow-unverified-snapshot" in text

    # a matching transformers hash is kept, but the weights still count as unverified
    loaded, text, verified, error = cf.verify_loaded_model(REV, pin_with({"f": "0" * 64}), True, missing_snapshot)
    assert error is None and loaded == REV and verified is False and "weights NOT verified" in text


def test_pin_without_weight_hashes_is_treated_like_a_missing_snapshot():
    loaded, text, verified, error = cf.verify_loaded_model(REV, pin_with({}), False, missing_snapshot)
    assert error and "no weight hashes" in error and not verified
    loaded, text, verified, error = cf.verify_loaded_model(REV, pin_with({}), True, missing_snapshot)
    assert error is None and not verified and "no weight hashes" in text


# --- re-pinning ---------------------------------------------------------------------------------------

def fake_resolver(model_name):
    return OTHER_REV, {"model.safetensors": "c" * 64}


def test_write_pin_fills_revision_weights_libraries_time_and_note():
    now = datetime(2026, 11, 3, 12, 30, 45, 999, tzinfo=timezone.utc)
    new = cf.write_pin({"model": "org/model", "revision": None, "seed": 42, "libraries": {}}, {"numpy": "2.0", "torch": None},
                       fake_resolver, now)
    assert new["revision"] == OTHER_REV and new["weights"] == {"model.safetensors": "c" * 64}
    assert new["libraries"] == {"numpy": "2.0"}
    assert new["pinned_at"] == "2026-11-03T12:30:45+00:00"
    assert "2026-11-03T12:30:45+00:00" in new["note"] and "--force-repin" in new["note"]


@pytest.fixture
def pin_file(tmp_path, monkeypatch):
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(pin_with({"model.safetensors": "d" * 64})) + "\n", encoding="utf-8")
    monkeypatch.setattr(cf, "PIN_FILE", path)
    monkeypatch.setattr(cf, "load_pin", lambda: json.loads(path.read_text(encoding="utf-8")))

    def must_not_resolve(model_name):
        raise AssertionError("must not contact the Hub")

    monkeypatch.setattr(cf, "resolve_revision_and_weights", must_not_resolve)
    return path


def test_write_pin_refuses_to_overwrite_an_existing_revision(pin_file, capsys):
    before = pin_file.read_bytes()
    assert cf.main(["--write-pin"]) == 2
    err = capsys.readouterr().err
    assert REV in err and "--force-repin" in err
    assert pin_file.read_bytes() == before


def test_force_repin_rewrites_the_pin_and_carries_on_to_loading_the_model(pin_file, monkeypatch):
    monkeypatch.setattr(cf, "resolve_revision_and_weights", fake_resolver)
    monkeypatch.setattr(cf, "installed_versions", lambda: {"numpy": "2.0"})

    class Stop(Exception):
        pass

    def raising_model(*args, **kwargs):
        raise Stop

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=raising_model))
    with pytest.raises(Stop):
        cf.main(["--write-pin", "--force-repin"])
    written = json.loads(pin_file.read_text(encoding="utf-8"))
    assert written["revision"] == OTHER_REV and written["libraries"] == {"numpy": "2.0"}
    assert written["pinned_at"] in written["note"]


def test_write_pin_still_works_when_there_is_no_revision_yet(pin_file, monkeypatch):
    path = pin_file
    path.write_text(json.dumps({"model": "org/model", "revision": None, "seed": 42, "libraries": {}}) + "\n")
    monkeypatch.setattr(cf, "resolve_revision_and_weights", fake_resolver)
    monkeypatch.setattr(cf, "installed_versions", lambda: {"numpy": "2.0"})
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        types.SimpleNamespace(SentenceTransformer=lambda *a, **k: (_ for _ in ()).throw(KeyError("stop"))))
    with pytest.raises(KeyError):
        cf.main(["--write-pin"])
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == OTHER_REV


# --- the manifest records how the weights were checked ---------------------------------------------

class FakeModel:
    def __init__(self, *args, **kwargs):
        self.config = types.SimpleNamespace(_commit_hash=None)
        self.auto_model = types.SimpleNamespace(config=self.config)

    def __getitem__(self, index):
        return self

    def encode(self, texts, show_progress_bar=False):
        import numpy as np
        return np.array([[len(t), sum(map(ord, t)) % 97, 1.0] for t in texts])


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    csv = tmp_path / "fields.csv"
    pd.DataFrame([("DEIMS", "title", "FLAGGED: x"), ("ICOS", "hasName", "FLAGGED: x"), ("ACTRIS", "name", "FLAGGED: x")],
                 columns=["ri", "field", "definition"]).to_csv(csv, index=False)
    pin_path = tmp_path / "pin.json"
    snap, weights = make_snapshot(tmp_path)
    pin_path.write_text(json.dumps(pin_with(weights)) + "\n", encoding="utf-8")
    monkeypatch.setattr(cf, "ROOT", tmp_path)
    monkeypatch.setattr(cf, "IN_FILE", csv)
    monkeypatch.setattr(cf, "PIN_FILE", pin_path)
    monkeypatch.setattr(cf, "RUN_FILE", tmp_path / "run.json")
    monkeypatch.setattr(cf, "load_pin", lambda: json.loads(pin_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(cf, "installed_versions", lambda: {})
    monkeypatch.setattr(cf, "pair_file", lambda a, b, out_dir=None: tmp_path / f"{a}_{b}.csv")
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeModel))
    return tmp_path, snap


def test_manifest_records_verified_weights(run_env, monkeypatch):
    tmp_path, snap = run_env
    monkeypatch.setattr(cf, "locate_snapshot", locator(snap))
    assert cf.main([]) == 0
    model = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["model"]
    assert model["revision_loaded"] == REV and model["weights_verified"] is True
    assert model["allow_unverified_snapshot"] is False and "verified 2/2" in model["revision_loaded_verification"]


def test_manifest_records_when_the_unverified_flag_was_used(run_env, monkeypatch):
    tmp_path, _ = run_env
    monkeypatch.setattr(cf, "locate_snapshot", missing_snapshot)
    assert cf.main([]) == 2 and not (tmp_path / "run.json").exists()
    assert cf.main(["--allow-unverified-snapshot"]) == 0
    model = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["model"]
    assert model["revision_loaded"] is None and model["weights_verified"] is False
    assert model["allow_unverified_snapshot"] is True and "NOT verified" in model["revision_loaded_verification"]


# --- the committed pin file ----------------------------------------------------------------------------

def test_committed_pin_file_note_matches_its_own_pin_time_and_hashes_look_like_sha256():
    pin = json.loads(Path(cf.PIN_FILE).read_text(encoding="utf-8"))
    assert pin["pinned_at"] in pin["note"]
    assert pin["note"] == cf.pin_note(pin["pinned_at"])
    assert re.fullmatch(r"[0-9a-f]{40}", pin["revision"])
    assert pin["weights"] and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in pin["weights"].values())
