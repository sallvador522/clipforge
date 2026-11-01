"""Development worker launcher that loads `.env` (mirrors scripts/dev_api.py).

Run from the repository root:
    .\\.venv\\Scripts\\python.exe scripts\\dev_worker.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_env(ROOT / ".env")
    repo_paths = [
        ROOT / "packages" / "contracts",
        ROOT / "packages" / "providers",
        ROOT / "packages" / "jobs",
        ROOT / "packages" / "director",
        ROOT / "apps" / "worker",
        ROOT / "apps" / "api",
    ]
    for path in reversed(repo_paths):
        sys.path.insert(0, str(path))

    from clipforge_jobs import JobStore
    from clipforge_providers import get_providers
    from clipforge_worker.worker_process import PersistentWorker

    logging_ready = os.environ.get("CLIPFORGE_AI_MODE", "mock")
    providers = get_providers()
    print(
        f"ClipForge worker | ai_mode={logging_ready} | "
        f"transcribe={providers.transcription_mode} | director={providers.director_mode}"
    )
    worker = PersistentWorker(JobStore(Path(os.environ.get("CLIPFORGE_STORAGE_ROOT", "storage"))), providers, poll_seconds=0.5)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    raise SystemExit(main())
