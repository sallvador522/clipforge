"""Generate deterministic synthetic mask fixtures locally (ADR-007). No external calls."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "packages" / "contracts", _ROOT / "apps" / "worker"):
    sys.path.insert(0, str(_p))

from clipforge_worker.fixtures import generate_all_fixtures  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "masks"
    paths = generate_all_fixtures(root)
    for path in paths:
        print(f"generated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
