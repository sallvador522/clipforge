"""Idea-to-video API routes.

The API never performs provider work and never renders: it validates the
brief, records cost approvals and enqueues work for the idea worker. Every
paid step needs an explicit approval whose hashes and provider modes are
re-checked by the worker before the call.

Mounted by `clipforge_api.main.create_app` with `app.include_router(...)`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts.idea import (
    AssetStatus,
    IdeaApproval,
    IdeaError,
    IdeaJobRecord,
    IdeaOptions,
    IdeaState,
    IdeaStateEntry,
    IdeaStatus,
    brief_hash,
    storyboard_hash,
)
from clipforge_contracts.storyboard import Storyboard
from clipforge_director.creative import apply_storyboard_patch
from clipforge_director.idea_director import (
    build_assets,
    create_live_refinement_director,
    create_refinement_live,
    creative_effort,
    idea_modes,
    validate_board_for_options,
    validate_board_targets,
)
from clipforge_director.pricing import (
    asset_cost_usd,
    cap_usd,
    estimate_before_plan,
    estimate_from_storyboard,
    image_price_usd,
    storyboard_price_usd,
)
from clipforge_jobs.idea_store import IdeaNotFoundError, IdeaStore, new_idea_id


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


class CreateIdeaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(min_length=10, max_length=1000)
    options: IdeaOptions = Field(default_factory=IdeaOptions)
    project_id: str | None = Field(default=None, max_length=40)


class ApproveStoryboardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float = Field(ge=0.0, le=5.0)


class PatchStoryboardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard: dict
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApproveAssetsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[str] = Field(default_factory=list, max_length=12)
    max_cost_usd: float = Field(default=0.0, ge=0.0, le=5.0)
    programmatic_only: bool = False


class RenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DirectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=1000)
    approved_cost_usd: float = Field(default=0.0, ge=0.0, le=5.0)


def create_ideas_router(
    storage_root: str | Path,
    *,
    transcription_mode: str = "mock",
    refinement_provider_factory=None,
) -> APIRouter:
    store = IdeaStore(storage_root)
    router = APIRouter(prefix="/api/ideas", tags=["ideas"])

    # ------------------------------------------------------------- helpers
    def _load(idea_id: str):
        try:
            return store.get(idea_id), None
        except IdeaNotFoundError as exc:
            return None, _error(404, "idea_not_found", str(exc))

    def _base_url(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def _render_payload(record: IdeaJobRecord, base: str) -> dict | None:
        version = record.idea.delivered_version()
        if version is None:
            return None
        return {
            "version": version.version,
            "url": f"{base}/api/ideas/{record.idea_id}/download",
            "sha256": version.output_sha256,
            "width": version.width,
            "height": version.height,
            "fps": version.fps,
            "frame_count": version.frame_count,
            "duration_seconds": version.duration_seconds,
            "qa": version.qa,
            "created_at": version.created_at.isoformat(),
        }

    def _payload(record: IdeaJobRecord, request: Request) -> dict:
        base = _base_url(request)
        modes = idea_modes()
        delivered = record.idea.delivered_version()
        progress = store.read_progress(record.idea_id) or record.progress
        assets = [
            {
                "asset_id": asset.asset_id,
                "scene_ids": asset.scene_ids,
                "prompt": asset.prompt,
                "orientation": asset.orientation,
                "role": asset.role,
                "status": asset.status.value,
                "url": (
                    f"{base}/api/ideas/{record.idea_id}/assets/{asset.asset_id}"
                    if asset.status == AssetStatus.GENERATED
                    else None
                ),
                "is_mock": asset.is_mock,
                "width": asset.width,
                "height": asset.height,
                "cost_usd": asset.cost_usd,
                "error": asset.error,
            }
            for asset in record.idea.assets
        ]
        return {
            "idea_id": record.idea_id,
            "project_id": record.project_id,
            "status": record.status.value,
            "stage": record.stage,
            "brief": record.idea.brief,
            "options": record.idea.options.model_dump(mode="json"),
            "estimate": record.idea.estimate.model_dump(mode="json") if record.idea.estimate else None,
            "storyboard": (
                record.idea.storyboard.model_dump(mode="json") if record.idea.storyboard else None
            ),
            "storyboard_hash": record.idea.storyboard_hash,
            "pending_patch": (
                record.idea.pending_patch.model_dump(mode="json")
                if record.idea.pending_patch
                else None
            ),
            "pending_clarification_question": record.idea.pending_clarification_question,
            "approvals": [approval.model_dump(mode="json") for approval in record.idea.approvals],
            "assets": assets,
            "render": _render_payload(record, base),
            "versions": [version.model_dump(mode="json") for version in record.idea.versions],
            "spent_usd": record.idea.spent_usd,
            "error": record.error.model_dump(mode="json") if record.error else None,
            "progress": progress.model_dump(mode="json") if progress else None,
            "modes": modes,
            "cancel_requested": record.cancel_requested,
            "history": [entry.model_dump(mode="json") for entry in record.history],
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "can_approve_storyboard": (
                record.status == IdeaStatus.AWAITING_APPROVAL
                and record.stage == "awaiting_storyboard_cost"
            ),
            "can_approve_assets": (
                record.status == IdeaStatus.AWAITING_APPROVAL
                and record.stage == "awaiting_plan_approval"
                and record.idea.storyboard is not None
            ),
            "can_render": (
                record.status in (IdeaStatus.COMPLETED, IdeaStatus.FAILED)
                and record.idea.storyboard is not None
            ),
            "can_download": delivered is not None and record.status == IdeaStatus.COMPLETED,
            "can_cancel": record.status in (IdeaStatus.QUEUED, IdeaStatus.PROCESSING),
        }

    def _adopt_board(record, board, *, post_completion: bool):
        """Persist a validated board + rebuilt assets. Returns an error or None.

        Post-completion, only previously generated image prompts may survive:
        an edit that would need new paid images is refused (ADR-034/036).
        """
        new_assets = build_assets(board, record.idea.options)
        if post_completion and record.idea.options.use_generated_images:
            previous_hashes = {
                asset.prompt_hash
                for asset in record.idea.assets
                if asset.status in (AssetStatus.GENERATED, AssetStatus.SKIPPED)
            }
            introduced = [
                asset.asset_id
                for asset in new_assets
                if asset.prompt_hash not in previous_hashes
            ]
            if introduced:
                return _error(
                    422,
                    "storyboard_new_images",
                    "Esta edição pedia imagens novas "
                    f"({', '.join(introduced)}); edições após conclusão só "
                    "podem reutilizar imagens já geradas. Cria um novo vídeo "
                    "para gerar imagens novas.",
                )
            previous_by_hash = {}
            for asset in record.idea.assets:
                previous_by_hash.setdefault(asset.prompt_hash, asset)
            for asset in new_assets:
                previous = previous_by_hash.get(asset.prompt_hash)
                if previous is None:
                    continue
                if previous.status == AssetStatus.GENERATED:
                    asset.status = AssetStatus.GENERATED
                    asset.filename = previous.filename
                    asset.sha256 = previous.sha256
                    asset.width = previous.width
                    asset.height = previous.height
                    asset.provider_name = previous.provider_name
                    asset.is_mock = previous.is_mock
                    asset.request_id = previous.request_id
                    asset.cost_usd = previous.cost_usd
                    asset.error = None
                    asset.generated_at = previous.generated_at
                else:
                    asset.status = AssetStatus.SKIPPED
        record.idea.storyboard = board
        record.idea.storyboard_hash = storyboard_hash(board)
        record.idea.assets = new_assets
        modes = idea_modes()
        record.idea.estimate = estimate_from_storyboard(
            board,
            record.idea.options,
            director_mode=modes["director"],
            image_mode=modes["image"],
            effort=modes["effort"],
        )
        return None

    # -------------------------------------------------------------- config
    @router.get("/config", response_model=None)
    async def config() -> dict:
        modes = idea_modes()
        return {
            "modes": modes,
            "transcribe_mode": transcription_mode if transcription_mode in ("mock", "live") else "mock",
            "prices": {
                "storyboard_usd": storyboard_price_usd(modes["effort"]),
                "image_usd": image_price_usd(),
            },
            "cap_usd": cap_usd(),
            "defaults": IdeaOptions().model_dump(mode="json"),
        }

    # -------------------------------------------------------------- create
    @router.post("", status_code=201, response_model=None)
    async def create_idea(body: CreateIdeaBody, request: Request) -> dict | JSONResponse:
        brief = body.brief.strip()
        if len(brief) < 10:
            return _error(422, "brief_too_short", "O brief precisa de pelo menos 10 caracteres.")
        modes = idea_modes()
        estimate = estimate_before_plan(
            body.options,
            director_mode=modes["director"],
            image_mode=modes["image"],
            effort=modes["effort"],
        )
        if estimate.total_usd > estimate.cap_usd + 1e-9:
            return _error(
                409,
                "cost_cap_exceeded",
                f"A estimativa (${estimate.total_usd:.4f}) excede o limite por vídeo "
                f"(${estimate.cap_usd:.2f}). Reduz a duração ou desliga as imagens.",
            )
        record = IdeaJobRecord(
            idea_id=new_idea_id(),
            project_id=body.project_id,
            status=IdeaStatus.AWAITING_APPROVAL,
            stage="awaiting_storyboard_cost",
            idea=IdeaState(brief=brief, options=body.options, estimate=estimate),
        )
        record.history.append(
            IdeaStateEntry(
                status=record.status,
                stage=record.stage,
                note=f"Brief recebido · director={modes['director']} · imagens={modes['image']}",
            )
        )
        store.create(record)
        return _payload(record, request)

    # ---------------------------------------------------------------- list
    @router.get("", response_model=None)
    async def list_ideas(limit: int = 20) -> dict:
        records = store.list(limit=max(1, min(limit, 100)))
        return {
            "ideas": [
                {
                    "idea_id": record.idea_id,
                    "brief": record.idea.brief,
                    "status": record.status.value,
                    "stage": record.stage,
                    "spent_usd": record.idea.spent_usd,
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat(),
                }
                for record in records
            ]
        }

    # ------------------------------------------------------------ read one
    @router.get("/{idea_id}", response_model=None)
    async def get_idea(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        return _payload(record, request)

    # ---------------------------------------------------- approve storyboard
    @router.post("/{idea_id}/approve-storyboard", status_code=202, response_model=None)
    async def approve_storyboard(
        idea_id: str, body: ApproveStoryboardBody, request: Request
    ) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.status != IdeaStatus.AWAITING_APPROVAL or record.stage != "awaiting_storyboard_cost":
            return _error(
                409,
                "idea_stage_conflict",
                f"O plano não pode ser aprovado no estado {record.status.value}/{record.stage}.",
            )
        estimate = record.idea.estimate
        if estimate is None:
            return _error(409, "idea_stage_conflict", "Estimativa em falta; cria um novo plano.")
        if body.max_cost_usd + 1e-9 < estimate.storyboard_usd:
            return _error(
                409,
                "cost_cap_exceeded",
                f"O custo do plano (${estimate.storyboard_usd:.4f}) excede o valor aprovado "
                f"(${body.max_cost_usd:.4f}).",
            )
        if body.max_cost_usd > estimate.cap_usd + 1e-9:
            return _error(
                409,
                "cost_cap_exceeded",
                f"O valor aprovado excede o limite por vídeo (${estimate.cap_usd:.2f}).",
            )
        modes = idea_modes()
        record.idea.approvals.append(
            IdeaApproval(
                scope="storyboard",
                approved_usd=body.max_cost_usd,
                provider_modes=dict(modes),
                brief_hash=brief_hash(record.idea.brief, record.idea.options),
            )
        )
        store.transition(
            record,
            status=IdeaStatus.QUEUED,
            stage="planning",
            note=f"Storyboard aprovado até ${body.max_cost_usd:.4f}",
        )
        return _payload(record, request)

    # -------------------------------------------------------- get storyboard
    @router.get("/{idea_id}/storyboard", response_model=None)
    async def get_storyboard(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        return {
            "storyboard": (
                record.idea.storyboard.model_dump(mode="json") if record.idea.storyboard else None
            ),
            "storyboard_hash": record.idea.storyboard_hash,
            "estimate": record.idea.estimate.model_dump(mode="json") if record.idea.estimate else None,
            "approvals": [approval.model_dump(mode="json") for approval in record.idea.approvals],
            "assets": [asset.model_dump(mode="json") for asset in record.idea.assets],
        }

    # ------------------------------------------------------- patch storyboard
    @router.patch("/{idea_id}/storyboard", response_model=None)
    async def patch_storyboard(
        idea_id: str, body: PatchStoryboardBody, request: Request
    ) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        pre_approval = (
            record.status == IdeaStatus.AWAITING_APPROVAL
            and record.stage == "awaiting_plan_approval"
        )
        # Post-completion edits (1-2: text + scene removal) reuse the same
        # validated PATCH. No new image prompts are allowed here, so the edit
        # stays free: only previously approved prompts may survive.
        post_completion = record.status in (IdeaStatus.COMPLETED, IdeaStatus.FAILED)
        if not pre_approval and not post_completion:
            return _error(
                409,
                "idea_stage_conflict",
                f"O storyboard só pode ser editado antes da aprovação final ou "
                f"depois de concluído/falhado (estado atual: {record.status.value}/{record.stage}).",
            )
        if record.idea.storyboard_hash != body.expected_hash:
            return _error(
                409,
                "storyboard_hash_mismatch",
                "O storyboard mudou desde que foi carregado; recarrega antes de guardar.",
            )
        try:
            board = Storyboard.model_validate(body.storyboard)
            validate_board_for_options(board, record.idea.brief, record.idea.options)
            validate_board_targets(board)
        except Exception as exc:  # noqa: BLE001 - surfaced as a stable API error
            return _error(422, "storyboard_invalid", f"Storyboard inválido: {exc}")
        adopt_error = _adopt_board(record, board, post_completion=post_completion)
        if adopt_error:
            return adopt_error
        store.save(record)
        return _payload(record, request)

    # --------------------------------------------- voice/text refinement
    @router.post("/{idea_id}/direct", response_model=None)
    async def direct_refinement(
        idea_id: str, body: DirectBody, request: Request
    ) -> dict | JSONResponse:
        """One live refinement call -> a pending patch for user approval.

        The director never applies anything: the patch waits in
        pending_patch until /direct/apply. Live only (ADR-036); there is no
        mock refinement path and no automatic retry.
        """
        record, error = _load(idea_id)
        if error:
            return error
        board = record.idea.storyboard
        if board is None:
            return _error(409, "idea_stage_conflict", "Ainda não existe storyboard para ajustar.")
        editable = (
            record.status == IdeaStatus.AWAITING_APPROVAL
            and record.stage == "awaiting_plan_approval"
        ) or record.status in (IdeaStatus.COMPLETED, IdeaStatus.FAILED)
        if not editable:
            return _error(
                409,
                "idea_stage_conflict",
                f"O ajuste só é possível com o plano em revisão ou concluído "
                f"(estado atual: {record.status.value}/{record.stage}).",
            )
        modes = idea_modes()
        if modes["director"] != "live" and refinement_provider_factory is None:
            return _error(
                409,
                "refinement_requires_live",
                "O ajuste por voz/texto usa o Director real. Activa "
                "CLIPFORGE_CREATIVE_DIRECTOR_MODE=live para o usar.",
            )
        price = storyboard_price_usd(modes["effort"])
        if modes["director"] == "live" and body.approved_cost_usd + 1e-9 < price:
            return _error(
                409,
                "cost_cap_exceeded",
                f"O ajuste custa até ${price:.4f}; aprovado ${body.approved_cost_usd:.4f}.",
            )
        if record.idea.spent_usd + price > cap_usd() + 1e-9:
            return _error(
                409,
                "cost_cap_exceeded",
                f"Gasto acumulado (${record.idea.spent_usd:.4f}) + ajuste (${price:.4f}) "
                f"excede o limite por vídeo (${cap_usd():.2f}).",
            )
        instruction = body.instruction.strip()
        clarification_context = record.idea.pending_clarification_question
        try:
            if refinement_provider_factory is not None:
                provider = refinement_provider_factory()
                patch = provider.create_patch(
                    board,
                    instruction,
                    authorization=object(),
                    clarification_context=clarification_context,
                )
                cost = float(getattr(provider, "last_cost_usd", 0.0) or 0.0)
            else:
                provider = create_live_refinement_director(effort=creative_effort())
                patch, cost, _request_id = create_refinement_live(
                    provider,
                    board,
                    instruction,
                    store.root,
                    clarification_context=clarification_context,
                )
        except Exception as exc:  # noqa: BLE001 - one attempt, surfaced honestly
            return _error(502, "refinement_failed", f"{type(exc).__name__}: {exc}")
        record.idea.spent_usd = round(record.idea.spent_usd + cost, 6)
        if patch.outcome == "clarification":
            record.idea.pending_patch = None
            record.idea.pending_patch_instruction = None
            record.idea.pending_clarification_question = patch.clarification_question
        else:
            record.idea.pending_patch = patch
            record.idea.pending_patch_instruction = instruction
            record.idea.pending_clarification_question = None
        store.save(record)
        return _payload(record, request)

    @router.post("/{idea_id}/direct/apply", response_model=None)
    async def apply_refinement(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        patch = record.idea.pending_patch
        board = record.idea.storyboard
        if patch is None or board is None:
            return _error(409, "refinement_not_pending", "Não há ajuste pendente para aplicar.")
        post_completion = record.status in (IdeaStatus.COMPLETED, IdeaStatus.FAILED)
        try:
            new_board = apply_storyboard_patch(board, patch)
            validate_board_targets(new_board)
        except Exception as exc:  # noqa: BLE001
            return _error(422, "storyboard_invalid", f"Ajuste inválido: {exc}")
        adopt_error = _adopt_board(record, new_board, post_completion=post_completion)
        if adopt_error:
            return adopt_error
        record.idea.pending_patch = None
        record.idea.pending_patch_instruction = None
        record.history.append(
            IdeaStateEntry(
                status=record.status,
                stage=record.stage,
                note=f"Ajuste aplicado: {patch.summary}"[:300],
            )
        )
        store.save(record)
        return _payload(record, request)

    @router.post("/{idea_id}/direct/reject", response_model=None)
    async def reject_refinement(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        record.idea.pending_patch = None
        record.idea.pending_patch_instruction = None
        store.save(record)
        return _payload(record, request)

    # ---------------------------------------------------------- approve assets
    @router.post("/{idea_id}/approve-assets", status_code=202, response_model=None)
    async def approve_assets(
        idea_id: str, body: ApproveAssetsBody, request: Request
    ) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.status != IdeaStatus.AWAITING_APPROVAL or record.stage != "awaiting_plan_approval":
            return _error(
                409,
                "idea_stage_conflict",
                f"As imagens não podem ser aprovadas no estado {record.status.value}/{record.stage}.",
            )
        board = record.idea.storyboard
        if board is None:
            return _error(409, "idea_stage_conflict", "Ainda não existe storyboard para aprovar.")
        modes = idea_modes()
        selected = [] if body.programmatic_only else list(dict.fromkeys(body.asset_ids))
        if selected and not record.idea.options.use_generated_images:
            return _error(
                409,
                "assets_disabled",
                "As imagens geradas estão desligadas neste projeto; aprova só o render programático.",
            )
        known = {asset.asset_id for asset in record.idea.assets}
        unknown = [asset_id for asset_id in selected if asset_id not in known]
        if unknown:
            return _error(
                422,
                "asset_unknown",
                f"Assets fora do plano aprovado: {unknown}.",
            )
        cost = asset_cost_usd(len(selected), image_mode=modes["image"])
        if cost > body.max_cost_usd + 1e-9:
            return _error(
                409,
                "cost_cap_exceeded",
                f"As imagens custam ${cost:.4f}; o valor aprovado é ${body.max_cost_usd:.4f}.",
            )
        if record.idea.spent_usd + cost > cap_usd() + 1e-9:
            return _error(
                409,
                "cost_cap_exceeded",
                f"Gasto acumulado (${record.idea.spent_usd:.4f}) + imagens (${cost:.4f}) "
                f"excede o limite por vídeo (${cap_usd():.2f}).",
            )
        prompt_hashes = {
            asset.asset_id: asset.prompt_hash
            for asset in record.idea.assets
            if asset.asset_id in selected
        }
        record.idea.approvals.append(
            IdeaApproval(
                scope="assets",
                approved_usd=body.max_cost_usd,
                provider_modes=dict(modes),
                brief_hash=brief_hash(record.idea.brief, record.idea.options),
                asset_ids=selected,
                prompt_hashes=prompt_hashes,
            )
        )
        for asset in record.idea.assets:
            asset.status = AssetStatus.APPROVED if asset.asset_id in selected else AssetStatus.SKIPPED
        record.idea.estimate = estimate_from_storyboard(
            board,
            record.idea.options,
            director_mode=modes["director"],
            image_mode=modes["image"],
            effort=modes["effort"],
            selected_assets=len(selected),
        )
        stage = "generating_assets" if selected else "rendering"
        store.transition(
            record,
            status=IdeaStatus.QUEUED,
            stage=stage,
            note=(
                f"{len(selected)} plate(s) aprovada(s) até ${body.max_cost_usd:.4f}"
                if selected
                else "Render programático aprovado (sem imagens)"
            ),
        )
        return _payload(record, request)

    # ---------------------------------------------------------------- reject
    @router.post("/{idea_id}/reject", status_code=202, response_model=None)
    async def reject_idea(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.status not in (IdeaStatus.AWAITING_APPROVAL, IdeaStatus.QUEUED):
            return _error(
                409,
                "idea_stage_conflict",
                f"O plano não pode ser rejeitado no estado {record.status.value}/{record.stage}.",
            )
        record.error = IdeaError(
            code="rejected_by_user", message="Plano rejeitado pelo utilizador."
        )
        store.transition(record, status=IdeaStatus.REJECTED, stage="rejected", note="Rejeitado")
        return _payload(record, request)

    # ---------------------------------------------------------------- render
    @router.post("/{idea_id}/render", status_code=202, response_model=None)
    async def rerender(idea_id: str, body: RenderBody, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.status not in (IdeaStatus.COMPLETED, IdeaStatus.FAILED):
            return _error(
                409,
                "idea_stage_conflict",
                f"O render só pode ser repetido depois de concluído ou falhado "
                f"(estado atual: {record.status.value}/{record.stage}).",
            )
        if record.idea.storyboard is None or record.idea.storyboard_hash != body.storyboard_hash:
            return _error(
                409,
                "storyboard_hash_mismatch",
                "O storyboard mudou; recarrega o projeto antes de renderizar.",
            )
        record.error = None
        record.cancel_requested = False
        record.progress = None
        store.clear_progress(record.idea_id)
        store.clear_cancel(record.idea_id)
        store.transition(
            record,
            status=IdeaStatus.QUEUED,
            stage="rendering",
            note="Re-render pedido pelo utilizador",
        )
        return _payload(record, request)

    # ---------------------------------------------------------------- cancel
    @router.post("/{idea_id}/cancel", status_code=202, response_model=None)
    async def cancel_idea(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.status == IdeaStatus.QUEUED:
            record.error = IdeaError(code="cancelled_by_user", message="Cancelado pelo utilizador.")
            store.transition(record, status=IdeaStatus.FAILED, stage="failed", note="Cancelado")
            return _payload(record, request)
        if record.status != IdeaStatus.PROCESSING:
            return _error(
                409,
                "idea_stage_conflict",
                f"Não há trabalho em curso para cancelar (estado {record.status.value}).",
            )
        record.cancel_requested = True
        store.request_cancel(idea_id)
        store.save(record)
        return _payload(record, request)

    # -------------------------------------------------------- render manifest
    @router.get("/{idea_id}/render-manifest", response_model=None)
    async def render_manifest(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        if record.idea.storyboard is None:
            return _error(409, "idea_stage_conflict", "Ainda não existe storyboard para renderizar.")
        if record.status not in (IdeaStatus.QUEUED, IdeaStatus.PROCESSING, IdeaStatus.COMPLETED):
            return _error(
                409,
                "idea_stage_conflict",
                f"Manifesto indisponível no estado {record.status.value}/{record.stage}.",
            )
        base = _base_url(request)
        asset_urls = {
            asset.asset_id: f"{base}/api/ideas/{idea_id}/assets/{asset.asset_id}"
            for asset in record.idea.assets
            if asset.status == AssetStatus.GENERATED
        }
        options = record.idea.options
        return {
            "idea_id": idea_id,
            "storyboard": record.idea.storyboard.model_dump(mode="json"),
            "asset_urls": asset_urls,
            "width": options.width,
            "height": options.height,
            "fps": options.fps,
            # ADR-036: the delivered board defines the real duration.
            "duration_seconds": record.idea.storyboard.duration_seconds,
            "frame_count": record.idea.storyboard.total_frames,
        }

    # ---------------------------------------------------------------- assets
    @router.get("/{idea_id}/assets/{asset_id}", response_model=None)
    async def get_asset(idea_id: str, asset_id: str):
        record, error = _load(idea_id)
        if error:
            return error
        asset = next((item for item in record.idea.assets if item.asset_id == asset_id), None)
        if asset is None or asset.status != AssetStatus.GENERATED:
            return _error(404, "asset_not_found", f"Asset {asset_id} não foi gerado.")
        path = store.asset_path(idea_id, asset_id)
        if not path.is_file():
            return _error(404, "asset_not_found", f"Ficheiro do asset {asset_id} em falta no disco.")
        return FileResponse(path, media_type="image/png")

    # -------------------------------------------------------------- download
    @router.get("/{idea_id}/download", response_model=None)
    async def download(idea_id: str):
        record, error = _load(idea_id)
        if error:
            return error
        version = record.idea.delivered_version()
        if record.status != IdeaStatus.COMPLETED or version is None:
            return _error(
                409,
                "render_not_verified",
                f"O vídeo ainda não tem um render verificado (estado {record.status.value}/{record.stage}).",
            )
        path = store.root / version.output_relative_path
        if not path.is_file() or path.stat().st_size == 0:
            return _error(409, "render_not_verified", "O ficheiro renderizado não existe no disco.")
        return FileResponse(path, media_type="video/mp4", filename=f"clipforge-{idea_id}.mp4")

    # ---------------------------------------------------------------- result
    @router.get("/{idea_id}/result", response_model=None)
    async def result(idea_id: str, request: Request) -> dict | JSONResponse:
        record, error = _load(idea_id)
        if error:
            return error
        return {
            "idea_id": idea_id,
            "status": record.status.value,
            "stage": record.stage,
            "render": _render_payload(record, _base_url(request)),
            "versions": [version.model_dump(mode="json") for version in record.idea.versions],
            "spent_usd": record.idea.spent_usd,
            "error": record.error.model_dump(mode="json") if record.error else None,
        }

    return router
