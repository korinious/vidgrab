"""PyInstaller entry script (PyInstaller needs a file, not ``-m vidgrab``)."""

import sys

from vidgrab.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
