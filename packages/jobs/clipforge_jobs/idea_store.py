"""Filesystem store for idea-to-video jobs.

Deliberately separate from the edit `JobStore` while the P0 project workspace
is still landing: idea jobs have their own record, approval ledger and render
versions, so this module can ship without touching the editing pipeline.

Layout under the storage root:
  ideas/<idea_id>/idea.json
  ideas/<idea_id>/assets/<asset_id>.png
  ideas/<idea_id>/renders/v<N>/out.mp4
  ideas/<idea_id>/renders/v<N>/frames/frame_00000.png
  ideas/<idea_id>/progress.json          (worker sidecar, read by the API)
  ideas/<idea_id>/.claim                 (cross-process worker lock)

Writes are atomic (temp file + os.replace) and ids are validated before any
path is built, so a user-supplied string cannot escape the storage root.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from clipforge_contracts.idea import IdeaJobRecord, IdeaProgress, utc_now

IDEA_ID_RE = re.compile(r"^idea_[a-z0-9]{12}$")
ASSET_ID_RE = re.compile(r"^asset_[a-z0-9_]{1,40}$")
CLAIM_TTL_SECONDS = 30 * 60


class IdeaNotFoundError(LookupError):
    pass


def new_idea_id() -> str:
    return "idea_" + uuid.uuid4().hex[:12]


def _validate_idea_id(idea_id: str) -> str:
    if not IDEA_ID_RE.match(idea_id or ""):
        raise IdeaNotFoundError(f"Invalid idea id {idea_id!r}.")
    return idea_id


def _validate_asset_id(asset_id: str) -> str:
    if not ASSET_ID_RE.match(asset_id or ""):
        raise IdeaNotFoundError(f"Invalid asset id {asset_id!r}.")
    return asset_id


class IdeaStore:
    def __init__(self, storage_root: str | Path) -> None:
        self.root = Path(storage_root)
        self.base = self.root / "ideas"

    # ---------------------------------------------------------------- paths
    def idea_dir(self, idea_id: str) -> Path:
        return self.base / _validate_idea_id(idea_id)

    def assets_dir(self, idea_id: str) -> Path:
        return self.idea_dir(idea_id) / "assets"

    def asset_path(self, idea_id: str, asset_id: str) -> Path:
        return self.assets_dir(idea_id) / f"{_validate_asset_id(asset_id)}.png"

    def tmp_dir(self, idea_id: str) -> Path:
        return self.idea_dir(idea_id) / "tmp"

    def render_dir(self, idea_id: str, version: int) -> Path:
        if version < 1:
            raise ValueError("Render version must be >= 1.")
        return self.idea_dir(idea_id) / "renders" / f"v{version}"

    def rejected_dir(self, idea_id: str, version: int) -> Path:
        return self.idea_dir(idea_id) / "renders" / f"v{version}" / "rejected"

    def progress_path(self, idea_id: str) -> Path:
        return self.idea_dir(idea_id) / "progress.json"

    def claim_path(self, idea_id: str) -> Path:
        return self.idea_dir(idea_id) / ".claim"

    # ---------------------------------------------------------------- write
    def _write_record(self, record: IdeaJobRecord) -> None:
        directory = self.idea_dir(record.idea_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "idea.json"
        tmp = directory / f".idea-{uuid.uuid4().hex}.tmp"
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def create(self, record: IdeaJobRecord) -> IdeaJobRecord:
        directory = self.idea_dir(record.idea_id)
        if (directory / "idea.json").exists():
            raise FileExistsError(f"Idea {record.idea_id} already exists.")
        self._write_record(record)
        return record

    def save(self, record: IdeaJobRecord) -> IdeaJobRecord:
        record.updated_at = utc_now()
        self._write_record(record)
        return record

    def transition(
        self,
        record: IdeaJobRecord,
        *,
        status=None,
        stage: str | None = None,
        note: str | None = None,
    ) -> IdeaJobRecord:
        """Apply a status/stage change and append it to the job history."""
        from clipforge_contracts.idea import IdeaStateEntry

        if status is not None:
            record.status = status
        if stage is not None:
            record.stage = stage
        record.history.append(IdeaStateEntry(status=record.status, stage=record.stage, note=note))
        return self.save(record)

    # ----------------------------------------------------------------- read
    def get(self, idea_id: str) -> IdeaJobRecord:
        path = self.idea_dir(idea_id) / "idea.json"
        if not path.is_file():
            raise IdeaNotFoundError(f"Idea {idea_id} was not found.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IdeaNotFoundError(f"Idea {idea_id} could not be read.") from exc
        return IdeaJobRecord.model_validate(raw)

    def list(self, limit: int = 30) -> list[IdeaJobRecord]:
        records: list[IdeaJobRecord] = []
        if not self.base.is_dir():
            return records
        for directory in self.base.iterdir():
            if not directory.is_dir() or not IDEA_ID_RE.match(directory.name):
                continue
            try:
                records.append(self.get(directory.name))
            except (IdeaNotFoundError, ValueError):
                # A corrupt or partially written record must not break the list.
                continue
        records.sort(key=lambda r: r.updated_at, reverse=True)
        return records[: max(1, limit)]

    def queued(self) -> list[IdeaJobRecord]:
        from clipforge_contracts.idea import IdeaStatus

        records = [r for r in self.list(limit=200) if r.status == IdeaStatus.QUEUED]
        records.sort(key=lambda r: r.created_at)
        return records

    # ---------------------------------------------------------------- claim
    def claim(self, idea_id: str) -> bool:
        """Atomically claim one idea for this worker process.

        A stale claim (crashed worker) is reclaimed after CLAIM_TTL_SECONDS.
        """
        path = self.claim_path(idea_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - path.stat().st_mtime
                except OSError:
                    age = 0
                if attempt == 0 and age > CLAIM_TTL_SECONDS:
                    path.unlink(missing_ok=True)
                    continue
                return False
            except OSError:
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()} {time.time():.0f}")
            return True
        return False

    def release(self, idea_id: str) -> None:
        self.claim_path(idea_id).unlink(missing_ok=True)

    def is_claimed(self, idea_id: str) -> bool:
        return self.claim_path(idea_id).exists()

    # ------------------------------------------------------------- progress
    def write_progress(self, idea_id: str, progress: IdeaProgress) -> None:
        path = self.progress_path(idea_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(progress.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)

    def read_progress(self, idea_id: str) -> IdeaProgress | None:
        path = self.progress_path(idea_id)
        if not path.is_file():
            return None
        try:
            return IdeaProgress.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def clear_progress(self, idea_id: str) -> None:
        self.progress_path(idea_id).unlink(missing_ok=True)

    # --------------------------------------------------------------- cancel
    def cancel_path(self, idea_id: str) -> Path:
        return self.idea_dir(idea_id) / "cancel.requested"

    def request_cancel(self, idea_id: str) -> None:
        path = self.cancel_path(idea_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(utc_now().isoformat(), encoding="utf-8")

    def cancel_requested(self, idea_id: str) -> bool:
        return self.cancel_path(idea_id).exists()

    def clear_cancel(self, idea_id: str) -> None:
        self.cancel_path(idea_id).unlink(missing_ok=True)
