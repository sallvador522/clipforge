"""ProfessionalEditingPlan v2-lite — minimal wire contract (Milestone 6B-LIVE LIVE-CALL 003).

The full v2 schema (~8.4 KB, 16 $defs) is the prime suspect for the Contributor
500s, so the wire carries a hand-written minimal schema: zero $refs, flat
operation objects, no timing fields at all (timing stays forbidden while
`timeline.trim` is disabled). Strictness is NOT relaxed: the response is parsed
into `LitePlan`, model-generated operation ids are canonicalised (`op_1`...),
converted to a full `ProfessionalEditingPlan`, and the full
registry/dependency/approval validators run unchanged.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts.capabilities import (
    BlurBackgroundParams,
    IsolateSubjectParams,
    PreserveAudioParams,
    RenderMp4Params,
    ReplaceBackgroundParams,
    VerifyOutputParams,
    get_capability,
)
from clipforge_contracts.director_plan import (
    ApprovalStatus,
    DirectorOperation,
    OperationStatus,
    OutputTarget,
    PlanOutcome,
    ProfessionalEditingPlan,
    SubjectSelection,
    SubjectStrategy,
    VerificationRequirement,
)
from clipforge_contracts.director_stages import DirectorStage

LITE_SCHEMA_VERSION = "2.0-lite"

_EXECUTABLE_IDS = (
    "subject.isolate",
    "background.blur",
    "background.replace",
    "audio.preserve",
    "video.render_mp4",
    "output.verify",
)

# Hand-written wire schema: zero $refs, all inline. Kept deliberately small.
LITE_WIRE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string", "pattern": "^req_[a-z0-9]{8,32}$"},
        "raw_instruction": {"type": "string"},
        "interpreted_intention": {"type": "string"},
        "outcome": {"type": "string", "enum": ["plan_ready", "needs_clarification", "unsupported"]},
        "subject_description": {"type": "string"},
        "subject_is_ambiguous": {"type": "boolean"},
        "clarification_question": {"type": "string"},
        "preserve_audio": {"type": "boolean"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "operation_id": {"type": "string"},
                    "capability_id": {"type": "string", "enum": list(_EXECUTABLE_IDS)},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "params": {
                        "type": "object",
                        "properties": {
                            # Enums mirror the strict capability params models.
                            # Without them the model copied prompt wording such as
                            # "mock segmentation" into params.strategy.
                            "strategy": {
                                "type": "string",
                                "enum": ["largest_subject", "named_subject", "foreground"],
                            },
                            "subject_description": {"type": "string"},
                            "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "feather_px": {"type": "integer", "minimum": 0, "maximum": 21},
                            "prompt": {"type": "string"},
                            "asset_source": {
                                "type": "string",
                                "enum": ["local_asset", "mock_generated"],
                            },
                            "composition": {
                                "type": "string",
                                "enum": ["centered", "rule_of_thirds"],
                            },
                        },
                        "additionalProperties": False,
                    },
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "expected_output": {"type": "string"},
                },
                "required": [
                    "operation_id",
                    "capability_id",
                    "title",
                    "explanation",
                    "params",
                    "dependencies",
                    "expected_output",
                ],
                "additionalProperties": False,
            },
        },
        "summary_explanation": {"type": "string"},
        "clarification_questions": {"type": "array", "items": {"type": "string"}},
        "unsupported_capabilities": {"type": "array", "items": {"type": "string"}},
        "approval_status": {"type": "string", "enum": ["not_required", "required", "approved", "rejected"]},
    },
    "required": [
        "request_id",
        "raw_instruction",
        "interpreted_intention",
        "outcome",
        "subject_description",
        "subject_is_ambiguous",
        "preserve_audio",
        "operations",
        "summary_explanation",
        "clarification_questions",
        "unsupported_capabilities",
        "approval_status",
    ],
    "additionalProperties": False,
}

LITE_BRIEF = """You are ClipForge's professional video editing director. Turn the confirmed instruction into one executable editing plan. Reason with professional editing knowledge, but plan ONLY these available capabilities: subject.isolate (synthetic placeholder masks, not SAM; params.strategy must be exactly one of largest_subject, named_subject, foreground), background.blur (local render), background.replace (local compositing over a generated background: Muse Image when live or local mock; requires approval), audio.preserve, video.render_mp4, output.verify (ffprobe checks). Everything else is unavailable — name it if asked, never plan it.
RULES: smallest plan that fulfils the intent; order isolate, background, audio, render, verify; end every executable plan with output.verify; ambiguous subject or intent means needs_clarification with one focused question and zero operations; unsupported request means unsupported naming the capability with zero operations; explain each operation in one sentence, no chain-of-thought; never emit shell commands, paths, URLs, flags, credentials or arbitrary parameters.
OUTPUT: exactly one JSON object matching the schema, nothing else. Copy request_id and raw_instruction verbatim. Set approval_status to "required" when background.replace is included, else "not_required"."""

_LITE_REGISTRY_LINES = (
    "subject.isolate [synthetic placeholder masks, not SAM; "
    "params.strategy: largest_subject | named_subject | foreground]; background.blur [local]; "
    "background.replace [generated background: Muse Image when live or local mock, REQUIRES APPROVAL]; "
    "audio.preserve [local]; video.render_mp4 [local]; output.verify [local]. "
    "Unavailable (explain, never plan): background.generate (internal step of background.replace; "
    "never plan separately); scene.detect_cuts, "
    "timeline.trim, transition.apply, keyframe.animate, multitrack.edit, colour.grade, "
    "speed.ramp, audio.mix, captions.animate (disabled)."
)


def lite_capability_summary() -> str:
    return _LITE_REGISTRY_LINES


class LiteOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The wire may carry a model-generated id (e.g. `op1_isolate`). The provider
    # canonicalises every id to `op_1`...`op_n` before full v2 validation.
    operation_id: str = Field(min_length=1, max_length=80)
    capability_id: Literal[
        "subject.isolate",
        "background.blur",
        "background.replace",
        "audio.preserve",
        "video.render_mp4",
        "output.verify",
    ]
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=300)
    params: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    expected_output: str = Field(min_length=1, max_length=200)


class LitePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0-lite"] = "2.0-lite"
    request_id: str = Field(pattern=r"^req_[a-z0-9]{8,32}$")
    raw_instruction: str = Field(min_length=1, max_length=500)
    interpreted_intention: str = Field(min_length=1, max_length=300)
    outcome: PlanOutcome = PlanOutcome.PLAN_READY
    subject_description: str = Field(min_length=1, max_length=200)
    subject_is_ambiguous: bool = False
    clarification_question: str = Field(default="", max_length=300)
    preserve_audio: bool = True
    operations: list[LiteOperation] = Field(default_factory=list)
    summary_explanation: str = Field(min_length=1, max_length=400)
    clarification_questions: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED


_VERIFICATION_REQUIREMENTS = [
    ("duration", "Output duration matches the rendered frame count."),
    ("streams", "Output has a video stream (and audio when expected)."),
    ("frame_count", "Frame count equals the source/mask count."),
    ("audio_presence", "Original audio survives when the source has audio."),
    ("resolution", "Resolution equals the target 720p/source size."),
]


def _typed_params(capability_id: str, raw: dict[str, Any]) -> BaseModel:
    """Map a lite params dict onto the strict capability params model."""
    if capability_id == "subject.isolate":
        return IsolateSubjectParams(
            strategy=raw.get("strategy", "largest_subject"),
            subject_description=raw.get("subject_description"),
        )
    if capability_id == "background.blur":
        return BlurBackgroundParams(
            strength=raw.get("strength", 0.8),
            feather_px=raw.get("feather_px", 5),
        )
    if capability_id == "background.replace":
        return ReplaceBackgroundParams(
            prompt=raw.get("prompt", ""),
            asset_source=raw.get("asset_source", "local_asset"),
            composition=raw.get("composition", "centered"),
        )
    if capability_id == "audio.preserve":
        return PreserveAudioParams()
    if capability_id == "video.render_mp4":
        return RenderMp4Params()
    if capability_id == "output.verify":
        return VerifyOutputParams()
    raise ValueError(f"No params mapping for capability {capability_id!r}.")


def normalize_lite_operation_ids(
    operations: list[LiteOperation],
) -> tuple[list[LiteOperation], dict[str, str]]:
    """Assign deterministic canonical ids and rewrite dependencies.

    The model owns the operation semantics but not the internal id format. We
    keep the incoming order, map every original id to `op_1`...`op_n`, rewrite
    dependency references through the same map, and reject ambiguous graphs
    before the full v2 validators run.

    Returns the normalized operations and the complete original -> canonical map.
    """
    mapping: dict[str, str] = {}
    originals: list[str] = []

    for index, operation in enumerate(operations, start=1):
        original = operation.operation_id.strip()
        if not original:
            raise ValueError("Operation id must not be empty.")
        if original in mapping:
            raise ValueError(f"Duplicate operation id {original!r}.")
        mapping[original] = f"op_{index}"
        originals.append(original)

    dependencies: dict[str, list[str]] = {}
    for operation in operations:
        original = operation.operation_id.strip()
        rewritten: list[str] = []
        for raw_dependency in operation.dependencies:
            dependency = raw_dependency.strip()
            if dependency not in mapping:
                raise ValueError(
                    f"Operation {original!r} depends on unknown operation {dependency!r}."
                )
            rewritten.append(dependency)
        dependencies[original] = rewritten

    # Explicit cycle detection gives a precise error before the forward-order check.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join(path + [node])
            raise ValueError(f"Dependency cycle detected: {cycle}.")
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency, path + [node])
        visiting.remove(node)
        visited.add(node)

    for original in originals:
        visit(original, [])

    index_by_id = {original: index for index, original in enumerate(originals)}
    normalized: list[LiteOperation] = []
    for index, operation in enumerate(operations):
        original = operation.operation_id.strip()
        canonical_dependencies: list[str] = []
        for dependency in dependencies[original]:
            if index_by_id[dependency] >= index:
                raise ValueError(
                    f"Operation {original!r} depends on {dependency!r}, which must appear earlier."
                )
            canonical_dependencies.append(mapping[dependency])
        normalized.append(
            operation.model_copy(
                update={
                    "operation_id": mapping[original],
                    "dependencies": canonical_dependencies,
                }
            )
        )

    return normalized, mapping


def lite_to_full_plan(lite: LitePlan) -> ProfessionalEditingPlan:
    """Convert a lite plan into a full v2 plan. Full validators run on construction."""
    plan, _ = lite_to_full_plan_with_mapping(lite)
    return plan


def lite_to_full_plan_with_mapping(
    lite: LitePlan,
) -> tuple[ProfessionalEditingPlan, dict[str, str]]:
    """Convert a lite plan and expose the original -> canonical operation id map."""
    normalized_operations, operation_id_map = normalize_lite_operation_ids(lite.operations)
    subject = SubjectSelection(
        strategy=SubjectStrategy.LARGEST_SUBJECT,
        description=lite.subject_description,
        is_ambiguous=lite.subject_is_ambiguous,
        clarification_question=lite.clarification_question or None,
    )
    operations: list[DirectorOperation] = []
    for lite_op in normalized_operations:
        if lite_op.capability_id not in _EXECUTABLE_IDS:
            raise ValueError(f"Capability {lite_op.capability_id!r} is not executable.")
        operations.append(
            DirectorOperation(
                operation_id=lite_op.operation_id,
                capability_id=lite_op.capability_id,
                title=lite_op.title,
                explanation=lite_op.explanation,
                params=_typed_params(lite_op.capability_id, dict(lite_op.params or {})),
                dependencies=list(lite_op.dependencies),
                status="proposed",
                expected_output=lite_op.expected_output,
            )
        )
    providers = sorted(
        {
            get_capability(op.capability_id).required_provider  # type: ignore[union-attr]
            for op in operations
            if get_capability(op.capability_id) and get_capability(op.capability_id).required_provider  # type: ignore[union-attr]
        }
    )
    needs_approval = any(
        get_capability(op.capability_id).requires_approval  # type: ignore[union-attr]
        for op in operations
    )
    stages = [DirectorStage.PLAN_READY]
    if needs_approval:
        stages.append(DirectorStage.WAITING_FOR_APPROVAL)
    stages.extend([DirectorStage.EXECUTING, DirectorStage.VERIFYING, DirectorStage.COMPLETED])
    plan = ProfessionalEditingPlan(
        request_id=lite.request_id,
        raw_instruction=lite.raw_instruction,
        interpreted_intention=lite.interpreted_intention,
        outcome=lite.outcome,
        subject=subject,
        operations=operations,
        required_providers=providers,
        estimated_stages=stages if lite.outcome is PlanOutcome.PLAN_READY else [],
        expected_results=[f"{op.title}: {op.expected_output}" for op in operations][:5],
        verification_requirements=[
            VerificationRequirement(check=check, description=description)  # type: ignore[arg-type]
            for check, description in _VERIFICATION_REQUIREMENTS
        ],
        summary_explanation=lite.summary_explanation,
        explanations=[op.explanation for op in operations],
        clarification_questions=list(lite.clarification_questions),
        unsupported_capabilities=list(lite.unsupported_capabilities),
        approval_status=lite.approval_status,
    )
    return plan, operation_id_map
