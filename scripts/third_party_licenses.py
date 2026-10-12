"""Copy the license files of every Python package VidGrab ships into a folder.

    uv run python scripts/third_party_licenses.py OUT_DIR

Used by build.yml for ``VidGrab/licenses/python/`` in the zip. Walks the runtime
dependencies of ``vidgrab`` (with extras such as ``yt-dlp[default]``) in the current
environment, copies each package's license files from its ``.dist-info`` into
``OUT_DIR/<name>-<version>/`` and writes ``OUT_DIR/INDEX.md`` (name, version, license).
A package without any license file fails the run, unless it is listed in
``LICENSE_ELSEWHERE`` with the file in ``LICENSES/`` that covers it.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import shutil
import sys
from pathlib import Path

from packaging.requirements import Requirement

ROOT_PACKAGE = "vidgrab"
# Wheels without license files in their metadata, covered by a text in LICENSES/.
LICENSE_ELSEWHERE = {
    "pyside6-essentials": "qt-pyside6-LGPL-3.0.txt",
    "shiboken6": "qt-pyside6-LGPL-3.0.txt",
}
LICENSE_NAME = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_closure(root: str = ROOT_PACKAGE) -> list[md.Distribution]:
    """``root``'s runtime dependencies, recursively, for this platform (no dev group)."""
    seen: dict[str, md.Distribution] = {}
    todo: list[tuple[str, frozenset[str]]] = [(root, frozenset())]
    while todo:
        name, extras = todo.pop()
        dist = md.distribution(name)
        key = normalize(dist.metadata["Name"])
        if key in seen and not extras:
            continue
        seen[key] = dist
        for line in dist.requires or []:
            req = Requirement(line)
            envs = [{"extra": extra} for extra in extras] or [{"extra": ""}]
            if req.marker is None or any(req.marker.evaluate(env) for env in envs):
                todo.append((req.name, frozenset(req.extras)))
    seen.pop(normalize(root), None)
    return sorted(seen.values(), key=lambda d: normalize(d.metadata["Name"]))


def license_files(dist: md.Distribution) -> list[Path]:
    files = []
    for entry in dist.files or []:
        parts = Path(str(entry)).parts
        if parts and parts[0].endswith(".dist-info") and LICENSE_NAME.search(parts[-1]):
            files.append(Path(str(dist.locate_file(entry))))
    return sorted(files)


def license_label(dist: md.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if "License" in c]
    if classifiers:
        return ", ".join(classifiers)
    first_line = (meta.get("License") or "").strip().splitlines()[:1]
    return first_line[0] if first_line else "see file"


def collect(out_dir: Path) -> list[str]:
    """Copy the files; returns the problems (packages without a license file)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, problems = [], []
    for dist in runtime_closure():
        name, version = dist.metadata["Name"], dist.version
        files = license_files(dist)
        target = out_dir / f"{normalize(name)}-{version}"
        for path in files:
            target.mkdir(exist_ok=True)
            shutil.copy2(path, target / path.name)
        where = ", ".join(f"`{target.name}/{p.name}`" for p in files)
        if not files:
            covered = LICENSE_ELSEWHERE.get(normalize(name))
            if covered is None:
                problems.append(f"{name} {version}: no license file in its metadata")
                continue
            where = f"`../{covered}`"
        rows.append(f"| {name} | {version} | {license_label(dist)} | {where} |")
    index = [
        "# Python packages bundled with VidGrab",
        "",
        "| Package | Version | License | File |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
    ]
    (out_dir / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    problems = collect(Path(argv[0]))
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"Wrote {argv[0]}/INDEX.md" if not problems else "Missing license files")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
