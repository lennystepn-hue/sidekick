"""PyInstaller entry point (equivalent to `python -m sidekick`)."""

import multiprocessing
import sys

from sidekick.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
