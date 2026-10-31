"""Edit Decision List (EDL) v2 — declarative projection of a ProfessionalEditingPlan.

Security model (no global text deny-list):
- Decisions reference only registered, executable capabilities.
- Parameters are the same typed capability param models used by v2 (discriminated,
  `extra="forbid"`); unknown fields and types are rejected by schema validation.
- No handler, path, URL or command travels with model output. Execution resolves the
  backend handler from the registry (`edl_handler_for`), never from the EDL itself.
- Timing fields are legal only when the owning timeline capability
  (`timeline.trim`) is executable. While it is disabled, any timing value fails.
- Provenance uses canonical JSON (sorted keys, compact separators) over the decision
  content excluding the hash field itself, so hashes are reproducible.

Edit history reuses the existing job store: `EditHistoryEntry` is designed to be
stored inside `JobRecord.edit_history` (persisted in `job.json`). No new database,
memory service, read API or endpoint is introduced in this milestone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge_contracts.capabilities import (
    CAPABILITY_BY_PARAM_TYPE,
    BlurBackgroundParams,
    IsolateSubjectParams,
    PreserveAudioParams,
    RenderMp4Params,
    ReplaceBackgroundParams,
    VerifyOutputParams,
    edl_handler_for,
    edl_timing_allowed,
    get_capability,
)
from clipforge_contracts.director_plan import ApprovalStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(payload: dict) -> str:
    """Reproducible SHA-256 over canonical JSON (sorted keys, compact separators)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DecisionTransparency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested: str = Field(min_length=1, max_length=300)
    understood: str = Field(min_length=1, max_length=300)
    why: str = Field(min_length=1, max_length=300)
    approval_required: bool = False
    approval_state: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    operator_message: str = Field(min_length=1, max_length=300)


