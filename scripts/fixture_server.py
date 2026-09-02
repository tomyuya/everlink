"""CLI entrypoint for the EverLink fixture server (logic in everlink/fixtures.py).

Usage:
    python scripts/fixture_server.py            # http://127.0.0.1:8787
    python scripts/fixture_server.py --port 9000
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.fixtures import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
