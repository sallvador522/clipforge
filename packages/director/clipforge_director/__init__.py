"""Professional Editing Director package (Milestone 6B-PREP)."""

from clipforge_director.evaluation import (
    CorrectionAttempt,
    ObjectiveChecks,
    OutputEvaluationReport,
    SamplePoint,
    evaluate_output,
)
from clipforge_director.mock import MockProfessionalEditingDirector, ProfessionalEditingDirector
from clipforge_director.spark import (
    DirectorAPIError,
    DirectorRateLimitedError,
    DirectorTimeoutError,
    DirectorUsage,
    DirectorValidationError,
    DirectorVideoMetadata,
    InvalidModelError,
    LiteMetaEditingDirectorProvider,
    MetaEditingDirectorProvider,
    MissingCredentialsError as SparkMissingCredentialsError,
    SparkDirectorError,
    build_developer_prompt,
    build_user_prompt,
    calculate_cost_usd,
    estimate_tokens,
)

__all__ = [
    "CorrectionAttempt",
    "DirectorAPIError",
    "DirectorRateLimitedError",
    "DirectorTimeoutError",
    "DirectorUsage",
    "DirectorValidationError",
    "DirectorVideoMetadata",
    "InvalidModelError",
    "LiteMetaEditingDirectorProvider",
    "MetaEditingDirectorProvider",
    "MockProfessionalEditingDirector",
    "ObjectiveChecks",
    "OutputEvaluationReport",
    "ProfessionalEditingDirector",
    "SamplePoint",
    "SparkDirectorError",
    "SparkMissingCredentialsError",
    "build_developer_prompt",
    "build_user_prompt",
    "calculate_cost_usd",
    "estimate_tokens",
    "evaluate_output",
]
