"""Thin entrypoint so ``python -m everlink <command>`` works (spec §12)."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
