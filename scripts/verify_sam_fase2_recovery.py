"""Verify Fase 2 recovery on the already-paid LIVE-CALL 009 response.

Reads the stored completed response with GETs only (never billed), re-parses
its output text through the provider's synthetic-event path, and writes the
real SAM masks for the Facebook clip. No POST, no upload, no ledger slot.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers"):
    sys.path.insert(0, str(ROOT / _p))

RESPONSE_ID = "resp_6ae932f574e188479226482b"
SOURCE = ROOT / "storage" / "uploads" / "cd9616b3c69a4d97b7a0a373572e340e" / "source.mp4"
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
    load_env(ROOT / ".env")
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        print("Refusing: MODEL_API_KEY is missing. No request attempted.")
        return 2

    from clipforge_contracts import sha256_file
    from clipforge_providers import SamSegmentationProvider
    from clipforge_providers.sam import _output_text

    provider = SamSegmentationProvider(api_key)
    body = provider._retrieve_response(RESPONSE_ID)
    print("retrieved status:", body.get("status"))
    text = _output_text(body)
    print("output_text chars:", len(text))
    if body.get("status") != "completed" or not text:
        print("Stored response is not completed; nothing to recover.")
        return 1

    parsed = asyncio.run(provider._parse_retrieved(text, RESPONSE_ID))
    print("parser outcome:", parsed.outcome.status, "| records:", len(parsed.records))
    result = provider._convert(
        parsed,
        job_id="live-call-009-recovered",
        source_video_id="live-call-009-recovered",
        output_dir=OUT_DIR,
        width=360,
        height=640,
        frame_count=177,
        fps=30.0,
        source_sha256=sha256_file(SOURCE),
        source_path=SOURCE,
    )
    for subject in result.subjects:
        print(
            f"subject {subject.object_id}: frames {subject.frames_detected} "
            f"first={subject.first_frame} last={subject.last_frame}"
        )
    print("manifest:", result.mask_manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
