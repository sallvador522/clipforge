"""Development API launcher that loads `.env` (no extra dependency).

Usage (from the repository root):
    .venv\\Scripts\\python.exe scripts\\dev_api.py

Loads KEY=VALUE pairs from `.env` without overriding variables already set in
the real environment, then starts uvicorn with reload. It never prints secret
values; it only reports whether MODEL_API_KEY is present.

No live request is made here. Development launchers force transcription and the
director to mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is set explicitly; even then
the app still requires its normal live-mode flags, key and budget ledger.
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


def enforce_dev_safety() -> None:
    if os.environ.get("CLIPFORGE_DEV_ALLOW_LIVE", "0").strip() == "1":
        print("Dev safety: LIVE mode explicitly allowed by CLIPFORGE_DEV_ALLOW_LIVE=1.")
        return
    os.environ["CLIPFORGE_TRANSCRIBE_MODE"] = "mock"
    os.environ["CLIPFORGE_DIRECTOR_MODE"] = "mock"
    os.environ["CLIPFORGE_SEGMENTATION_MODE"] = "mock"
    os.environ["CLIPFORGE_IMAGE_MODE"] = "mock"
    print(
        "Dev safety: transcription/director/segmentation/image forced to mock. "
        "Set CLIPFORGE_DEV_ALLOW_LIVE=1 to opt in to live."
    )


def main() -> int:
    load_env(ROOT / ".env")
    enforce_dev_safety()

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
        f"director_mode={os.environ.get('CLIPFORGE_DIRECTOR_MODE', 'mock')} | "
        f"segmentation_mode={os.environ.get('CLIPFORGE_SEGMENTATION_MODE', 'mock')} | "
        f"image_mode={os.environ.get('CLIPFORGE_IMAGE_MODE', 'mock')} | "
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
