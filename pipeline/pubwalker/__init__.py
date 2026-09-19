"""pubwalker pipeline. Every step reads and writes JSON under data/<slug>/ and is idempotent."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
SITE_DATA = REPO / "site" / "data"
