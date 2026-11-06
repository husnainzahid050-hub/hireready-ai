"""Vercel installs from pyproject.toml; CI and pip-audit use requirements.txt. Keep them in sync."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_and_requirements_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    from_pyproject = {d.lower() for d in pyproject["project"]["dependencies"]}
    from_reqs = {
        line.strip().lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert from_pyproject == from_reqs
