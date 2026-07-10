import sys
from pathlib import Path

# Insert polymarket/ path BEFORE pytest collects test packages
# This prevents tests/control_plane/ from shadowing polymarket/control_plane/
polymarket_dir = str(Path(__file__).resolve().parent.parent / "polymarket")
if polymarket_dir not in sys.path:
    sys.path.insert(0, polymarket_dir)
