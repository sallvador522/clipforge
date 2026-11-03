"""LIVE-CALL 010 — first real idea-to-video storyboard (user-approved, cap $1).

Exactly ONE Muse Spark call (contributor, storyboard schema, no retries).
Saves the validated storyboard JSON; image generation is a SEPARATE step
needing its own explicit approval.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "packages/director", "apps/worker", "apps/api"):
    sys.path.insert(0, str(ROOT / _p))

IDEA = (
    "Cria uma apresentação cinematográfica científica de 20 segundos, formato "
    "vertical 9:16 para reels, sobre o que aconteceria se um asteroide gigante "
    "atingisse a Terra. Realista, dramático e educativo, estilo documentário."
)
RESULT_PATH = ROOT / "storage" / "live-call-010-storyboard-result.json"


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
    if "--execute-live-call-010" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-010 to confirm this single approved call.")
        return 2
    if RESULT_PATH.exists():
        print("Refusing: result already exists — a new call needs fresh approval.")
        return 2

    load_env(ROOT / ".env")
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing or empty. No request attempted.")
        return 2

    from clipforge_director import (
        CreativeDirectorProvider,
        LiveCallAuthorization,
        LiveCallBudget,
    )
    from clipforge_director.creative import CREATIVE_BRIEF

    budget = LiveCallBudget(ROOT / "storage")
    authorization = LiveCallAuthorization(budget, "director")
    provider = CreativeDirectorProvider(
        api_key,
        CREATIVE_BRIEF,
        "storyboard-only",
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=16000,
    )
    try:
        board = provider.create_storyboard(IDEA, authorization=authorization)
    except Exception as exc:
        print(json.dumps({"outcome": type(exc).__name__, "message": str(exc)[:500]}, indent=2))
        return 1

    record = {
        "call": "LIVE-CALL 010",
        "idea": IDEA,
        "project_title": board.project_title,
        "duration_seconds": board.duration_seconds,
        "aspect_ratio": board.aspect_ratio,
        "output_fps": board.output_fps,
        "resolution": board.resolution,
        "scenes": len(board.scenes),
        "assets": [{"asset_id": a.asset_id, "description": a.description, "scenes": a.scene_ids} for a in board.asset_plan],
        "usage": provider.last_usage.model_dump() if provider.last_usage is not None else None,
        "storyboard": board.model_dump(mode="json"),
    }
    RESULT_PATH.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k != "storyboard"}, indent=2, ensure_ascii=False))
    print(f"Storyboard saved ({len(board.scenes)} scenes, {len(board.asset_plan)} assets).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
