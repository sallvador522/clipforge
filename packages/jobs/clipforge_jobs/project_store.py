"""Filesystem project store (P0).

Layout under the storage root:
  projects/<project_id>/project.json
  projects/<project_id>/assets/<asset_id>/asset.json
  projects/<project_id>/assets/<asset_id>/<stored file> (+ sanitized.svg for SVG)

Same atomic-write discipline as JobStore: temp file + os.replace.
IDs are generated server-side; every lookup validates the id pattern so a
user-supplied string can never escape the project directory.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from pathlib import Path

from clipforge_contracts.project import ProjectMode, ProjectRecord


_PROJECT_ID_RE = re.compile(r"^prj_[a-z0-9]{12}$")
_ASSET_ID_RE = re.compile(r"^ast_[a-z0-9]{12}$")


class ProjectNotFoundError(LookupError):
    pass


class AssetNotFoundError(LookupError):
    pass


def _new_project_id() -> str:
    return "prj_" + uuid.uuid4().hex[:12]


def _new_asset_id() -> str:
    return "ast_" + uuid.uuid4().hex[:12]


def _check_project_id(project_id: str) -> None:
    if not _PROJECT_ID_RE.match(project_id or ""):
        raise ProjectNotFoundError(f"Project not found: {project_id}")


def _check_asset_id(asset_id: str) -> None:
    if not _ASSET_ID_RE.match(asset_id or ""):
        raise AssetNotFoundError(f"Asset not found: {asset_id}")


class ProjectStore:
    def __init__(self, storage_root: str | Path) -> None:
        self.root = Path(storage_root)
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()

    # -- paths --------------------------------------------------------------
    def project_dir(self, project_id: str) -> Path:
        _check_project_id(project_id)
        return self.projects_dir / project_id

    def project_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def assets_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "assets"

    def asset_dir(self, project_id: str, asset_id: str) -> Path:
        _check_project_id(project_id)
        _check_asset_id(asset_id)
        return self.assets_dir(project_id) / asset_id

    # -- projects -------------------------------------------------------------
    def create_project(self, title: str, mode: ProjectMode = ProjectMode.EDIT) -> ProjectRecord:
        clean = (title or "").strip() or "Untitled project"
        record = ProjectRecord(project_id=_new_project_id(), title=clean[:80], mode=mode)
        with self._thread_lock:
            self.project_dir(record.project_id).mkdir(parents=True, exist_ok=False)
            self.assets_dir(record.project_id).mkdir(parents=True, exist_ok=True)
            self._write_project(record)
        return record

    def get_project(self, project_id: str) -> ProjectRecord:
        path = self.project_path(project_id)
        if not path.is_file():
            raise ProjectNotFoundError(f"Project not found: {project_id}")
        return ProjectRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_projects(self) -> list[ProjectRecord]:
        records: list[ProjectRecord] = []
        if not self.projects_dir.is_dir():
            return records
        for path in sorted(self.projects_dir.glob("*/project.json")):
            try:
                records.append(ProjectRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return records

    def rename_project(self, project_id: str, title: str) -> ProjectRecord:
        clean = (title or "").strip()
        if not clean:
            raise ValueError("Project title cannot be empty.")
        with self._thread_lock:
            record = self.get_project(project_id)
            record.title = clean[:80]
            self._write_project(record)
            return record

    def _write_project(self, record: ProjectRecord) -> None:
        from clipforge_jobs.models import utc_now

        record.updated_at = utc_now()
        path = self.project_path(record.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    # -- assets -----------------------------------------------------------------
    def write_asset_record(self, project_id: str, asset_id: str, payload: str) -> None:
        """Atomically persist the asset.json sidecar (payload is pre-validated JSON)."""
        with self._thread_lock:
            directory = self.asset_dir(project_id, asset_id)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "asset.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)

    def delete_asset(self, project_id: str, asset_id: str) -> None:
        with self._thread_lock:
            directory = self.asset_dir(project_id, asset_id)
            if not (directory / "asset.json").is_file():
                # Distinguish unknown ids from cross-project probes without leaking layout.
                raise AssetNotFoundError(f"Asset not found: {asset_id}")
            shutil.rmtree(directory, ignore_errors=False)
