"""Shared job state for ClipForge: used by both the FastAPI app and the persistent worker."""

from clipforge_jobs.models import (
    MAX_CLARIFICATIONS,
    JobError,
    JobRecord,
    JobResult,
    JobStateEntry,
    JobStatus,
    SourceInfo,
)
from clipforge_contracts import SubjectDetectionConsent
from clipforge_jobs.store import JobNotFoundError, JobStore, JobTransitionError
from clipforge_jobs.project_store import (
    AssetNotFoundError,
    ProjectNotFoundError,
    ProjectStore,
)

__all__ = [
    "AssetNotFoundError",
    "ProjectNotFoundError",
    "ProjectStore",
    "JobError",
    "JobNotFoundError",
    "JobRecord",
    "JobResult",
    "JobStateEntry",
    "JobStatus",
    "JobStore",
    "JobTransitionError",
    "MAX_CLARIFICATIONS",
    "SourceInfo",
    "SubjectDetectionConsent",
]
