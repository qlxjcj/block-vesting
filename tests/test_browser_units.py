"""Run the browser unit tests under pytest.

The page converts GEN text to wei, mirrors the contract's vesting arithmetic,
and decides whether a height is fresh on both providers. That code lives in
units.mjs and is tested here, so the browser half is never a second, untested
copy of the contract's rules.
"""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_browser_rules_match_the_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; run `node --test tests/js/units.test.mjs`")
    r = subprocess.run(
        [node, "--test", str(ROOT / "tests" / "js" / "units.test.mjs")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr
