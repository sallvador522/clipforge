"""LIVE-CALL 011 — four Muse Image scene plates (user-approved, ~$0.04).

Exactly FOUR POSTs (one per scene plate), no retries. Each generation has
its own output dir and its own one-shot ledger authorization. Refuses to
overwrite existing plates: a repeat needs fresh approval + empty dirs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "packages/director"):
    sys.path.insert(0, str(ROOT / _p))

STORYBOARD_PATH = ROOT / "storage" / "live-call-010-storyboard-result.json"
OUT_ROOT = ROOT / "storage" / "idea_assets_live"

SCENE_ASSETS = [
    ("scene_1", "asset_space"),
    ("scene_2", "asset_entry"),
    ("scene_3", "asset_impact"),
    ("scene_4", "asset_aftermath"),
]


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
    if "--execute-live-call-011" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-011 to confirm these four approved calls.")
        return 2
    if not STORYBOARD_PATH.is_file():
        print("Refusing: LIVE-CALL 010 storyboard result missing.")
        return 2
    if OUT_ROOT.exists() and any(OUT_ROOT.iterdir()):
        print("Refusing: output dir is not empty — a repeat needs fresh approval.")
        return 2

    load_env(ROOT / ".env")
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing or empty. No request attempted.")
        return 2

    from clipforge_director import LiveCallAuthorization, LiveCallBudget
    from clipforge_providers import MuseImageBackgroundProvider

    board = json.loads(STORYBOARD_PATH.read_text(encoding="utf-8"))["storyboard"]
    prompts = {s["scene_id"]: s["image_generation_prompt"] for s in board["scenes"]}
    budget = LiveCallBudget(ROOT / "storage")
    provider = MuseImageBackgroundProvider(api_key)
    results: list[dict] = []
    for scene_id, asset_id in SCENE_ASSETS:
        out_dir = OUT_ROOT / asset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = prompts[scene_id] + ", vertical 9:16 composition, no text, no watermark"
        authorization = LiveCallAuthorization(budget, "image")
        try:
            result = provider.generate(
                prompt=prompt,
                orientation="portrait",
                output_dir=out_dir,
                job_id=f"live-call-011-{asset_id}",
                authorization=authorization,
            )
        except Exception as exc:
            print(json.dumps({"outcome": type(exc).__name__, "scene": scene_id, "message": str(exc)[:300]}))
            return 1
        results.append({"scene_id": scene_id, "asset_id": asset_id, "path": str(out_dir / "background.png")})
        print(f"generated {asset_id} for {scene_id}: {provider.last_request_id}")
    (OUT_ROOT / "live-call-011-result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"4 plates done in {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
