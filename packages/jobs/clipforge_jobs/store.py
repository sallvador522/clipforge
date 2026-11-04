"""File-based job store with atomic writes and cross-process claiming.

Layout under the storage root:
  uploads/<job_id>/source.<ext>
  jobs/<job_id>/job.json
  jobs/<job_id>/masks/...

No database and no extra dependencies. Writes go to a temp file in the same
directory followed by os.replace, so a reader never sees a partial record.
Claiming uses an O_CREAT|O_EXCL lock file, which is atomic across processes:
exactly one worker can claim a job.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from clipforge_jobs.models import JobRecord, JobStateEntry, JobStatus, utc_now

# User/API transitions only. Worker stage updates are recorded by update().
ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.QUEUED},
    JobStatus.COMPLETED: {JobStatus.QUEUED},
    JobStatus.AWAITING_APPROVAL: {JobStatus.QUEUED, JobStatus.REJECTED},
    JobStatus.AWAITING_CLARIFICATION: {JobStatus.QUEUED, JobStatus.REJECTED},
    JobStatus.AWAITING_CONSENT: {JobStatus.QUEUED},
}


class JobNotFoundError(LookupError):
    pass


class JobTransitionError(RuntimeError):
    def __init__(self, code: str, message: str, *, current_status: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.current_status = current_status


class JobStore:
    def __init__(self, storage_root: str | Path) -> None:
        self.root = Path(storage_root)
        self.uploads_dir = self.root / "uploads"
        self.jobs_dir = self.root / "jobs"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()

    # -- paths -------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def record_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def source_path(self, record: JobRecord) -> Path:
        return self.root / record.source_relative_path

    # -- CRUD ---------------------------------------------------------------
    def create(self, record: JobRecord) -> JobRecord:
        self.job_dir(record.job_id).mkdir(parents=True, exist_ok=False)
        self.save(record)
        return record

    def save(self, record: JobRecord) -> None:
        record.updated_at = utc_now()
        path = self.record_path(record.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def get(self, job_id: str) -> JobRecord:
        path = self.record_path(job_id)
        if not path.is_file():
            raise JobNotFoundError(f"Job not found: {job_id}")
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_jobs(self) -> list[JobRecord]:
        records = []
        for path in sorted(self.jobs_dir.glob("*/job.json")):
            records.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    def list_ready_queued(self) -> list[JobRecord]:
        return [r for r in self.list_jobs() if r.status is JobStatus.QUEUED and r.ready]

    # -- state transitions ---------------------------------------------------
    @staticmethod
    def _append_state(
        record: JobRecord,
        *,
        from_status: JobStatus | str,
        from_stage: str,
        actor: str,
        note: str | None = None,
    ) -> None:
        from_value = str(getattr(from_status, "value", from_status))
        if record.status.value == from_value and record.stage == from_stage:
            return
        record.state_history.append(
            JobStateEntry(
                from_status=from_value,
                to_status=record.status.value,
                from_stage=from_stage,
                to_stage=record.stage,
                actor=actor,  # type: ignore[arg-type]
                note=note,
            )
        )

    def claim(self, job_id: str) -> JobRecord | None:
        """Atomically move a ready queued job to processing. Returns None if not claimable."""
        with self._thread_lock:
            record = self.get(job_id)
            if record.status is not JobStatus.QUEUED or not record.ready:
                return None
            lock_path = self.job_dir(job_id) / "claim.lock"
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return None  # another worker/process already claimed it
            with os.fdopen(fd, "w") as fh:
                fh.write(str(os.getpid()))
            before_status, before_stage = record.status, record.stage
            record.status = JobStatus.PROCESSING
            record.stage = "processing"
            record.attempts += 1
            self._append_state(
                record,
                from_status=before_status,
                from_stage=before_stage,
                actor="worker",
                note="claimed",
            )
            self.save(record)
            return record

    def release_claim(self, job_id: str) -> None:
        """Release the per-job claim lock after processing stops (including review wait)."""
        (self.job_dir(job_id) / "claim.lock").unlink(missing_ok=True)

    def update(self, job_id: str, **changes: object) -> JobRecord:
        with self._thread_lock:
            record = self.get(job_id)
            before_status, before_stage = record.status, record.stage
            for key, value in changes.items():
                setattr(record, key, value)
            self._append_state(
                record,
                from_status=before_status,
                from_stage=before_stage,
                actor="worker",
            )
            self.save(record)
            return record

    def transition(
        self,
        job_id: str,
        *,
        expected: JobStatus | set[JobStatus],
        status: JobStatus,
        stage: str,
        actor: str = "user",
        note: str | None = None,
        **changes: object,
    ) -> JobRecord:
        """Atomic, cross-process user transition with explicit validation."""
        expected_set = expected if isinstance(expected, set) else {expected}
        with self._thread_lock:
            lock_path = self.job_dir(job_id) / "transition.lock"
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                raise JobTransitionError(
                    "job_transition_locked",
                    "Another approval/clarification transition is in progress.",
                ) from exc
            try:
                record = self.get(job_id)
                if record.status not in expected_set:
                    raise JobTransitionError(
                        "job_state_conflict",
                        f"Job is {record.status.value}; expected {sorted(s.value for s in expected_set)}.",
                        current_status=record.status.value,
                    )
                if status not in ALLOWED_TRANSITIONS.get(record.status, set()):
                    raise JobTransitionError(
                        "invalid_job_transition",
                        f"Cannot move job from {record.status.value} to {status.value}.",
                        current_status=record.status.value,
                    )
                before_status, before_stage = record.status, record.stage
                record.status = status
                record.stage = stage
                for key, value in changes.items():
                    setattr(record, key, value)
                self._append_state(
                    record,
                    from_status=before_status,
                    from_stage=before_stage,
                    actor=actor,
                    note=note,
                )
                self.save(record)
                return record
            finally:
                os.close(fd)
                lock_path.unlink(missing_ok=True)
