"""Prepare the first real SAM 3.1 validation without sending anything.

This script is deliberately offline:

- it probes the real source clip;
- creates and validates a temporary video-only copy locally;
- builds the exact Responses request payload;
- builds the exact Files API multipart body in memory and verifies field order;
- inspects provider/ledger authorization state;
- writes a preparation report and request preview.

It never calls `segment`, `httpx.post`, `httpx.get` or any Meta endpoint.
No file is uploaded and no ledger slot is reserved.

Usage (from the repository root):
    .\\.venv\\Scripts\\python.exe scripts\\prepare_sam_live_validation.py
    .\\.venv\\Scripts\\python.exe scripts\\prepare_sam_live_validation.py --source "C:\\path\\clip.mp4"
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
for path in (
    "packages/contracts",
    "packages/providers",
    "packages/jobs",
    "packages/director",
    "apps/worker",
    "apps/api",
):
    sys.path.insert(0, str(ROOT / path))

from clipforge_director import LiveCallAuthorization, LiveCallBudget  # noqa: E402
from clipforge_providers.sam import (  # noqa: E402
    FILE_EXPIRY_SECONDS,
    SamSegmentationProvider,
)

DEFAULT_SOURCE = Path(r"C:\Users\New User\Videos\Video\Facebook.mp4")
DEFAULT_STORAGE = ROOT / "storage"
DEFAULT_OUTPUT = DEFAULT_STORAGE / "sam_live_validation"
EXPECTED_FILES_FIELDS = [
    "purpose",
    "expires_after[anchor]",
    "expires_after[seconds]",
    "file",
]


class PreparationError(RuntimeError):
    pass


def load_env(path: Path) -> None:
    """Load .env without overriding the current process environment or printing secrets."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path, *, count_frames: bool = True) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    if count_frames:
        command.insert(3, "-count_frames")
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise PreparationError(f"ffprobe failed: {result.stderr.strip()[-300:]}")
    return json.loads(result.stdout)


