"""LIVE-CALL 001 — single approved Muse Spark plan-generation call (Contributor Medium).

GUARDS (all must hold or the script exits BEFORE any network use):
- `--execute-live-call-001` flag must be passed (no accidental runs).
- `MODEL_API_KEY` must be present and non-empty (server-side `.env` only).
- `CLIPFORGE_AI_MODE` must be `mock` (default when unset).
- `CLIPFORGE_TRANSCRIBE_MODE` must be `mock`.
- `docs/live-call-001-result.json` must NOT exist (exactly one call ever).

Sends exactly ONE POST to https://api.meta.ai/v1/chat/completions and exits.
No retries: any transport/API/validation failure aborts with a non-zero exit.
Never prints or logs the API key.

Usage (from the repository root):
    .\\.venv\\Scripts\\python.exe scripts\\live_call_001_spark.py --execute-live-call-001
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "packages/director", "apps/worker", "apps/api"):
    sys.path.insert(0, str(ROOT / _p))


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


INSTRUCTION = (
    "Keep me sharp, blur the people behind me and replace the background "
    "with a cinematic Luanda sunset."
)

# Benchmark-unit video metadata (documented assumption, not measured media).
VIDEO = {"width": 1280, "height": 720, "fps": 30.0, "duration_seconds": 10.0, "frame_count": 300, "has_audio": True}


def main() -> int:
    if "--execute-live-call-001" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-001 to confirm this single approved call.")
        return 2

    load_env(ROOT / ".env")

    if os.environ.get("CLIPFORGE_AI_MODE", "mock").strip().lower() != "mock":
        print("Refusing: CLIPFORGE_AI_MODE must be mock.")
        return 2
    if os.environ.get("CLIPFORGE_TRANSCRIBE_MODE", "mock").strip().lower() != "mock":
        print("Refusing: CLIPFORGE_TRANSCRIBE_MODE must be mock.")
        return 2
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing or empty (server-side .env only). No request attempted.")
        return 2

    result_path = ROOT / "docs" / "live-call-001-result.json"
    if result_path.exists():
        print("Refusing: docs/live-call-001-result.json already exists — a second call needs fresh approval.")
        return 2

    from clipforge_api.playbook import default_playbook  # noqa: E402
    from clipforge_contracts import TranscriptResult, capability_summary_for_prompt  # noqa: E402
    from clipforge_director import DirectorVideoMetadata, MetaEditingDirectorProvider  # noqa: E402
    from clipforge_director.spark import DirectorAPIError  # noqa: E402

    playbook = default_playbook()
    provider = MetaEditingDirectorProvider(
        api_key,
        playbook.text,
        capability_summary_for_prompt(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
    )
    transcript = TranscriptResult(text=INSTRUCTION, language="pt-BR", provider_name="user-confirmed", is_mock=False)
    video = DirectorVideoMetadata(**VIDEO)

    import datetime as _datetime

    try:
        plan = provider.create_plan(transcript, video)  # exactly one POST; raises on any failure
    except DirectorAPIError as exc:
        # No result file is written on failure (preserves the exactly-once guard).
        # server_request_id is the panel-matchable handle; the key is never printed.
        print(
            json.dumps(
                {
                    "call": "LIVE-CALL 001",
                    "outcome": "http_error_no_plan",
                    "http_status": exc.status_code,
                    "error_type": exc.error_type,
                    "server_request_id": exc.server_request_id,
                    "message": str(exc),
                    "model": provider.model,
                    "at_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                    "usage": None,
                    "note": "Match server_request_id against the Meta panel; usage on failed Spark calls is metered server-side.",
                },
                indent=2,
            )
        )
        return 1
    assert provider.last_usage is not None and provider.last_request_id is not None

    record = {
        "call": "LIVE-CALL 001",
        "model": provider.model,
        "reasoning_effort": "medium",
        "endpoint": "POST https://api.meta.ai/v1/chat/completions",
        "instruction": INSTRUCTION,
        "video_metadata": VIDEO,
        "request_id": provider.last_request_id,
        "plan_outcome": plan.outcome.value,
        "plan_operations": [op.capability_id for op in plan.operations],
        "plan_approval": plan.approval_status.value,
        "usage": provider.last_usage.model_dump(mode="json"),
        "edl_render_executed": False,
    }
    result_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k != "instruction"}, indent=2))
    print(f"Saved {result_path} (plan JSON validated; render NOT executed).")
    provider.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
