"""Entry point: ``python -m pull1sec`` (or the ``pull1sec`` console script)."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
