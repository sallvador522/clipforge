"""Development API launcher that loads `.env` (no extra dependency).

Usage (from the repository root):
    .venv\\Scripts\\python.exe scripts\\dev_api.py

Loads KEY=VALUE pairs from `.env` without overriding variables already set in
the real environment, then starts uvicorn with reload. It never prints secret
values; it only reports whether MODEL_API_KEY is present.

No live request is made here. Transcription stays mock unless
CLIPFORGE_TRANSCRIBE_MODE=live is set *and* the call is explicitly approved.
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
            line = line[len("export "):]
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
    pythonpath = os.pathsep.join(str(p) for p in repo_paths)
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = f"{pythonpath}{os.pathsep}{existing}" if existing else pythonpath
    for path in reversed(repo_paths):
        sys.path.insert(0, str(path))

    import uvicorn

    from clipforge_api.main import app

    key_present = bool(os.environ.get("MODEL_API_KEY", "").strip())
    print(
        "ClipForge API dev launcher | "
        f"ai_mode={os.environ.get('CLIPFORGE_AI_MODE', 'mock')} | "
        f"transcribe_mode={os.environ.get('CLIPFORGE_TRANSCRIBE_MODE', 'mock')} | "
        f"MODEL_API_KEY={'present' if key_present else 'missing'}"
    )
    print("No live request is made by this launcher.")

    # The app object is passed directly so Windows multiprocessing never has to
    # re-import the package in a child process; restart the launcher after code edits.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("CLIPFORGE_API_PORT", "8000")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
