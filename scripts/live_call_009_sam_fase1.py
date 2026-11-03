"""LIVE-CALL 009 — Fase 1: single SAM segmentation on the Facebook clip.

The user explicitly approved exactly ONE live SAM call (~$0.0354 for 177
frames at $0.20/1000) to test whether the server persists the result after
our socket drops mid-stream.

GUARDS: `--execute-live-call-009` flag, MODEL_API_KEY present, result file
absent. Exactly ONE Responses POST, no retries. If the stream drops, the
script performs ONE non-billable GET /v1/responses/{resp_id} to check whether
the server kept processing (Fase 1 decision gate) — no second POST, no new
ledger slot.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "packages/director", "apps/worker", "apps/api"):
    sys.path.insert(0, str(ROOT / _p))

SOURCE = ROOT / "storage" / "uploads" / "cd9616b3c69a4d97b7a0a373572e340e" / "source.mp4"
RESULT_PATH = ROOT / "storage" / "live-call-009-sam-fase1-result.json"
OUT_DIR = ROOT / "storage" / "sam_fase1_test"


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
    if "--execute-live-call-009" not in sys.argv[1:]:
        print("Refusing: pass --execute-live-call-009 to confirm this single approved call.")
        return 2
    if RESULT_PATH.exists():
        print("Refusing: result already exists — a new call needs fresh approval.")
        return 2
    if not SOURCE.is_file():
        print(f"Refusing: source not found: {SOURCE}")
        return 2

    load_env(ROOT / ".env")
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing or empty. No request attempted.")
        return 2

    import httpx
    from clipforge_contracts import (
        SUBJECT_DETECTION_DISCLOSURE_VERSION,
        SubjectDetectionConsent,
        sha256_file,
    )
    from clipforge_director import LiveCallAuthorization, LiveCallBudget
    from clipforge_providers import SamSegmentationProvider, SamStreamInterruptedError

    job_id = "live-call-009-fase1"
    source_hash = sha256_file(SOURCE)
    consent = SubjectDetectionConsent(
        job_id=job_id,
        source_video_hash=source_hash,
        consent_given=True,
        consent_timestamp=datetime.now(timezone.utc),
        disclosure_version=SUBJECT_DETECTION_DISCLOSURE_VERSION,
        provider="meta-sam",
        model="sam-3.1",
        segmentation_mode="live",
    )
    budget = LiveCallBudget(ROOT / "storage")
    authorization = LiveCallAuthorization(budget, "segmentation")
    provider = SamSegmentationProvider(api_key)

    record: dict = {
        "call": "LIVE-CALL 009",
        "source": str(SOURCE),
        "source_sha256": source_hash,
        "prompt": "person",
    }
    try:
        result = provider.segment(
            job_id=job_id,
            source_video_id=job_id,
            output_dir=OUT_DIR,
            width=360,
            height=640,
            frame_count=177,
            fps=30.0,
            source_path=SOURCE,
            prompt="person",
            authorization=authorization,
            consent=consent,
        )
    except SamStreamInterruptedError as exc:
        record["outcome"] = "stream_interrupted"
        record["message"] = str(exc)
        record["response_id"] = exc.response_id
        record["request_id"] = provider.last_request_id
        record["file_cleanup"] = provider.last_file_cleanup
        # Fase 1 gate: ONE non-billable retrieval to see if the server kept
        # processing after our socket died. No POST, no new ledger slot.
        record["retrieval"] = _retrieve_once(api_key, exc.response_id)
        RESULT_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        return 1
    record["outcome"] = "completed"
    record["subjects"] = [
        {"object_id": s.object_id, "frames_detected": s.frames_detected}
        for s in result.subjects
    ]
    record["mask_manifest"] = result.mask_manifest_path
    record["request_id"] = provider.last_request_id
    record["file_cleanup"] = provider.last_file_cleanup
    RESULT_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0


def _retrieve_once(api_key: str, response_id: str | None) -> dict:
    """Single GET to check server-side persistence. Never POSTs, never bills."""
    if not response_id:
        return {"attempted": False, "reason": "no response id was observed before the drop"}
    import httpx

    try:
        response = httpx.get(
            f"https://api.meta.ai/v1/responses/{response_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
    except Exception as exc:
        return {"attempted": True, "response_id": response_id, "error": f"{type(exc).__name__}: {exc}"}
    body = response.text[:2000]
    parsed: dict = {}
    try:
        parsed = response.json()
    except Exception:
        pass
    status = parsed.get("status") if isinstance(parsed, dict) else None
    return {
        "attempted": True,
        "response_id": response_id,
        "http_status": response.status_code,
        "status": status,
        "body_preview": body,
    }


if __name__ == "__main__":
    raise SystemExit(main())
