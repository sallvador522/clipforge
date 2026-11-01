"""Prepare (but never execute) the LIVE-CALL 006 plan-only request.

This script builds the exact Chat Completions payload for the approved future test,
prints token/cost estimates for Standard and Contributor, and writes the request
JSON to storage/ (gitignored). It never calls create_plan, never opens a network
connection, and never invokes SAM, Muse Image, the renderer or the EDL executor.

Usage:
    python scripts/prepare_live_call_006.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
for path in reversed(
    [
        ROOT / "packages" / "contracts",
        ROOT / "packages" / "providers",
        ROOT / "packages" / "director",
        ROOT / "apps" / "api",
    ]
):
    sys.path.insert(0, str(path))

from clipforge_api.playbook import default_playbook  # noqa: E402
from clipforge_contracts import TranscriptResult  # noqa: E402
from clipforge_contracts.director_lite import lite_capability_summary  # noqa: E402
from clipforge_director import (  # noqa: E402
    DirectorVideoMetadata,
    LiteMetaEditingDirectorProvider,
    calculate_cost_usd,
    estimate_tokens,
)

INSTRUCTION = (
    "Keep me sharp, blur the people behind me and replace the background "
    "with a cinematic Luanda sunset."
)
OUTPUT_CAP = 16_000
EXPECTED_OUTPUT_TOKENS = 2_400  # prior 5-op live plan used 2,293 completion tokens
VIDEO = DirectorVideoMetadata(
    width=360,
    height=640,
    fps=30.0,
    duration_seconds=6.177007,
    frame_count=177,
    has_audio=True,
)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Preparation script attempted a network request: {request.url}")


def build(mode: str):
    contributor = mode == "contributor"
    provider = LiteMetaEditingDirectorProvider(
        "prepared-only-no-request",
        default_playbook().text,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor" if contributor else "muse-spark-1.3",
        reasoning_effort="medium",
        require_contributor=contributor,
        max_output_tokens=OUTPUT_CAP,
        timeout_seconds=180.0,
        client=httpx.Client(
            transport=httpx.MockTransport(_no_network),
            base_url="https://api.meta.ai",
        ),
    )
    transcript = TranscriptResult(
        text=INSTRUCTION,
        language="en",
        provider_name="prepared-only",
        is_mock=True,
    )
    payload, request_id = provider.request_payload(transcript, VIDEO)
    developer = payload["messages"][0]["content"]
    user = payload["messages"][1]["content"]
    input_tokens = estimate_tokens(developer) + estimate_tokens(user)
    expected_cost = calculate_cost_usd(input_tokens, EXPECTED_OUTPUT_TOKENS, mode)
    cap_cost = calculate_cost_usd(input_tokens, OUTPUT_CAP, mode)
    provider.close()
    return {
        "mode": mode,
        "model": payload["model"],
        "request_id": request_id,
        "playbook_chars": len(default_playbook().text),
        "developer_chars": len(developer),
        "user_chars": len(user),
        "payload_chars": len(json.dumps(payload)),
        "schema_chars": len(json.dumps(payload["response_format"]["json_schema"]["schema"])),
        "input_token_estimate_chars4": input_tokens,
        "expected_output_tokens": EXPECTED_OUTPUT_TOKENS,
        "max_completion_tokens": OUTPUT_CAP,
        "expected_cost_usd": expected_cost,
        "cap_cost_usd": cap_cost,
        "payload": payload,
    }


def main() -> int:
    storage = ROOT / "storage"
    storage.mkdir(exist_ok=True)
    summary = {}
    for mode in ("standard", "contributor"):
        data = build(mode)
        path = storage / f"live_call_006_request_{mode}.json"
        path.write_text(json.dumps(data["payload"], indent=2, ensure_ascii=False), encoding="utf-8")
        summary[mode] = {key: value for key, value in data.items() if key != "payload"}
        summary[mode]["request_path"] = str(path)

    print("LIVE-CALL 006 PLAN-ONLY PREPARATION (NO REQUEST MADE)")
    print(f"instruction: {INSTRUCTION}")
    print(
        "video: "
        f"{VIDEO.width}x{VIDEO.height} @ {VIDEO.fps:.2f}fps, "
        f"{VIDEO.duration_seconds:.2f}s, {VIDEO.frame_count} frames, "
        f"audio={'present' if VIDEO.has_audio else 'absent'}"
    )
    print(f"playbook chars: {summary['standard']['playbook_chars']}")
    print(f"developer chars: {summary['standard']['developer_chars']}")
    print(f"user chars: {summary['standard']['user_chars']}")
    print(f"payload chars: {summary['standard']['payload_chars']}")
    print(f"schema chars: {summary['standard']['schema_chars']}")
    print(f"input token estimate (chars/4): {summary['standard']['input_token_estimate_chars4']}")
    print(f"expected output tokens: {EXPECTED_OUTPUT_TOKENS}")
    print(f"max_completion_tokens: {OUTPUT_CAP}")
    for mode in ("standard", "contributor"):
        data = summary[mode]
        print(
            f"{mode}: model={data['model']} request_id={data['request_id']} "
            f"expected=${data['expected_cost_usd']:.6f} cap=${data['cap_cost_usd']:.6f} "
            f"request={data['request_path']}"
        )
    print("No network request was made. No EDL, SAM, Muse Image or render was invoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
