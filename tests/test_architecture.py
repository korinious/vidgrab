"""Guard the core/ui split: nothing under vidgrab.core may pull in Qt."""

import pkgutil
import subprocess
import sys

import vidgrab.core


def test_core_does_not_import_qt():
    modules = [m.name for m in pkgutil.iter_modules(vidgrab.core.__path__, "vidgrab.core.")]
    assert modules, "no core modules found"
    code = (
        "import importlib, sys\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "import vidgrab.strings\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6'))\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
