"""Idea job processor: plan -> approved assets -> render -> verify.

Runs in a persistent worker process, never inside the API. Each paid step is
re-checked against the persisted approval (brief hash, prompt hashes, provider
modes, per-job cap) immediately before the call. There are no automatic
retries: a failed asset or render leaves the job failed with a stable error
code and preserves everything already produced.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from clipforge_contracts import sha256_file
from clipforge_contracts.idea import (
    ApprovalScope,
    AssetStatus,
    IdeaError,
    IdeaJobRecord,
    IdeaProgress,
    IdeaStatus,
    RenderVersion,
    brief_hash,
    storyboard_hash,
    utc_now,
)
from clipforge_director.idea_director import (
    MockIdeaDirector,
    build_assets,
    create_live_director,
    create_storyboard_live,
    creative_effort,
    idea_modes,
    validate_board_for_options,
    validate_board_targets,
)
from clipforge_director.ledger import LiveCallAuthorization
from clipforge_director.pricing import asset_cost_usd, cap_usd, estimate_from_storyboard
from clipforge_jobs.idea_store import IdeaStore
from clipforge_worker.idea_renderer import IdeaCancelled, IdeaRenderError, IdeaRenderRequest, render_idea

logger = logging.getLogger("clipforge.idea_worker")

DEFAULT_STUDIO_URL = "http://localhost:3000"
DEFAULT_API_URL = "http://localhost:8000"


def _image_provider(mode: str):
    if mode == "mock":
        from clipforge_providers import MockBackgroundGenerationProvider

        return MockBackgroundGenerationProvider()
    if mode != "live":
        raise ValueError(f"Invalid idea image mode {mode!r}.")
    from clipforge_providers.muse_image import (
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        DEFAULT_TIMEOUT_SECONDS,
        MuseImageBackgroundProvider,
    )

    api_key = os.environ.get("MODEL_API_KEY", "")
    if not api_key.strip():
        raise RuntimeError(
            "CLIPFORGE_IDEA_IMAGE_MODE=live requires MODEL_API_KEY (server-side only). "
            "No request was attempted."
        )
    return MuseImageBackgroundProvider(
        api_key,
        base_url=os.environ.get("META_IMAGE_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("META_IMAGE_MODEL", DEFAULT_MODEL),
        timeout_seconds=float(os.environ.get("META_IMAGE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
    )


class IdeaProcessor:
    def __init__(
        self,
        store: IdeaStore,
        *,
        studio_url: str | None = None,
        api_url: str | None = None,
        director_factory=None,
        image_provider_factory=None,
    ) -> None:
        self.store = store
        self.storage_root = store.root
        self.studio_url = studio_url or os.environ.get("CLIPFORGE_STUDIO_URL", DEFAULT_STUDIO_URL)
        self.api_url = api_url or os.environ.get("CLIPFORGE_API_URL", DEFAULT_API_URL)
        self._director_factory = director_factory or self._default_director
        self._image_provider_factory = image_provider_factory or _image_provider

    @staticmethod
    def _default_director(mode: str):
        if mode == "mock":
            return MockIdeaDirector()
        # Effort comes from the environment — the single source of truth that
        # idea_modes() also reports, so approval/worker can never disagree.
        return create_live_director(effort=creative_effort())

    # ------------------------------------------------------------- loop
    def run_once(self) -> bool:
        for candidate in self.store.queued():
            if not self.store.claim(candidate.idea_id):
                continue
            record: IdeaJobRecord | None = None
            try:
                record = self.store.get(candidate.idea_id)
                if record.status != IdeaStatus.QUEUED:
                    return True
                if record.stage == "planning":
                    self._plan(record)
                elif record.stage == "generating_assets":
                    self._assets(record)
                elif record.stage == "rendering":
                    self._render(record)
                else:
                    self._fail(record, "idea_stage_conflict", f"Stage desconhecido: {record.stage}")
                return True
            except Exception as exc:  # noqa: BLE001 - persisted as a structured job error
                logger.exception("idea_worker_failed idea_id=%s", candidate.idea_id)
                if record is not None:
                    self._fail(record, "idea_worker_error", f"{type(exc).__name__}: {exc}")
                return True
            finally:
                self.store.release(candidate.idea_id)
        return False

    # ------------------------------------------------------------- plan
    def _plan(self, record: IdeaJobRecord) -> None:
        approval = record.idea.approval(ApprovalScope.STORYBOARD)
        if approval is None:
            self._fail(record, "approval_required", "O storyboard não foi aprovado.")
            return
        if approval.brief_hash != brief_hash(record.idea.brief, record.idea.options):
            self._fail(record, "approval_stale", "O brief mudou desde a aprovação do storyboard.")
            return
        modes = idea_modes()
        if approval.provider_modes.get("director") != modes["director"]:
            self._fail(
                record,
                "provider_mode_mismatch",
                f"Storyboard aprovado em modo {approval.provider_modes.get('director')!r}, "
                f"worker em {modes['director']!r}.",
            )
            return
        if approval.provider_modes.get("effort", "medium") != modes["effort"]:
            self._fail(
                record,
                "provider_mode_mismatch",
                f"Storyboard aprovado com effort "
                f"{approval.provider_modes.get('effort', 'medium')!r}, worker em "
                f"{modes['effort']!r}. Cria um novo plano com o esforço atual.",
            )
            return

        record.status = IdeaStatus.PROCESSING
        record.stage = "planning"
        self.store.save(record)
        self.store.write_progress(
            record.idea_id, IdeaProgress(stage="planning", current=0, total=1)
        )

        cost = 0.0
        request_id: str | None = None
        try:
            director = self._director_factory(modes["director"])
            if modes["director"] == "mock":
                board = director.create_storyboard(record.idea.brief, record.idea.options)
            else:
                board, cost, request_id = create_storyboard_live(
                    director, record.idea.brief, record.idea.options, self.storage_root
                )
            validate_board_for_options(board, record.idea.brief, record.idea.options)
            # Engine vocabulary + motion: a board that animates nothing must
            # fail here, not after image spend and a 5-minute capture.
            validate_board_targets(board)
        except Exception as exc:  # noqa: BLE001 - surfaced with a stable code
            self._fail(record, "storyboard_failed", f"{type(exc).__name__}: {exc}")
            return

        record.idea.storyboard = board
        record.idea.storyboard_hash = storyboard_hash(board)
        record.idea.assets = build_assets(board, record.idea.options)
        record.idea.spent_usd = round(record.idea.spent_usd + cost, 6)
        record.idea.estimate = estimate_from_storyboard(
            board,
            record.idea.options,
            director_mode=modes["director"],
            image_mode=modes["image"],
            effort=modes["effort"],
        )
        if record.idea.spent_usd > approval.approved_usd + 1e-9:
            self.store.save(record)
            self._fail(
                record,
                "cost_cap_exceeded",
                f"O storyboard custou ${record.idea.spent_usd:.4f}; aprovado "
                f"${approval.approved_usd:.4f}.",
            )
            return
        if self.store.cancel_requested(record.idea_id) or record.cancel_requested:
            self._fail(record, "cancelled_by_user", "Plano cancelado pelo utilizador.")
            return
        note = f"Plano pronto ({len(board.scenes)} cenas"
        if request_id:
            note += f", request {request_id}"
        note += ")"
        self.store.clear_progress(record.idea_id)
        record.progress = None
        self.store.transition(
            record,
            status=IdeaStatus.AWAITING_APPROVAL,
            stage="awaiting_plan_approval",
            note=note,
        )

    # ----------------------------------------------------------- assets
    def _assets(self, record: IdeaJobRecord) -> None:
        approval = record.idea.approval(ApprovalScope.ASSETS)
        if approval is None:
            self._fail(record, "approval_required", "Os assets não foram aprovados.")
            return
        if approval.brief_hash != brief_hash(record.idea.brief, record.idea.options):
            self._fail(record, "approval_stale", "O brief mudou desde a aprovação dos assets.")
            return
        modes = idea_modes()
        for key in ("director", "image"):
            if approval.provider_modes.get(key) != modes[key]:
                self._fail(
                    record,
                    "provider_mode_mismatch",
                    f"Aprovação em {key}={approval.provider_modes.get(key)!r}, "
                    f"worker em {modes[key]!r}.",
                )
                return
        if record.idea.storyboard is None:
            self._fail(record, "idea_stage_conflict", "Ainda não existe storyboard.")
            return

        selected = set(approval.asset_ids)
        if not selected:
            self._render(record)
            return

        record.status = IdeaStatus.PROCESSING
        record.stage = "generating_assets"
        self.store.save(record)
        total = len(selected)
        done = 0
        try:
            provider = self._image_provider_factory(modes["image"])
        except Exception as exc:  # noqa: BLE001
            self._fail(record, "image_provider_unavailable", str(exc))
            return

        for index, asset in enumerate(record.idea.assets):
            if asset.asset_id not in selected:
                continue
            if self.store.cancel_requested(record.idea_id) or record.cancel_requested:
                self._fail(record, "cancelled_by_user", "Geração de imagens cancelada pelo utilizador.")
                return
            if asset.status == AssetStatus.GENERATED:
                done += 1
                continue
            if asset.status != AssetStatus.APPROVED:
                self._fail(
                    record,
                    "asset_not_approved",
                    f"O asset {asset.asset_id} não está aprovado (estado {asset.status.value}).",
                )
                return
            if approval.prompt_hashes.get(asset.asset_id) != asset.prompt_hash:
                self._fail(
                    record,
                    "approval_stale",
                    f"O prompt do asset {asset.asset_id} mudou desde a aprovação.",
                )
                return
            cost = asset_cost_usd(1, image_mode=modes["image"])
            if modes["image"] == "live":
                # The assets approval covers image calls only; the storyboard
                # cost was approved separately and already sits in spent_usd.
                spent_on_plates = sum(
                    item.cost_usd
                    for item in record.idea.assets
                    if item.status == AssetStatus.GENERATED
                )
                if spent_on_plates + cost > approval.approved_usd + 1e-9:
                    self._fail(
                        record,
                        "cost_cap_exceeded",
                        f"Imagens aprovadas até ${approval.approved_usd:.4f}; "
                        f"${spent_on_plates + cost:.4f} excede esse valor.",
                    )
                    return
                if record.idea.spent_usd + cost > cap_usd() + 1e-9:
                    self._fail(
                        record,
                        "cost_cap_exceeded",
                        f"Gasto acumulado excede o limite por vídeo (${cap_usd():.2f}).",
                    )
                    return
            tmp = self.store.tmp_dir(record.idea_id) / f"{asset.asset_id}-{index + 1}"
            if tmp.exists():
                self._fail(
                    record,
                    "asset_attempt_exists",
                    f"Já existe uma tentativa para {asset.asset_id}; um novo pedido exige nova aprovação.",
                )
                return
            self.store.write_progress(
                record.idea_id,
                IdeaProgress(stage="generating_assets", current=done, total=total),
            )
            authorization = (
                LiveCallAuthorization.from_storage(self.storage_root, "image")
                if modes["image"] == "live"
                else None
            )
            try:
                result = provider.generate(
                    prompt=asset.prompt,
                    orientation=asset.orientation,
                    output_dir=tmp,
                    job_id=record.idea_id,
                    authorization=authorization,
                )
            except Exception as exc:  # noqa: BLE001 - one attempt, no retry
                asset.status = AssetStatus.FAILED
                asset.error = f"{type(exc).__name__}: {exc}"[:500]
                self.store.save(record)
                self._fail(record, "asset_generation_failed", f"{asset.asset_id}: {exc}")
                return
            try:
                self._store_generated_asset(record, asset, result, cost)
            except Exception as exc:  # noqa: BLE001
                asset.status = AssetStatus.FAILED
                asset.error = str(exc)[:500]
                self.store.save(record)
                self._fail(record, "asset_validation_failed", f"{asset.asset_id}: {exc}")
                return
            record.idea.spent_usd = round(record.idea.spent_usd + cost, 6)
            self.store.save(record)
            done += 1

        self.store.write_progress(
            record.idea_id, IdeaProgress(stage="generating_assets", current=total, total=total)
        )
        self._render(record)

    def _store_generated_asset(self, record: IdeaJobRecord, asset, result, cost: float) -> None:
        source = Path(result.image_path)
        if not source.is_file():
            raise FileNotFoundError("O provider não escreveu a imagem esperada.")
        with Image.open(source) as image:
            image.load()
            if image.format != "PNG":
                raise ValueError(f"Formato {image.format!r}; esperado PNG.")
            width, height = image.size
        expected_portrait = asset.orientation == "portrait"
        if expected_portrait != (height > width):
            raise ValueError(
                f"Orientação {width}x{height} não corresponde a {asset.orientation}."
            )
        destination = self.store.asset_path(record.idea_id, asset.asset_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(".part")
        shutil.copyfile(source, partial)
        os.replace(partial, destination)
        asset.status = AssetStatus.GENERATED
        asset.filename = destination.name
        asset.sha256 = sha256_file(destination)
        asset.width = width
        asset.height = height
        asset.provider_name = result.provider_name
        asset.is_mock = bool(result.is_mock)
        asset.request_id = getattr(result, "request_id", None)
        asset.cost_usd = cost
        asset.error = None
        asset.generated_at = datetime.now(timezone.utc)

    # ----------------------------------------------------------- render
    def _render(self, record: IdeaJobRecord) -> None:
        board = record.idea.storyboard
        if board is None:
            self._fail(record, "idea_stage_conflict", "Ainda não existe storyboard para renderizar.")
            return
        try:
            # Fail fast: a board whose steps resolve to no motion would waste
            # a full capture only to trip the frozen-frame QA.
            validate_board_targets(board)
        except ValueError as exc:
            self._fail(
                record,
                "storyboard_static",
                f"O storyboard não produz movimento no motor de cenas ({exc}). "
                "Cria um novo plano — repetir o render reproduziria o mesmo vídeo estático.",
            )
            return
        version_number = len(record.idea.versions) + 1
        output_dir = self.store.render_dir(record.idea_id, version_number)
        output_dir.mkdir(parents=True, exist_ok=True)
        marker = output_dir / "storyboard.sha256"
        expected_hash = record.idea.storyboard_hash or storyboard_hash(board)
        if marker.is_file():
            try:
                previous = marker.read_text(encoding="utf-8").strip()
            except OSError:
                previous = ""
            if previous and previous != expected_hash:
                shutil.rmtree(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(expected_hash, encoding="utf-8")

        if record.cancel_requested or self.store.cancel_requested(record.idea_id):
            self._fail(record, "cancelled_by_user", "Render cancelado pelo utilizador.")
            return

        record.status = IdeaStatus.PROCESSING
        record.stage = "rendering"
        record.error = None
        self.store.save(record)
        self.store.write_progress(
            record.idea_id,
            IdeaProgress(stage="rendering", current=0, total=record.idea.options.frame_count),
        )

        asset_urls = {
            asset.asset_id: f"{self.api_url.rstrip('/')}/api/ideas/{record.idea_id}/assets/{asset.asset_id}"
            for asset in record.idea.assets
            if asset.status == AssetStatus.GENERATED
        }
        request = IdeaRenderRequest(
            idea_id=record.idea_id,
            storyboard=board,
            asset_urls=asset_urls,
            output_dir=output_dir,
            width=record.idea.options.width,
            height=record.idea.options.height,
            fps=record.idea.options.fps,
            studio_url=self.studio_url,
            keep_frames=os.environ.get("CLIPFORGE_KEEP_FRAMES", "0") == "1",
        )

        def on_progress(stage: str, current: int, total: int) -> None:
            self.store.write_progress(
                record.idea_id, IdeaProgress(stage=stage, current=current, total=total)
            )

        try:
            report = render_idea(
                request,
                on_progress=on_progress,
                is_cancelled=lambda: self.store.cancel_requested(record.idea_id),
            )
        except IdeaCancelled as exc:
            self._fail(record, exc.code, str(exc))
            return
        except IdeaRenderError as exc:
            self._quarantine(output_dir)
            self._fail(record, exc.code, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._quarantine(output_dir)
            self._fail(record, "render_failed", f"{type(exc).__name__}: {exc}")
            return

        version = RenderVersion(
            version=version_number,
            storyboard_hash=expected_hash,
            output_relative_path=str(
                (output_dir / "out.mp4").relative_to(self.store.root)
            ).replace("\\", "/"),
            output_sha256=report["output_sha256"],
            width=report["width"],
            height=report["height"],
            fps=report["fps"],
            frame_count=report["frame_count"],
            duration_seconds=report["duration_seconds"],
            qa=report["qa"],
            created_at=utc_now(),
            is_delivered=True,
        )
        record.idea.versions.append(version)
        record.status = IdeaStatus.COMPLETED
        record.stage = "completed"
        record.progress = None
        record.error = None
        self.store.clear_progress(record.idea_id)
        self.store.clear_cancel(record.idea_id)
        self.store.save(record)
        if request.keep_frames is False:
            shutil.rmtree(output_dir / "frames", ignore_errors=True)
        logger.info(
            "idea_render_verified idea_id=%s version=%d frames=%d sha256=%s",
            record.idea_id,
            version.version,
            version.frame_count,
            version.output_sha256,
        )

    def _quarantine(self, output_dir: Path) -> None:
        """Keep a failed MP4 for diagnosis, never for download."""
        source = output_dir / "out.mp4"
        if not source.is_file():
            return
        rejected = output_dir / "rejected"
        rejected.mkdir(parents=True, exist_ok=True)
        os.replace(source, rejected / "out.mp4")

    # ------------------------------------------------------------- fail
    def _fail(self, record: IdeaJobRecord, code: str, message: str) -> None:
        logger.warning("idea_failed idea_id=%s code=%s message=%s", record.idea_id, code, message)
        record.error = IdeaError(code=code[:60], message=message[:2000])
        record.progress = None
        self.store.clear_progress(record.idea_id)
        self.store.transition(
            record, status=IdeaStatus.FAILED, stage="failed", note=f"{code}: {message[:160]}"
        )
