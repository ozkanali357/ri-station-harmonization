"""Tests for scripts/extract_site_terms_field_allowlist.py — Step 1 of the site-terms plan.

Focus: the script must exit with a clear error and must NOT clobber the committed
allowlist when the gitignored raw cache is missing (i.e. on a clean clone).
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "extract_site_terms_field_allowlist.py"
OUT_REL = Path("outputs/site_terms_field_allowlist.csv")


def test_clean_clone_does_not_touch_output(tmp_path):
    """Running from a directory with no data/raw must fail before writing."""
    out = tmp_path / OUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "sentinel-content-do-not-overwrite\n"
    out.write_text(sentinel)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "script must exit non-zero on missing inputs"
    assert "missing" in (result.stderr + result.stdout).lower(), \
        f"expected 'missing' in output; got stderr={result.stderr!r} stdout={result.stdout!r}"
    assert out.read_text() == sentinel, "script must not overwrite output on missing inputs"
