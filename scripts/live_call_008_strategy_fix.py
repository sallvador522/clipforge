"""LIVE-CALL 008 — record proof that params.strategy is now a valid enum value.

LIVE-CALL 007 already proved the fix at the validation gate: the same kind of
instruction that used to fail with `strategy='mock_segmentation'` returned a
validated plan. That run crashed afterwards in this harness (it read the typed
`params` model as a dict), so no artefact was written. This call records it.

GUARDS: `--execute-live-call-008` flag, MODEL_API_KEY present, result file absent.
Exactly ONE POST, no retries.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "packages/director", "apps/worker", "apps/api"):
    sys.path.insert(0, str(ROOT / _p))

INSTRUCTION = "Deixa-me nítido e desfoca o fundo, por favor."
VIDEO = {
    "width": 1280,
    "height": 720,
    "fps": 30.0,
    "duration_seconds": 10.0,
    "frame_count": 300,
    "has_audio": True,
}


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
    if "--execute-live-call-008" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-008 to confirm this single approved call.")
        return 2

    load_env(ROOT / ".env")
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing or empty. No request attempted.")
        return 2

    result_path = ROOT / "storage" / "live-call-008-strategy-fix-result.json"
    if result_path.exists():
        print("Refusing: result already exists — a new call needs fresh approval.")
        return 2

    from clipforge_contracts import TranscriptResult
    from clipforge_contracts.director_lite import LITE_BRIEF, lite_capability_summary
    from clipforge_director import (
        DirectorVideoMetadata,
        LiteMetaEditingDirectorProvider,
        LiveCallAuthorization,
        LiveCallBudget,
    )
    from clipforge_director.spark import DirectorAPIError, DirectorValidationError

    provider = LiteMetaEditingDirectorProvider(
        api_key,
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=16000,
    )
    transcript = TranscriptResult(
        text=INSTRUCTION, language="pt-BR", provider_name="user-confirmed", is_mock=False
    )
    authorization = LiveCallAuthorization(LiveCallBudget(ROOT / "storage"), "director")

    try:
        plan = provider.create_plan(
            transcript, DirectorVideoMetadata(**VIDEO), authorization=authorization
        )
    except DirectorAPIError as exc:
        print(json.dumps({"outcome": "http_error", "status": exc.status_code, "message": str(exc)}, indent=2))
        return 1
    except DirectorValidationError as exc:
        print(json.dumps({"outcome": "validation_failed", "message": str(exc)}, indent=2))
        return 1

    # Persist first so a harness bug can never lose a paid result again.
    dumped = plan.model_dump(mode="json")
    strategies = [
        op.get("params", {}).get("strategy")
        for op in dumped["operations"]
        if op["capability_id"] == "subject.isolate"
    ]
    allowed = {"largest_subject", "named_subject", "foreground"}
    ok = all(s in allowed for s in strategies)
    record = {
        "call": "LIVE-CALL 008",
        "instruction": INSTRUCTION,
        "outcome": plan.outcome.value,
        "operations": [op.capability_id for op in plan.operations],
        "isolate_strategies": strategies,
        "strategy_valid": ok,
        "approval": plan.approval_status.value,
        "usage": provider.last_usage.model_dump(mode="json") if provider.last_usage else None,
        "plan": dumped,
    }
    result_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k != "plan"}, indent=2))
    provider.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
