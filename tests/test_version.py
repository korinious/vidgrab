import tomllib
from pathlib import Path

import vidgrab


def test_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == vidgrab.__version__
