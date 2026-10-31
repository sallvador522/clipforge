"""LIVE-CALL 004 — single approved Muse Spark call (Contributor Medium, lite schema, 1500-token cap).

Identical payload to LIVE-CALL 003 except `max_completion_tokens: 1500` (003 was
truncated at 800; the lite schema itself was accepted with HTTP 200).

GUARDS (all must hold or the script exits BEFORE any network use):
- `--execute-live-call-004` flag required.
- `MODEL_API_KEY` present and non-empty (server-side `.env` only).
- `CLIPFORGE_AI_MODE` and `CLIPFORGE_TRANSCRIBE_MODE` must be `mock`.
- `docs/live-call-004-result.json` must NOT exist (exactly one call ever).

Exactly ONE POST; no retries. Never prints/logs the key or raw prompt. On HTTP
error or validation failure it prints structured context (status, request id,
usage when available) and writes no result file.
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
VIDEO = {"width": 1280, "height": 720, "fps": 30.0, "duration_seconds": 10.0, "frame_count": 300, "has_audio": True}


def main() -> int:
    if "--execute-live-call-004" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-004 to confirm this single approved call.")
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
        print("Refusing: MODEL_API_KEY is missing or empty. No request attempted.")
        return 2

    result_path = ROOT / "docs" / "live-call-004-result.json"
    if result_path.exists():
        print("Refusing: docs/live-call-004-result.json already exists — a new call needs fresh approval.")
        return 2

    import datetime as _datetime  # noqa: E402

    from clipforge_contracts import TranscriptResult  # noqa: E402
    from clipforge_contracts.director_lite import LITE_BRIEF, lite_capability_summary  # noqa: E402
    from clipforge_contracts.edl import edl_from_professional_plan  # noqa: E402
    from clipforge_director import DirectorVideoMetadata, LiteMetaEditingDirectorProvider  # noqa: E402
    from clipforge_director.spark import DirectorAPIError, DirectorValidationError  # noqa: E402

    provider = LiteMetaEditingDirectorProvider(
        api_key,
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=1500,
    )
    transcript = TranscriptResult(text=INSTRUCTION, language="pt-BR", provider_name="user-confirmed", is_mock=False)
    video = DirectorVideoMetadata(**VIDEO)

    try:
        plan = provider.create_plan(transcript, video)
    except DirectorAPIError as exc:
        print(
            json.dumps(
                {
                    "call": "LIVE-CALL 004",
                    "outcome": "http_error_no_plan",
                    "http_status": exc.status_code,
                    "error_type": exc.error_type,
                    "server_request_id": exc.server_request_id,
                    "message": str(exc),
                    "model": provider.model,
                    "at_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                    "usage": provider.last_usage.model_dump(mode="json") if provider.last_usage else None,
                },
                indent=2,
            )
        )
        return 1
    except DirectorValidationError as exc:
        print(
            json.dumps(
                {
                    "call": "LIVE-CALL 004",
                    "outcome": "validation_failed_no_plan",
                    "http_status": 200,
                    "server_request_id": exc.server_request_id,
                    "message": str(exc),
                    "model": provider.model,
                    "at_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                    "usage": provider.last_usage.model_dump(mode="json") if provider.last_usage else None,
                },
                indent=2,
            )
        )
        return 1

    assert provider.last_usage is not None and provider.last_request_id is not None
    record = {
        "call": "LIVE-CALL 004",
        "model": provider.model,
        "reasoning_effort": "medium",
        "max_completion_tokens": 1500,
        "endpoint": "POST https://api.meta.ai/v1/chat/completions",
        "instruction": INSTRUCTION,
        "video_metadata": VIDEO,
        "request_id": provider.last_request_id,
        "plan_outcome": plan.outcome.value,
        "plan_operations": [op.capability_id for op in plan.operations],
        "plan_approval": plan.approval_status.value,
        "summary_explanation": plan.summary_explanation,
        "plan": plan.model_dump(mode="json"),
        "plan_adapted_to_v1": plan.to_execution_plan().model_dump(mode="json"),
        "edl_projected": edl_from_professional_plan(plan).model_dump(mode="json"),
        "usage": provider.last_usage.model_dump(mode="json"),
        "edl_render_executed": False,
    }
    result_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k not in {"instruction", "plan"}}, indent=2))
    print(f"Saved {result_path} (plan validated; render NOT executed).")
    provider.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
