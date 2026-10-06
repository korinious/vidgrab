import tomllib
from pathlib import Path

import vidgrab


def test_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == vidgrab.__version__


def test_release_notes_exist_for_current_version():
    # The release job refuses to publish a tag without docs/release-notes/vX.Y.Z.md;
    # catch a version bump without notes here, long before tagging.
    notes = Path(__file__).parents[1] / "docs" / "release-notes" / f"v{vidgrab.__version__}.md"
    assert notes.is_file(), f"missing {notes.relative_to(notes.parents[2])}"
    assert notes.read_text(encoding="utf-8").strip()