def video_stream(probe_data: dict[str, Any]) -> dict[str, Any]:
    stream = next(
        (item for item in probe_data.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    if stream is None:
        raise PreparationError("The source has no video stream.")
    return stream


def fps(stream: dict[str, Any]) -> float:
    numerator, denominator = str(stream.get("avg_frame_rate", "0/1")).split("/")
    return float(numerator) / float(denominator) if float(denominator) else 0.0


def frame_count(stream: dict[str, Any]) -> int:
    raw = stream.get("nb_read_frames") or stream.get("nb_frames")
    return int(raw) if raw is not None and str(raw).isdigit() else -1


def compact_probe(data: dict[str, Any]) -> dict[str, Any]:
    stream = video_stream(data)
    audio_streams = [item for item in data.get("streams", []) if item.get("codec_type") == "audio"]
    stream_fps = fps(stream)
    stream_frames = frame_count(stream)
    return {
        "format": data.get("format", {}).get("format_name"),
        "duration_seconds": float(data.get("format", {}).get("duration", 0) or 0),
        "video_duration_seconds": (
            round(stream_frames / stream_fps, 6) if stream_fps > 0 and stream_frames > 0 else None
        ),
        "size_bytes": int(data.get("format", {}).get("size", 0) or 0),
        "video": {
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "fps": stream_fps,
            "frame_count": stream_frames,
        },
        "audio_streams": len(audio_streams),
    }


def multipart_names(body: bytes) -> list[str]:
    # Match the ``name=`` parameter, not the ``filename=`` parameter.
    return re.findall(
        r'(?:^|;\s*)name="([^"]+)"',
        body.decode("latin-1"),
        flags=re.MULTILINE,
    )


def extract_source_frames(source: Path, output_dir: Path, video_duration: float) -> list[str]:
    frames_dir = output_dir / "source_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frames_dir.glob("frame_*.png"):
        old_frame.unlink(missing_ok=True)
    times = [0.0, round(video_duration / 2, 2), max(0.0, round(video_duration - 0.2, 2))]
    paths: list[str] = []
    for index, timestamp in enumerate(times):
        path = frames_dir / f"frame_{index}_{timestamp:.2f}s.png"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(source),
                "-frames:v", "1", "-vf", "scale=640:-1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and path.is_file():
            paths.append(str(path))
    return paths


def build_multipart_preview(normalized: Path, provider: SamSegmentationProvider) -> dict[str, Any]:
    data = {
        "purpose": "user_data",
        "expires_after[anchor]": "created_at",
        "expires_after[seconds]": str(FILE_EXPIRY_SECONDS),
    }
    with normalized.open("rb") as handle:
        request = httpx.Request(
            "POST",
            f"{provider._base_url}/files",
            headers={"Authorization": "Bearer DRY-RUN-NOT-SENT"},
            data=data,
            files={"file": (normalized.name, handle, "video/mp4")},
        )
        body = request.read()
    names = multipart_names(body)
    if names != EXPECTED_FILES_FIELDS:
        raise PreparationError(
            f"Multipart field order is {names!r}, expected {EXPECTED_FILES_FIELDS!r}; "
            "the file part must be last."
        )
    text = body.decode("latin-1")
    if "user_data" not in text or "created_at" not in text or "3600" not in text:
        raise PreparationError("Multipart body does not contain the expected expiry values.")
    if 'Content-Type: video/mp4' not in text:
        raise PreparationError("Multipart body does not declare the video file as video/mp4.")
    return {
        "endpoint": f"{provider._base_url}/files",
        "content_type": request.headers.get("content-type"),
        "field_order": names,
        "file_part_last": names[-1] == "file",
        "fields": {
            "purpose": "user_data",
            "expires_after[anchor]": "created_at",
            "expires_after[seconds]": str(FILE_EXPIRY_SECONDS),
            "file": {"filename": normalized.name, "content_type": "video/mp4"},
        },
        "body_bytes_checked_locally": len(body),
        "uploaded": False,
    }


def inspect_provider_code() -> dict[str, Any]:
    segment_source = inspect.getsource(SamSegmentationProvider.segment)
    stream_source = inspect.getsource(SamSegmentationProvider._http_event_stream)
    payload_source = inspect.getsource(SamSegmentationProvider._request_payload)
    upload_source = inspect.getsource(SamSegmentationProvider._upload)
    delete_source = inspect.getsource(SamSegmentationProvider._delete)
    collect_source = inspect.getsource(SamSegmentationProvider._collect)
    convert_source = inspect.getsource(SamSegmentationProvider._convert)
    return {
        "authorization_reserve_count": segment_source.count("authorization.reserve()"),
        "cleanup_in_finally": "finally:" in segment_source and "_delete(file_id)" in segment_source,
        "expiry_seconds_constant": FILE_EXPIRY_SECONDS,
        "stream_flag_in_payload": '"stream": True' in payload_source,
        "sse_stream_used": "client.stream" in stream_source,
        "official_parser_used": "parse_responses_stream" in collect_source
        and "final_result" in collect_source,
        "incomplete_outcome_rejected": 'parsed.outcome.status != "completed"' in convert_source,
        "upload_uses_files": "files={" in upload_source,
        "delete_endpoint_present": "/files/" in delete_source,
        "automatic_retry_loops": bool(re.search(r"for\s+attempt|range\([^\n]*retry|tenacity", segment_source)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prompt", default="person")
    parser.add_argument("--model", default="sam-3.1")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise PreparationError(f"Source video not found: {source}")
    if source.stat().st_size == 0:
        raise PreparationError("Source video is empty.")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_probe = probe(source)
    source_info = compact_probe(source_probe)
    stream = video_stream(source_probe)
    width = int(stream["width"])
    height = int(stream["height"])
    source_fps = fps(stream)
    source_frames = frame_count(stream)
    if source_frames <= 0:
        raise PreparationError("Could not determine source frame count.")

    original_hash_before = sha256(source)
    provider = SamSegmentationProvider(
        "dry-run-only",
        model=args.model,
        prompt=args.prompt,
    )
    normalized = output_dir / f"{source.stem}_sam_input.mp4"
    provider._prepare_video_only(
        source,
        normalized,
        width=width,
        height=height,
        frame_count=source_frames,
        fps=source_fps,
    )
    original_hash_after = sha256(source)
    if original_hash_after != original_hash_before:
        raise PreparationError("The original source changed during preparation.")

    normalized_probe = compact_probe(probe(normalized))
    normalized_stream = video_stream(probe(normalized))
    if normalized_probe["audio_streams"] != 0:
        raise PreparationError("The prepared SAM input still contains audio.")
    if normalized_probe["video"]["width"] != width or normalized_probe["video"]["height"] != height:
        raise PreparationError("The prepared SAM input changed dimensions.")
    if normalized_probe["video"]["frame_count"] != source_frames:
        raise PreparationError("The prepared SAM input changed frame count.")
    if abs(normalized_probe["video"]["fps"] - source_fps) > 0.01:
        raise PreparationError("The prepared SAM input changed FPS.")
    if normalized_probe["video"]["codec"] != "h264":
        raise PreparationError(
            "The prepared SAM input is not H.264; the current normalization contract expects H.264."
        )

    payload = provider._request_payload("file-DRYRUN", args.prompt)
    if payload["model"] != "sam-3.1":
        raise PreparationError("Request model is not sam-3.1.")
    content = payload["input"][0]["content"]
    if content[0] != {"type": "input_text", "text": "person"}:
        raise PreparationError("Request prompt is not the short noun phrase 'person'.")
    if content[1] != {"type": "input_video", "file_id": "file-DRYRUN"}:
        raise PreparationError("Request does not use input_video by file_id.")
    if payload["stream"] is not True:
        raise PreparationError("Request streaming is not enabled.")
    if payload["metadata"] != {"mask_encoding": "one_bit"}:
        raise PreparationError("Request mask encoding is not one_bit.")

    multipart = build_multipart_preview(normalized, provider)
    code_checks = inspect_provider_code()
    if code_checks["authorization_reserve_count"] != 1:
        raise PreparationError("Provider must reserve authorization exactly once.")
    if not code_checks["cleanup_in_finally"]:
        raise PreparationError("Provider cleanup is not in a finally block.")
    if code_checks["automatic_retry_loops"]:
        raise PreparationError("Provider contains an automatic retry loop.")

    storage_root = args.storage_root.resolve()
    ledger_path = storage_root / "live-call-ledger.json"
    lock_path = storage_root / "live-call-ledger.lock"
    budget = LiveCallBudget(storage_root)
    ledger_used = {function: budget.used(function) for function in budget.limits}
    ledger = {
        "path": str(ledger_path),
        "exists": ledger_path.is_file(),
        "lock_exists": lock_path.exists(),
        "limits": budget.limits,
        "used": ledger_used,
        "segmentation_remaining": budget.limits["segmentation"]
        - ledger_used.get("segmentation", 0),
    }
    if ledger["lock_exists"]:
        raise PreparationError(
            f"Ledger lock exists at {lock_path}; do not run until it is manually verified and removed."
        )
    if ledger["segmentation_remaining"] < 1:
        raise PreparationError("No segmentation ledger slot remains; a new approved phase is required.")

    authorization = LiveCallAuthorization(budget, "segmentation")
    if authorization.reserved:
        raise PreparationError("Authorization was unexpectedly already reserved.")
    if authorization.function != "segmentation":
        raise PreparationError("Authorization is not scoped to segmentation.")

    env = {
        "CLIPFORGE_AI_MODE": os.environ.get("CLIPFORGE_AI_MODE", "mock"),
        "CLIPFORGE_TRANSCRIBE_MODE": os.environ.get("CLIPFORGE_TRANSCRIBE_MODE", "mock"),
        "CLIPFORGE_DIRECTOR_MODE": os.environ.get("CLIPFORGE_DIRECTOR_MODE", "mock"),
        "CLIPFORGE_SEGMENTATION_MODE": os.environ.get("CLIPFORGE_SEGMENTATION_MODE", "mock"),
        "CLIPFORGE_DEV_ALLOW_LIVE": os.environ.get("CLIPFORGE_DEV_ALLOW_LIVE", "0"),
        "MODEL_API_KEY_present": bool(os.environ.get("MODEL_API_KEY", "").strip()),
        "MODEL_API_KEY_value_printed": False,
    }
    warnings: list[str] = []
    if width < 1280 or height < 720:
        warnings.append(
            f"Source is {width}x{height}; this is below the 720p product target. "
            "It is accepted only because the user explicitly selected this Facebook clip."
        )
    if not (9.0 <= source_info["duration_seconds"] <= 11.0):
        warnings.append(
            f"Source duration is {source_info['duration_seconds']:.3f}s, not approximately 10s."
        )
    if abs(source_fps - 30.0) > 0.01:
        warnings.append(f"Source FPS is {source_fps}, not 30 FPS.")
    if source_info["video_duration_seconds"] is not None and abs(
        source_info["video_duration_seconds"] - source_info["duration_seconds"]
    ) > 0.05:
        warnings.append(
            "Container duration "
            f"{source_info['duration_seconds']:.3f}s differs from video-track duration "
            f"{source_info['video_duration_seconds']:.3f}s; SAM receives the video track."
        )
    if not env["MODEL_API_KEY_present"]:
        warnings.append("MODEL_API_KEY is not present; the live execution is blocked.")
    if env["CLIPFORGE_SEGMENTATION_MODE"] != "live":
        warnings.append(
            "CLIPFORGE_SEGMENTATION_MODE is not live. The prepared execution command must override it."
        )
    if env["CLIPFORGE_DEV_ALLOW_LIVE"] != "1":
        warnings.append(
            "CLIPFORGE_DEV_ALLOW_LIVE is not 1. The dev launchers would force segmentation back to mock."
        )

    source_frames_paths = extract_source_frames(
        source,
        output_dir,
        source_info["video_duration_seconds"] or source_info["duration_seconds"],
    )
    masks_dir = output_dir / "masks"
    planned_outputs = {
        "job_mask_root": str(masks_dir),
        "union_manifest": str(masks_dir / "manifest.json"),
        "per_object_manifests": str(masks_dir / "objects" / "object_<sam_object_id>" / "manifest.json"),
        "previews": str(masks_dir / "previews" / "object_<sam_object_id>.png"),
        "selected_union": str(masks_dir / "selected" / "manifest.json"),
        "rendered_mp4": str(output_dir / "sam_selected_blur.mp4"),
        "masks_created": False,
    }
    execution_command = {
        "prepared": True,
        "executed": False,
        "shell": "PowerShell",
        "steps": [
            '$env:CLIPFORGE_AI_MODE="mock"',
            '$env:CLIPFORGE_TRANSCRIBE_MODE="mock"',
            '$env:CLIPFORGE_DIRECTOR_MODE="mock"',
            '$env:CLIPFORGE_SEGMENTATION_MODE="live"',
            '$env:CLIPFORGE_DEV_ALLOW_LIVE="1"',
            r".\.venv\Scripts\python.exe scripts\dev_api.py  # terminal 1, port 8001",
            r".\.venv\Scripts\python.exe scripts\dev_worker.py  # terminal 2",
            'cd apps/web; $env:NEXT_PUBLIC_API_URL="http://localhost:8001"; npm run dev  # terminal 3',
        ],
        "ui_steps": [
            "Upload Facebook.mp4.",
            "Use the typed instruction: 'Desfoca o fundo e mantém-me nítido.'",
            "Confirm and wait for detection; the job must stop at awaiting_approval.",
            "Inspect both subject previews and select the people to keep sharp.",
            "Approve and render; verify the downloaded MP4.",
        ],
        "note": "No command above was executed by this preparation script.",
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline preparation; no upload, no SAM request, no ledger reservation",
        "source": str(source),
        "source_sha256": original_hash_before,
        "source_unchanged": original_hash_after == original_hash_before,
        "source_probe": source_info,
        "video_only_copy": {
            "path": str(normalized),
            "probe": normalized_probe,
            "has_audio": normalized_probe["audio_streams"] > 0,
            "sha256": sha256(normalized),
        },
        "request": {
            "endpoint": f"{provider._base_url}/responses",
            "payload": payload,
            "files_api": multipart,
        },
        "code_checks": code_checks,
        "ledger": ledger,
        "authorization": {
            "function": authorization.function,
            "reserved_before_execution": authorization.reserved,
        },
        "environment": env,
        "planned_outputs": planned_outputs,
        "source_frames": source_frames_paths,
        "execution_command": execution_command,
        "warnings": warnings,
        "manual_visual_review": {
            "required": True,
            "observed_from_sample_frames": [
                "Two men are visible together in the frame for most of the clip.",
                "Left person: dark sweater, arms crossed; right person: older man in a suit.",
                "Burned-in caption text is present at the top and over the lower frame.",
                "No full occlusion is visible in the sampled frames; identity-after-occlusion is not testable with this clip.",
            ],
        },
    }

    (output_dir / "request_preview.json").write_text(
        json.dumps(
            {
                "model": payload["model"],
                "endpoint": f"{provider._base_url}/responses",
                "payload": payload,
                "files_api_fields": multipart["fields"],
                "multipart_field_order": multipart["field_order"],
                "file_part_last": multipart["file_part_last"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "preparation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    print("SAM live validation preparation — OFFLINE ONLY")
    print(f"source: {source}")
    print(
        f"source probe: {width}x{height}, {source_fps:g} FPS, "
        f"{source_frames} frames, {source_info['duration_seconds']:.3f}s, "
        f"audio_streams={source_info['audio_streams']}"
    )
    print(f"video-only copy: {normalized}")
    print(f"copy probe: {normalized_probe['video']['width']}x{normalized_probe['video']['height']}, "
          f"{normalized_probe['video']['fps']:g} FPS, {normalized_probe['video']['frame_count']} frames, "
          f"audio_streams={normalized_probe['audio_streams']}")
    print(f"request: {provider._base_url}/responses model=sam-3.1 prompt=person stream=true mask_encoding=one_bit")
    print(f"multipart fields: {multipart['field_order']} (file last={multipart['file_part_last']})")
    print(f"ledger: limits={ledger['limits']} used={ledger['used']} "
          f"segmentation_remaining={ledger['segmentation_remaining']}")
    print(f"authorization: segmentation, reserved={authorization.reserved}")
    print(f"report: {output_dir / 'preparation_report.json'}")
    print(f"request preview: {output_dir / 'request_preview.json'}")
    print("No upload, SAM request, or ledger reservation was made.")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreparationError as exc:
        print(f"PREPARATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
