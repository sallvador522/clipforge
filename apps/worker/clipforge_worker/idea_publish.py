"""Publish verified idea outputs as project assets (Fase C supporting module).

When a render verifies, the plates, a generated subtitle file and the final
MP4 become first-class project assets so they show up in Recursos and can be
previewed, downloaded and reused. Nothing here calls AI or the network: files
are copied locally and validated with the same probes as uploads, except the
MVP media caps (a verified 20 s / 720x1280 idea render legitimately exceeds
the 10 s / 720p upload limits, so generated outputs are probed for metadata
only and recorded with `provenance="generated"`).

Idempotent per idea: a `published.json` marker lists the created asset ids
and a second run is a no-op. Publishing never fails the job — the verified
MP4 is already delivered; a publish problem is logged and skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

from clipforge_contracts.idea import IdeaState
from clipforge_contracts.project import (
    AssetKind,
    AssetProvenance,
    AssetRecord,
    utc_now,
)
from clipforge_contracts.storyboard import Storyboard
from clipforge_jobs.idea_store import IdeaStore
from clipforge_jobs.project_store import ProjectNotFoundError, ProjectStore

logger = logging.getLogger("clipforge.idea_publish")


def _new_asset_id() -> str:
    # Matches AssetRecord.asset_id (^ast_[a-z0-9]{12}$) and ProjectStore checks.
    return "ast_" + uuid.uuid4().hex[:12]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ms_to_srt_timestamp(total_ms: int) -> str:
    total_ms = max(0, total_ms)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_idea_srt(board: Storyboard) -> bytes:
    """One cue per scene: on-screen text with exact scene timings."""
    offset = 0
    cues: list[str] = []
    for index, scene in enumerate(board.scenes, start=1):
        start = _ms_to_srt_timestamp(offset)
        end = _ms_to_srt_timestamp(offset + scene.duration_ms)
        text = " ".join(line.strip() for line in scene.on_screen_text if line.strip())
        cues.append(f"{index}\n{start} --> {end}\n{text or '(sem texto)'}\n")
        offset += scene.duration_ms
    return ("\n".join(cues) + "\n").encode("utf-8")


def probe_video_unrestricted(path: Path) -> dict:
    """ffprobe metadata without the MVP upload caps (generated files only)."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe could not read {path.name}.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid metadata for {path.name}.") from exc
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"{path.name} has no video stream.")
    try:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    if width <= 0 or height <= 0:
        raise ValueError(f"{path.name} has invalid video dimensions.")
    try:
        duration = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise ValueError(f"{path.name} has no measurable duration.")
    fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0"
    fps = 0.0
    if isinstance(fps_raw, str) and "/" in fps_raw:
        num, _, den = fps_raw.partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 0.0
    else:
        try:
            fps = float(fps_raw)
        except (TypeError, ValueError):
            fps = 0.0
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return {
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "fps": fps or None,
        "frame_count": int(round(duration * fps)) if fps > 0 else None,
        "has_audio": has_audio,
    }


def _store_generated_file(
    projects: ProjectStore,
    *,
    project_id: str,
    source: Path,
    original_name: str,
    kind: AssetKind,
    extra: dict,
) -> str:
    """Copy a generated file into the project library as a new asset."""
    from PIL import Image  # local import: Pillow is a worker dependency too

    suffix = Path(original_name).suffix.lower()
    asset_id = _new_asset_id()
    asset_dir = projects.asset_dir(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=False)
    stored_filename = f"original{suffix}"
    try:
        tmp = asset_dir / (stored_filename + ".tmp")
        tmp.write_bytes(source.read_bytes())
        os.replace(tmp, asset_dir / stored_filename)
        if kind == AssetKind.IMAGE:
            with Image.open(asset_dir / stored_filename) as img:
                img.load()
                extra = {**extra, "width": img.width, "height": img.height}
        record = AssetRecord(
            asset_id=asset_id,  # type: ignore[arg-type]
            project_id=project_id,  # type: ignore[arg-type]
            kind=kind,
            original_filename=original_name[:255],
            stored_filename=stored_filename,
            mime={
                ".png": "image/png",
                ".srt": "text/plain",
                ".mp4": "video/mp4",
            }.get(suffix, "application/octet-stream"),
            size_bytes=(asset_dir / stored_filename).stat().st_size,
            sha256=_sha256_file(asset_dir / stored_filename),
            provenance=AssetProvenance.GENERATED,
            created_at=utc_now(),
            **extra,
        )
        projects.write_asset_record(project_id, asset_id, record.model_dump_json(indent=2))
        return asset_id
    except Exception:
        import shutil

        shutil.rmtree(asset_dir, ignore_errors=True)
        raise


def publish_idea_outputs(
    storage_root: str | Path,
    *,
    idea_id: str,
    project_id: str | None,
    idea: IdeaState,
    board: Storyboard,
    mp4_path: Path,
) -> list[str]:
    """Register plates, subtitles and the verified MP4 as project assets.

    Returns the created asset ids (empty when there is no project to publish
    to, or when this idea was already published). Never raises: publishing is
    auxiliary to the delivered render.
    """
    store = IdeaStore(storage_root)
    projects = ProjectStore(storage_root)
    if not project_id:
        return []
    try:
        projects.get_project(project_id)
    except ProjectNotFoundError:
        logger.warning("idea_publish_no_project idea_id=%s", idea_id)
        return []
    marker = store.idea_dir(idea_id) / "published.json"
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(marker_data, dict) and marker_data.get("asset_ids"):
            return list(marker_data["asset_ids"])
    except (OSError, ValueError):
        pass

    created: list[str] = []
    try:
        for asset in idea.assets:
            if asset.status.value != "generated":
                continue
            source = store.asset_path(idea_id, asset.asset_id)
            if not source.is_file():
                continue
            created.append(
                _store_generated_file(
                    projects,
                    project_id=project_id,
                    source=source,
                    original_name=f"{asset.asset_id}.png",
                    kind=AssetKind.IMAGE,
                    extra={},
                )
            )
        srt_bytes = build_idea_srt(board)
        if srt_bytes.strip():
            srt_tmp = store.tmp_dir(idea_id) / "legendas.srt"
            srt_tmp.parent.mkdir(parents=True, exist_ok=True)
            srt_tmp.write_bytes(srt_bytes)
            lines = srt_bytes.decode("utf-8").count("\n")
            created.append(
                _store_generated_file(
                    projects,
                    project_id=project_id,
                    source=srt_tmp,
                    original_name=f"legendas-{idea_id}.srt",
                    kind=AssetKind.TEXT,
                    extra={
                        "text_lines": lines,
                        "cue_count": len(board.scenes),
                        "text_encoding": "utf-8",
                    },
                )
            )
        if mp4_path.is_file() and mp4_path.stat().st_size > 0:
            meta = probe_video_unrestricted(mp4_path)
            created.append(
                _store_generated_file(
                    projects,
                    project_id=project_id,
                    source=mp4_path,
                    original_name=f"{idea_id}.mp4",
                    kind=AssetKind.VIDEO,
                    extra={k: v for k, v in meta.items() if v is not None},
                )
            )
        marker.write_text(json.dumps({"asset_ids": created}), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - publishing must never fail the job
        logger.warning("idea_publish_failed idea_id=%s error=%s", idea_id, exc)
        return []
    logger.info("idea_published idea_id=%s assets=%d", idea_id, len(created))
    return created
