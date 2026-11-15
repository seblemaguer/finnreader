"""Entry point of the standalone builds.

The executable named ``finnreader`` opens the reader; the one named ``finnreader-cli`` runs the
batch commands (Windows GUI programs have no console to print to).
"""
import sys
from pathlib import Path

from finnreader import cli
from finnreader.main import main

if __name__ == "__main__":
    if Path(sys.executable).stem.endswith("-cli"):
        sys.exit(cli.run(sys.argv[1:]))
    main()