EDLParams = Annotated[
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


class EditDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(pattern=r"^dec_[a-z0-9]{8,32}$")
    capability_id: str
    operation_id: str = Field(pattern=r"^op_[a-z0-9_]{1,40}$")
    params: EDLParams
    dependencies: list[str] = Field(default_factory=list)
    start_s: float | None = Field(default=None, ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)
    in_point_s: float | None = Field(default=None, ge=0.0)
    out_point_s: float | None = Field(default=None, ge=0.0)
    transparency: DecisionTransparency
    provenance_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_decision(self) -> "EditDecision":
        capability = get_capability(self.capability_id)
        if capability is None:
            raise ValueError(f"Unknown capability {self.capability_id!r}.")
        if not capability.executable:
            raise ValueError(
                f"Capability {self.capability_id} is {capability.status.value} and cannot be planned."
            )
        expected = CAPABILITY_BY_PARAM_TYPE.get(self.params.type)
        if expected != self.capability_id:
            raise ValueError(
                f"Params type {self.params.type!r} does not belong to capability {self.capability_id!r}."
            )
        # Timing gate: only legal when the owning timeline capability is executable.
        if any(
            value is not None
            for value in (self.start_s, self.end_s, self.in_point_s, self.out_point_s)
        ):
            if not edl_timing_allowed():
                raise ValueError(
                    "EDL timing fields are forbidden while timeline.trim is disabled."
                )
            if self.start_s is not None and self.end_s is not None and self.end_s <= self.start_s:
                raise ValueError("EDL end_s must be greater than start_s.")
        # Approval must mirror the registry.
        if capability.requires_approval != self.transparency.approval_required:
            raise ValueError(
                f"Capability {self.capability_id} requires_approval={capability.requires_approval} "
                f"but transparency says {self.transparency.approval_required}."
            )
        if capability.requires_approval:
            if self.transparency.approval_state not in {
                ApprovalStatus.REQUIRED,
                ApprovalStatus.APPROVED,
            }:
                raise ValueError(
                    f"Capability {self.capability_id} requires approval; "
                    f"got {self.transparency.approval_state.value}."
                )
        elif self.transparency.approval_state is ApprovalStatus.REQUIRED:
            raise ValueError(f"Capability {self.capability_id} does not require approval.")
        return self

    def verify_provenance(self, *, edl_id: str, request_id: str) -> None:
        expected = compute_decision_hash(
            edl_id=edl_id,
            request_id=request_id,
            decision=self,
        )
        if expected != self.provenance_hash:
            raise ValueError(
                f"Decision {self.decision_id} provenance hash mismatch (tampered or miscomputed)."
            )


def compute_decision_hash(*, edl_id: str, request_id: str, decision: EditDecision) -> str:
    """Hash over canonical content, excluding the hash field itself."""
    params = decision.params.model_dump(mode="json")
    payload = {
        "edl_id": edl_id,
        "request_id": request_id,
        "decision_id": decision.decision_id,
        "capability_id": decision.capability_id,
        "operation_id": decision.operation_id,
        "params": params,
        "dependencies": list(decision.dependencies),
        "timing": {
            "start_s": decision.start_s,
            "end_s": decision.end_s,
            "in_point_s": decision.in_point_s,
            "out_point_s": decision.out_point_s,
        },
    }
    return canonical_hash(payload)


def build_decision(
    *,
    edl_id: str,
    request_id: str,
    decision_id: str,
    capability_id: str,
    operation_id: str,
    params: EDLParams,
    dependencies: list[str] | None = None,
    transparency: DecisionTransparency,
    start_s: float | None = None,
    end_s: float | None = None,
    in_point_s: float | None = None,
    out_point_s: float | None = None,
) -> EditDecision:
    """Construct a decision with a correct provenance hash (no self-hashing)."""
    draft = EditDecision.model_construct(
        decision_id=decision_id,
        capability_id=capability_id,
        operation_id=operation_id,
        params=params,
        dependencies=list(dependencies or []),
        start_s=start_s,
        end_s=end_s,
        in_point_s=in_point_s,
        out_point_s=out_point_s,
        transparency=transparency,
        provenance_hash="0" * 64,
    )
    digest = compute_decision_hash(edl_id=edl_id, request_id=request_id, decision=draft)
    return EditDecision(
        decision_id=decision_id,
        capability_id=capability_id,
        operation_id=operation_id,
        params=params,
        dependencies=list(dependencies or []),
        start_s=start_s,
        end_s=end_s,
        in_point_s=in_point_s,
        out_point_s=out_point_s,
        transparency=transparency,
        provenance_hash=digest,
    )


class EditHistoryEntry(BaseModel):
    """Immutable history record. Stored in JobRecord.edit_history (job.json). No raw media."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str = Field(pattern=r"^hist_[a-z0-9]{8,32}$")
    at: datetime
    stage: Literal[
        "REQUEST_RECEIVED",
        "ANALYZING_REQUEST",
        "PLAN_READY",
        "WAITING_FOR_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "COMPLETED",
        "FAILED",
        "NEEDS_CLARIFICATION",
        "CANCELLED",
    ]
    actor: Literal["user", "director", "system"]
    summary: str = Field(min_length=1, max_length=300)
    refs: list[str] = Field(
        default_factory=list,
        description="Capability/plan/result ids only; allow-listed characters, no paths.",
    )

    @model_validator(mode="after")
    def _validate_refs(self) -> "EditHistoryEntry":
        import re

        pattern = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
        for ref in self.refs:
            if not pattern.match(ref):
                raise ValueError(f"History ref {ref!r} uses characters outside the allow-list.")
            if ".." in ref:
                raise ValueError(f"History ref {ref!r} must not contain parent traversal.")
        return self


class EditDecisionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    edl_id: str = Field(pattern=r"^edl_[a-z0-9]{8,32}$")
    request_id: str = Field(pattern=r"^req_[a-z0-9]{8,32}$")
    plan_id: str = Field(pattern=r"^req_[a-z0-9]{8,32}$")
    created_at: datetime = Field(default_factory=utc_now)
    decisions: list[EditDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_edl(self) -> "EditDecisionList":
        seen: set[str] = set()
        op_ids: set[str] = set()
        for decision in self.decisions:
            if decision.decision_id in seen:
                raise ValueError(f"Duplicate decision id {decision.decision_id!r}.")
            seen.add(decision.decision_id)
            if decision.operation_id in op_ids:
                raise ValueError(f"Duplicate operation id {decision.operation_id!r} in EDL.")
            op_ids.add(decision.operation_id)
            for dependency in decision.dependencies:
                # Dependencies refer to operation ids that must appear earlier in the EDL.
                earlier = {d.operation_id for d in self.decisions[: self.decisions.index(decision)]}
                if dependency not in earlier:
                    raise ValueError(
                        f"Decision {decision.decision_id} depends on {dependency!r}, "
                        "which must appear earlier."
                    )
            # Controlled handler must exist; resolved from the registry, never from input.
            edl_handler_for(decision.capability_id)
            decision.verify_provenance(edl_id=self.edl_id, request_id=self.request_id)
        if self.decisions:
            capability_ids = {d.capability_id for d in self.decisions}
            for required in ("subject.isolate", "video.render_mp4", "output.verify"):
                if required not in capability_ids:
                    raise ValueError(f"EDL must include {required}.")
        return self

    def handler_map(self) -> dict[str, str]:
        """Resolve controlled backend handlers for every decision (registry authority)."""
        return {d.decision_id: edl_handler_for(d.capability_id) for d in self.decisions}


def edl_from_professional_plan(plan) -> EditDecisionList:
    """Project a ready v2 plan into an EDL. Non-ready plans have no EDL."""
    from clipforge_contracts.director_plan import PlanOutcome

    if plan.outcome is not PlanOutcome.PLAN_READY:
        raise ValueError(f"Only ready plans produce an EDL (got {plan.outcome.value}).")
    edl_id = "edl_" + plan.request_id.removeprefix("req_")
    decisions: list[EditDecision] = []
    for index, operation in enumerate(plan.operations):
        capability = get_capability(operation.capability_id)
        assert capability is not None
        approval_required = bool(capability.requires_approval)
        approval_state = plan.approval_status if approval_required else ApprovalStatus.NOT_REQUIRED
        transparency = DecisionTransparency(
            requested=plan.raw_instruction[:300],
            understood=plan.interpreted_intention[:300],
            why=operation.explanation[:300],
            approval_required=approval_required,
            approval_state=approval_state,
            operator_message=f"{operation.title}: {operation.explanation}"[:300],
        )
        decisions.append(
            build_decision(
                edl_id=edl_id,
                request_id=plan.request_id,
                decision_id=f"dec_{plan.request_id.removeprefix('req_')}{index:02d}",
                capability_id=operation.capability_id,
                operation_id=operation.operation_id,
                params=operation.params,  # type: ignore[arg-type]
                dependencies=list(operation.dependencies),
                transparency=transparency,
            )
        )
    return EditDecisionList(
        edl_id=edl_id,
        request_id=plan.request_id,
        plan_id=plan.request_id,
        decisions=decisions,
    )
