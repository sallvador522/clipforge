"""ProfessionalEditingPlan v2 — director output contract and v1 adapter.

v1 (`EditingPlan`) remains the execution contract used by the worker. v2 is the
director's richer plan: capability references, typed parameters, dependencies,
explanations, approval and verification. `to_execution_plan()` adapts a v2 plan
into v1 without weakening either contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge_contracts.capabilities import (
    CAPABILITY_BY_PARAM_TYPE,
    CapabilityStatus,
    BlurBackgroundParams,
    IsolateSubjectParams,
    PreserveAudioParams,
    RenderMp4Params,
    ReplaceBackgroundParams,
    VerifyOutputParams,
    get_capability,
)
from clipforge_contracts.director_stages import DirectorStage, can_transition


class DirectorPlanError(ValueError):
    pass


class PlanOutcome(str, Enum):
    PLAN_READY = "plan_ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    APPROVED = "approved"
    REJECTED = "rejected"


class OperationStatus(str, Enum):
    PROPOSED = "proposed"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


_OPERATION_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.PROPOSED: frozenset({OperationStatus.PENDING, OperationStatus.SKIPPED}),
    OperationStatus.PENDING: frozenset(
        {OperationStatus.RUNNING, OperationStatus.FAILED, OperationStatus.SKIPPED}
    ),
    OperationStatus.RUNNING: frozenset({OperationStatus.COMPLETED, OperationStatus.FAILED}),
    OperationStatus.COMPLETED: frozenset(),
    OperationStatus.FAILED: frozenset(),
    OperationStatus.SKIPPED: frozenset(),
}


class InvalidOperationTransition(ValueError):
    pass


def can_transition_operation(source: OperationStatus, target: OperationStatus) -> bool:
    return target in _OPERATION_TRANSITIONS[source]


def require_operation_transition(source: OperationStatus, target: OperationStatus) -> None:
    if not can_transition_operation(source, target):
        raise InvalidOperationTransition(f"Cannot move operation from {source.value} to {target.value}.")


class OutputAspect(str, Enum):
    SOURCE = "source"
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class SubjectStrategy(str, Enum):
    LARGEST_SUBJECT = "largest_subject"
    NAMED_SUBJECT = "named_subject"
    FOREGROUND = "foreground"


class SubjectSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: SubjectStrategy = SubjectStrategy.LARGEST_SUBJECT
    description: str = Field(min_length=1, max_length=200)
    is_ambiguous: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _ambiguous_requires_question(self) -> "SubjectSelection":
        if self.is_ambiguous and not self.clarification_question:
            raise ValueError("An ambiguous subject requires a clarification question.")
        return self


class OutputTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["mp4"] = "mp4"
    aspect_ratio: OutputAspect = OutputAspect.SOURCE
    resolution: Literal["source", "720p"] = "source"
    preserve_audio: bool = True


Params = Annotated[
    Union[
        IsolateSubjectParams,
        BlurBackgroundParams,
        ReplaceBackgroundParams,
        PreserveAudioParams,
        RenderMp4Params,
        VerifyOutputParams,
    ],
    Field(discriminator="type"),
]


class DirectorOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(pattern=r"^op_[a-z0-9_]{1,40}$")
    capability_id: str
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=300)
    params: Params
    dependencies: list[str] = Field(default_factory=list)
    status: OperationStatus = OperationStatus.PROPOSED
    expected_output: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _capability_matches(self) -> "DirectorOperation":
        capability = get_capability(self.capability_id)
        if capability is None:
            raise ValueError(f"Unknown capability {self.capability_id!r}.")
        if not capability.executable:
            raise ValueError(
                f"Capability {self.capability_id} is {capability.status.value} and cannot be planned."
            )
        expected_capability = CAPABILITY_BY_PARAM_TYPE.get(self.params.type)
        if expected_capability != self.capability_id:
            raise ValueError(
                f"Params type {self.params.type!r} does not belong to capability {self.capability_id!r}."
            )
        return self


class VerificationRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: Literal["duration", "streams", "frame_count", "audio_presence", "resolution"]
    description: str = Field(min_length=1, max_length=160)


class ProfessionalEditingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    request_id: str = Field(pattern=r"^req_[a-z0-9]{8,32}$")
    raw_instruction: str = Field(min_length=1, max_length=500)
    interpreted_intention: str = Field(min_length=1, max_length=300)
    outcome: PlanOutcome = PlanOutcome.PLAN_READY
    subject: SubjectSelection
    target: OutputTarget = Field(default_factory=OutputTarget)
    operations: list[DirectorOperation] = Field(default_factory=list)
    required_providers: list[str] = Field(default_factory=list)
    estimated_stages: list[DirectorStage] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    verification_requirements: list[VerificationRequirement] = Field(default_factory=list)
    summary_explanation: str = Field(min_length=1, max_length=400)
    explanations: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED

    @model_validator(mode="after")
    def _validate_plan(self) -> "ProfessionalEditingPlan":
        self._validate_operations()
        self._validate_outcome()
        self._validate_stages()
        self._validate_providers()
        self._validate_approval()
        return self

    def _validate_operations(self) -> None:
        seen: set[str] = set()
        for index, operation in enumerate(self.operations):
            if operation.operation_id in seen:
                raise ValueError(f"Duplicate operation id {operation.operation_id!r}.")
            for dependency in operation.dependencies:
                if dependency not in seen:
                    raise ValueError(
                        f"Operation {operation.operation_id} depends on {dependency!r}, which must appear earlier."
                    )
            seen.add(operation.operation_id)
            if operation.status is not OperationStatus.PROPOSED:
                raise ValueError("A freshly generated plan may only contain proposed operations.")

        capability_ids = {op.capability_id for op in self.operations}
        if self.outcome is PlanOutcome.PLAN_READY:
            for required in ("subject.isolate", "video.render_mp4", "output.verify"):
                if required not in capability_ids:
                    raise ValueError(f"A ready edit plan must include {required}.")
            if self.target.preserve_audio and "audio.preserve" not in capability_ids:
                raise ValueError("preserve_audio is true, so the plan must include audio.preserve.")
            if not ({"background.blur", "background.replace"} & capability_ids):
                raise ValueError("A ready edit plan must include background.blur or background.replace.")

        # No plan may reference disabled/planned capabilities, including in explanations.
        for capability_id in self.unsupported_capabilities:
            capability = get_capability(capability_id)
            if capability is None:
                raise ValueError(f"Unknown capability {capability_id!r} listed as unsupported.")
            if capability.executable:
                raise ValueError(f"Capability {capability_id} is available, not unsupported.")

    def _validate_outcome(self) -> None:
        if self.outcome is PlanOutcome.PLAN_READY:
            if not self.operations:
                raise ValueError("A ready plan needs operations.")
            if self.clarification_questions:
                raise ValueError("A ready plan must not ask clarification questions.")
            if self.unsupported_capabilities:
                raise ValueError("A ready plan must not list unsupported capabilities.")
        elif self.outcome is PlanOutcome.NEEDS_CLARIFICATION:
            if self.operations:
                raise ValueError("A clarification plan must not contain operations.")
            if not self.clarification_questions:
                raise ValueError("A clarification plan needs at least one question.")
            # The ambiguity may be in the intent (broad or conflicting request)
            # rather than in the subject. The playbook allows both; the subject
            # flag stays truthful instead of being forced to true.
        else:  # UNSUPPORTED
            if self.operations:
                raise ValueError("An unsupported plan must not contain operations.")
            if not self.unsupported_capabilities:
                raise ValueError("An unsupported plan must name the unavailable capabilities.")
            if self.clarification_questions:
                raise ValueError("An unsupported plan must not ask a clarification question.")

    def _validate_stages(self) -> None:
        if self.outcome is not PlanOutcome.PLAN_READY:
            if self.estimated_stages:
                raise ValueError("Only ready plans describe execution stages.")
            return
        if not self.estimated_stages:
            raise ValueError("A ready plan must estimate its stages.")
        if self.estimated_stages[0] is not DirectorStage.PLAN_READY:
            raise ValueError("Estimated stages must start at PLAN_READY.")
        if self.estimated_stages[-1] is not DirectorStage.COMPLETED:
            raise ValueError("Estimated stages must end at COMPLETED.")
        for source, target in zip(self.estimated_stages, self.estimated_stages[1:]):
            if not can_transition(source, target):
                raise ValueError(f"Invalid estimated stage transition {source.value} -> {target.value}.")

    def _validate_providers(self) -> None:
        derived: set[str] = set()
        for operation in self.operations:
            capability = get_capability(operation.capability_id)
            assert capability is not None
            if capability.required_provider:
                derived.add(capability.required_provider)
        if set(self.required_providers) != derived:
            raise ValueError(
                f"required_providers must match operation requirements: expected {sorted(derived)}."
            )

    def _validate_approval(self) -> None:
        requires = any(
            get_capability(op.capability_id).requires_approval  # type: ignore[union-attr]
            for op in self.operations
        )
        if self.outcome is not PlanOutcome.PLAN_READY:
            if self.approval_status is not ApprovalStatus.NOT_REQUIRED:
                raise ValueError("Non-executing plans do not require approval.")
            return
        if requires and self.approval_status not in {ApprovalStatus.REQUIRED, ApprovalStatus.APPROVED}:
            raise ValueError("This plan contains capabilities that require user approval.")
        if not requires and self.approval_status is ApprovalStatus.REQUIRED:
            raise ValueError("No operation in this plan requires approval.")

    # --- v1 adapter -------------------------------------------------------

    def to_execution_plan(self):
        """Convert to the v1 EditingPlan executed by the current worker."""
        from clipforge_contracts.editing_plan import (
            BlurBackgroundOperation,
            EditingIntent,
            EditingPlan,
            KeepSubjectSharpOperation,
            ReplaceBackgroundOperation,
            SubjectSpec,
        )

        v1_subject = SubjectSpec(
            description=self.subject.description,
            is_ambiguous=self.subject.is_ambiguous,
            clarification_question=self.subject.clarification_question,
        )

        if self.outcome is PlanOutcome.NEEDS_CLARIFICATION:
            question = self.clarification_questions[0]
            return EditingPlan(
                plan_id=self.request_id,
                raw_transcript=self.raw_instruction,
                intent=EditingIntent.CLARIFICATION_NEEDED,
                subject=SubjectSpec(
                    description=self.subject.description,
                    is_ambiguous=True,
                    clarification_question=question,
                ),
                operations=[],
            )
        if self.outcome is PlanOutcome.UNSUPPORTED:
            return EditingPlan(
                plan_id=self.request_id,
                raw_transcript=self.raw_instruction,
                intent=EditingIntent.UNSUPPORTED,
                subject=v1_subject,
                operations=[],
            )

        operations = []
        for operation in self.operations:
            if operation.capability_id == "subject.isolate":
                operations.append(KeepSubjectSharpOperation())
            elif operation.capability_id == "background.blur":
                params = operation.params
                assert isinstance(params, BlurBackgroundParams)
                operations.append(BlurBackgroundOperation(strength=params.strength))
            elif operation.capability_id == "background.replace":
                params = operation.params
                assert isinstance(params, ReplaceBackgroundParams)
                operations.append(
                    ReplaceBackgroundOperation(
                        prompt=params.prompt,
                        asset_id=params.asset_id,
                        asset_source=params.asset_source,
                        backdrop=params.backdrop.model_dump(mode="json") if params.backdrop else None,
                    )
                )

        if not any(op.type in {"blur_background", "replace_background"} for op in operations):
            raise DirectorPlanError("Plan cannot be adapted to v1: no executable background operation.")
        intent = (
            EditingIntent.REPLACE_BACKGROUND
            if any(op.type == "replace_background" for op in operations)
            else EditingIntent.BLUR_BACKGROUND
        )
        return EditingPlan(
            plan_id=self.request_id,
            raw_transcript=self.raw_instruction,
            intent=intent,
            subject=v1_subject,
            operations=operations,
            preserve_audio=self.target.preserve_audio,
        )
