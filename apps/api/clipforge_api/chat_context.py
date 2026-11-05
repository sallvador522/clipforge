"""Chat context: real project/job/idea facts for the conversational director.

The chat must answer questions from persisted records — never from model
memory. This module builds a small, non-sensitive snapshot from the stores:
project title/assets, job status and video facts, text overlays, timeline and
idea state. No media bytes, secrets or filesystem paths leave the server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from clipforge_contracts.project import AssetRecord

_QUESTION_STARTS = (
    "quantos",
    "quanto",
    "qual",
    "quais",
    "onde",
    "porque",
    "explica",
    "explique",
    "mostra",
    "diz-me",
    "diz me",
    "sabes",
    "entendeste",
    "percebeste",
    "percebes",
    "o que",
    "como",
)

_KIND_WORDS = {
    "video": ("video", "vídeo", "videos", "vídeos", "clipe", "clipes", "clip", "clips", "filme", "filmes"),
    "audio": ("audio", "áudio", "audios", "áudios", "som", "sons"),
    "image": ("imagem", "imagens", "foto", "fotos", "image", "images"),
    "text": ("texto", "textos", "legenda", "legendas", "srt", "vtt"),
    "graphics": ("grafico", "gráfico", "graficos", "gráficos", "svg"),
}

_PT_KIND = {
    "video": ("vídeo", "vídeos"),
    "audio": ("áudio", "áudios"),
    "image": ("imagem", "imagens"),
    "text": ("texto", "textos"),
    "graphics": ("gráfico", "gráficos"),
}

_MATERIALISATION_HINTS = (
    "quantos",
    "quanto",
    "qual",
    "quais",
    "quantidade",
    "list",
    "lista",
    "enumera",
    "recurso",
    "recursos",
    "projeto",
    "projecto",
    "asset",
    "assets",
    "itens",
    "items",
    "o que eu tenho",
    "o que tenho",
    "o que há",
    "o que ha",
    "existe",
    "existem",
    "tem",
    "têm",
    "te tenho",
    "havia",
    "há ",
    "ha ",
)


def norm_chat_text(text: str) -> str:
    value = " ".join(text.strip().lower().split())
    value = re.sub(r"[^a-z0-9áàâãçéêíóôõúü :/+_-]+", " ", value)
    return " ".join(value.split())


def is_direct_question(text: str) -> bool:
    message = " ".join(text.strip().lower().split())
    if not message:
        return False
    if "?" in message:
        return True
    return any(
        message == start or message.startswith(start + " ")
        for start in _QUESTION_STARTS
    )


def _asset_line(asset: AssetRecord) -> str:
    duration = (
        f"{asset.duration_seconds:.1f}s" if asset.duration_seconds else "sem duração"
    )
    size_mb = asset.size_bytes / 1_000_000
    if asset.width and asset.height:
        resolution = f"{asset.width}x{asset.height}"
    else:
        resolution = "sem resolução"
    fps = f"@{asset.fps:.0f}fps" if asset.fps else ""
    provenance = str(asset.provenance.value)
    return (
        f"{asset.original_filename} "
        f"({asset.kind.value}, {duration}, {resolution}{fps}, {size_mb:.1f} MB, {provenance})"
    )


def read_project_assets(projects, project_id: str | None) -> list[dict[str, Any]]:
    if not project_id:
        return []
    try:
        project = projects.get_project(project_id)
    except Exception:
        return []
    assets_root = projects.assets_dir(project.project_id)
    items: list[dict[str, Any]] = []
    if not assets_root.is_dir():
        return items
    for sidecar in sorted(assets_root.glob("*/asset.json"), key=lambda p: str(p)):
        try:
            asset = AssetRecord.model_validate_json(
                sidecar.read_text(encoding="utf-8")
            )
        except Exception:
            continue
        items.append(
            {
                "asset_id": asset.asset_id,
                "kind": asset.kind.value,
                "name": asset.original_filename,
                "provenance": str(asset.provenance),
                "line": _asset_line(asset),
                "sha256": asset.sha256,
                "analysis_summary": _cached_analysis_summary(
                    projects, project.project_id, asset.asset_id, asset.sha256
                ),
            }
        )
    # Fallback por conteúdo idêntico (mesmo projeto): um re-import ou uma
    # cópia de sessão gera outro asset_id com os mesmos bytes. Como a análise
    # descreve pixels — e está vinculada ao sha256 — é seguro reutilizar o
    # resumo dentro do mesmo projeto, sem nunca atravessar projetos.
    by_sha_summary: dict[str, dict[str, Any]] = {}
    for item in items:
        summary = item.get("analysis_summary")
        if isinstance(summary, dict) and isinstance(item.get("sha256"), str):
            by_sha_summary.setdefault(item["sha256"], summary)
    for item in items:
        if not isinstance(item.get("analysis_summary"), dict):
            reused = by_sha_summary.get(item.get("sha256", ""))
            if isinstance(reused, dict):
                item["analysis_summary"] = reused
    return items


def _cached_analysis_summary(
    projects, project_id: str, asset_id: str, sha256: str
) -> dict[str, Any] | None:
    """Compact, non-sensitive summary of a cached analysis for this exact asset version.

    Returns None when there is no analysis or it belongs to another version.
    Never raises: context building must not break chat on a corrupt sidecar.
    """
    try:
        path = projects.asset_dir(project_id, asset_id) / "analysis.json"
        if not path.is_file():
            return None
        import json as _json

        payload = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("source_sha256") != sha256:
        return None
    if payload.get("asset_id") != asset_id or payload.get("project_id") != project_id:
        return None
    summary = str(payload.get("overall_summary") or "").strip()[:600]
    opportunities = [
        str(item).strip()[:200]
        for item in (payload.get("editing_opportunities") or [])
        if str(item).strip()
    ][:6]
    moments = []
    for item in (payload.get("important_moments") or [])[:6]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()[:160]
        if not label:
            continue
        at_s = item.get("at_s")
        stamp = ""
        if isinstance(at_s, (int, float)) and at_s >= 0:
            stamp = f"{int(at_s // 60):02d}:{int(at_s % 60):02d} "
        moments.append(f"{stamp}{label}".strip())
    raw = str(payload.get("raw_text", ""))
    excerpt = " ".join(raw.strip().split())[:800]
    return {
        "analysis_id": str(payload.get("analysis_id", "")),
        "is_mock": bool(payload.get("is_mock", False)),
        "overall_summary": summary,
        "editing_opportunities": opportunities,
        "important_moments": moments,
        "created_at": str(payload.get("created_at", "")),
        "raw_excerpt": excerpt,
    }


def build_chat_context(
    *,
    projects,
    store,
    job_id: str | None = None,
    project_id: str | None = None,
    idea_id: str | None = None,
    idea_record=None,
    interview=None,
    history: list | None = None,
    selected_asset_id: str | None = None,
) -> dict[str, Any]:
    """Snapshot used by the local Q&A and the Spark conversation.

    Job records are resolved first because uploads link jobs to projects; the
    frontend may wake before the Studio has restored project_id.
    """

    job = None
    if job_id:
        try:
            job = store.get(job_id)
        except Exception:
            job = None
    effective_project_id = project_id or (job.project_id if job is not None else None)

    title = None
    mode = None
    if effective_project_id:
        try:
            project = projects.get_project(effective_project_id)
            title = project.title
            mode = project.mode.value
        except Exception:
            title = None
            mode = None

    assets = read_project_assets(projects, effective_project_id)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        by_kind.setdefault(asset["kind"], []).append(asset)

    # ADR-061: a seleção dos Recursos viaja com o turno, mas só vale se o
    # asset existir neste projeto. Seleção inexistente => None (o router
    # decide sem ela em vez de responder sobre o vídeo errado).
    resolved_selection: str | None = None
    if selected_asset_id:
        for asset in assets:
            if asset.get("asset_id") == selected_asset_id:
                asset["selected"] = True
                resolved_selection = selected_asset_id
                break

    source = job.source_info.model_dump() if job is not None else None
    duration_s = float(source["duration_seconds"]) if source else None
    aspect = None
    source_label = None
    if source:
        width = int(source["width"])
        height = int(source["height"])
        aspect = (
            "vertical"
            if height > width
            else "horizontal"
            if width > height
            else "square"
        )
        source_label = (
            f"{width}x{height} @ {source['fps']:.0f}fps, {duration_s:.1f}s"
        )
    result = job.result if job is not None else None
    render_status = result.render_status if result is not None else None
    render_label = "sem render"
    if render_status == "verified":
        render_label = "render verificado pronto"
    elif render_status == "awaiting_approval":
        render_label = "parado a aguardar aprovação"

    target_duration_s = (
        (interview.duration_s if interview is not None else None)
        or duration_s
    )

    timeline = None
    if job is not None and job.timeline is not None:
        clips = []
        for clip in job.timeline.clips:
            clips.append(
                {
                    "track": clip.track,
                    "asset_id": clip.asset_id,
                    "start_s": round(clip.timeline_start_s, 2),
                    "end_s": round(
                        clip.timeline_start_s
                        + (clip.source_out_s - clip.source_in_s),
                        2,
                    ),
                }
            )
        timeline = {"clips": clips, "duration_s": round(
            job.timeline.program_duration_s(), 2
        )}

    snapshot: dict[str, Any] = {
        "project": {
            "id": effective_project_id,
            "title": title,
            "mode": mode,
            "assets_total": len(assets),
            "assets_by_kind": {
                kind: len(items) for kind, items in by_kind.items()
            },
            "assets": assets,
            "selected_asset_id": resolved_selection,
        },
        "job": {
            "has_clip": job is not None,
            "title": title,
            "filename": job.original_filename if job is not None else None,
            "status": job.status.value if job is not None else None,
            "stage": job.stage if job is not None else None,
            "ready": job.ready if job is not None else False,
            "source_sha256": job.source_sha256 if job is not None else None,
            "source_label": source_label,
            "duration_s": duration_s,
            "aspect": aspect,
            "has_audio": source["has_audio"] if source else None,
            "frame_count": source["frame_count"] if source else None,
            "texts": [t.model_dump(mode="json") for t in (job.clip_texts or [])]
            if job is not None
            else [],
            "colour": job.colour.model_dump(mode="json") if job is not None else None,
            "caption_cover": job.caption_cover if job is not None else False,
            "trim": {
                "start_s": job.trim_start_s,
                "end_s": job.trim_end_s,
            }
            if job is not None
            else None,
            "timeline": timeline,
            "render_status": render_status,
            "render_label": render_label,
            "output_name": (
                job.result.rendered.output_relative_path.rsplit("/", 1)[-1]
                if job is not None
                and job.result
                and job.result.rendered
                else None
            ),
        },
        "target_duration_s": target_duration_s,
        "history": [
            {
                "role": getattr(turn, "role", turn.get("role") if isinstance(turn, dict) else "user"),
                "text": " ".join(
                    getattr(turn, "text", turn.get("text", "") if isinstance(turn, dict) else "").strip().split()
                )[:300],
            }
            for turn in (history or [])[-6:]
        ],
    }

    if idea_record is not None:
        state = idea_record.idea
        board = state.storyboard.model_dump(mode="json") if state.storyboard else None
        snapshot["idea"] = {
            "id": idea_record.idea_id,
            "status": idea_record.status.value,
            "stage": idea_record.stage,
            "brief": idea_record.idea.brief,
            "duration_s": (
                board.get("duration_ms", 0) / 1000.0 if board else None
            ),
            "scenes": [
                {
                    "number": index + 1,
                    "duration_s": scene.get("duration_ms", 0) / 1000.0,
                    "title": scene.get("title", ""),
                    "caption": scene.get("caption", ""),
                }
                for index, scene in enumerate(
                    (board.get("scenes", []) if board else [])[:6]
                )
            ],
            "assets": [
                {
                    "status": asset.status.value,
                    "orientation": asset.orientation,
                    "is_mock": asset.is_mock,
                    "has_image_call": bool(asset.prompt),
                }
                for asset in state.assets[:6]
            ],
            "render_version": (
                state.delivered_version().version if state.delivered_version() else None
            ),
        }
    elif idea_id is not None:
        snapshot["idea"] = {"id": idea_id, "missing": True}

    return snapshot


def _counts_line(snapshot: dict) -> str:
    counts = snapshot.get("project", {}).get("assets_by_kind", {})
    if not counts:
        return "0 assets"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


def context_for_prompt(snapshot: dict) -> str:
    """Prompt-safe rendering of the snapshot for the live conversation.

    No provider, ledger, environment variable names, paths or secrets are
    included here. The model must answer only from these facts.
    """

    project = snapshot.get("project", {})
    job = snapshot.get("job", {})
    idea = snapshot.get("idea")
    blocks: list[str] = []
    if project.get("title"):
        blocks.append(
            f"Projeto «{project['title']}» ({project.get('mode') or 'edit'}): "
            f"{project.get('assets_total', 0)} asset(s) [{_counts_line(snapshot)}]"
        )
    else:
        blocks.append(
            "Sem projeto carregado no contexto. Não inventes contagens de projeto."
        )
    if project.get("assets"):
        blocks.append(
            "Assets (máx. 12 listados): "
            + "; ".join(asset["line"] for asset in project["assets"][:12])
        )
        selected = _selected_video_asset(project)
        if selected is not None:
            has_analysis = isinstance(selected.get("analysis_summary"), dict)
            blocks.append(
                f"Vídeo selecionado nos Recursos: «{selected.get('name', selected.get('asset_id'))}»"
                + (" (com análise visual em cache)" if has_analysis else " (sem análise ainda)")
                + ". Responde sobre ESTE vídeo quando perguntarem «este vídeo»."
            )
        analysed = [
            asset for asset in project["assets"][:12]
            if isinstance(asset.get("analysis_summary"), dict)
        ]
        if selected is not None and isinstance(selected.get("analysis_summary"), dict):
            analysed = [selected] + [a for a in analysed if a is not selected]
        for asset in analysed[:3]:
            summary = asset["analysis_summary"]
            bits = []
            if summary.get("overall_summary"):
                bits.append(f"Resumo: {summary['overall_summary']}")
            if summary.get("important_moments"):
                bits.append("Momentos: " + "; ".join(summary["important_moments"][:4]))
            if summary.get("editing_opportunities"):
                bits.append("Melhorias: " + "; ".join(summary["editing_opportunities"][:4]))
            if not bits and summary.get("raw_excerpt"):
                bits.append(
                    "Texto integral do modelo (sem estrutura validada): "
                    + summary["raw_excerpt"]
                )
            if bits:
                mock_note = " (simulada)" if summary.get("is_mock") else ""
                blocks.append(
                    f"Análise visual de «{asset.get('name', asset.get('asset_id'))}»{mock_note}: "
                    + " ".join(bits)
                )
    if job.get("has_clip"):
        status = f"{job.get('status')}/{job.get('stage')}"
        lines = [
            f"Vídeo aberto: {job.get('filename')} ({job.get('source_label')}; "
            f"{job.get('aspect')}; áudio={'sim' if job.get('has_audio') else 'não'}; {status}; {job.get('render_label')})"
        ]
        if job.get("texts"):
            titles = ", ".join(
                f"«{overlay['text'][:40]}»" for overlay in job["texts"][:6]
            )
            lines.append(
                f"Textos no vídeo: {len(job['texts'])} ({titles})"
                + (f"; cobertura de legendas queimadas: {'ligada' if job.get('caption_cover') else 'desligada'}")
            )
        else:
            lines.append("Textos no vídeo: 0")
        timeline = job.get("timeline")
        if timeline and timeline.get("clips"):
            lines.append(
                f"Timeline: {len(timeline['clips'])} bloco(s), programa {timeline['duration_s']:.1f}s"
            )
        blocks.append(". ".join(lines) + ".")
    elif job.get("has_clip") is False and snapshot.get("idea") is None:
        blocks.append("Não tens um clipe de edição aberto neste momento.")

    if idea is not None and not idea.get("missing"):
        blocks.append(
            f"Ideia ativa «{idea.get('brief')}» ({idea.get('status')}/{idea.get('stage')}; "
            f"duração {idea.get('duration_s') or 0:.1f}s; {len(idea.get('scenes', []))} cena(s)"
            + (
                f"; storyboard: {', '.join(scene['title'] for scene in idea['scenes'] if scene.get('title'))}"
                if idea.get("scenes")
                else ""
            )
            + ")."
        )

    target = snapshot.get("target_duration_s")
    if target:
        blocks.append(f"Duração de referência atual: {target:.1f}s.")
    history = snapshot.get("history") or []
    if history:
        tail = " | ".join(
            f"{'Tu' if item['role'] == 'user' else 'Muse'}: {item['text']}"
            for item in history[-4:]
        )
        blocks.append("Conversa recente: " + tail)
    return "\n".join(blocks)[:4200]


def _wanted_kind(low: str) -> str | None:
    for kind, words in _KIND_WORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", low) for word in words):
            return kind
    return None


def _needs_project_answer(low: str) -> bool:
    hints = (
        "quantos",
        "quanto",
        "quais",
        "quais são",
        "quantidade",
        "projecto",
        "projeto",
        "assets",
        "asset",
        "recurso",
        "recursos",
        "o que eu tenho",
        "o que tenho",
        "o que há",
        "o que ha",
        "existe",
        "existem",
        "há ",
        "ha ",
    )
    return any(hint in low for hint in hints)


def _requests_visual_analysis(low: str) -> bool:
    triggers = (
        "analisa este video",
        "analisa este vídeo",
        "analisar este video",
        "analisar este vídeo",
        "analisa o video",
        "analisa o vídeo",
        "analisar o video",
        "analisar o vídeo",
        "analisa este clipe",
        "analisar este clipe",
        "o que se passa neste video",
        "o que se passa neste vídeo",
        "o que acontece neste video",
        "o que acontece neste vídeo",
        "descreve este video",
        "descreve este vídeo",
        "descreve o video",
        "descreve o vídeo",
        "sabes sobre",
        "conheces este video",
        "conheces este vídeo",
        "sobre oque",
        "sobre o que é",
        "oque é o video",
        "oque é o vídeo",
        "o que é o video",
        "o que é o vídeo",
        "fala-me deste video",
        "fala-me deste vídeo",
    )
    if any(trigger in low for trigger in triggers):
        return True
    # Qualquer conjugação de analisar (analisa/analise/analisar/analises/
    # analisares/analisado) é um pedido de análise visual — não há outra
    # análise no produto. Cobre os reportes 2026-11-05 ("analise o video
    # para mim", "estou a pedir para analisar", "quero que analises ele")
    # que caíam na entrevista de ideia por falta de trigger exato. O router
    # decide depois a partir de que asset responder; nunca cai no interview.
    if "analis" in low or "anális" in low:
        return True
    return False


def _asks_about_video_content(low: str) -> bool:
    if not is_direct_question(low):
        return False
    hints = (
        "o que acontece",
        "o que se passa",
        "do que se trata",
        "sobre o que",
        "o que mostra",
        "o que aparece",
        "quem aparece",
        "que pessoas",
        "descreve",
        "resume",
        "resumo",
        "acontece no video",
        "acontece no vídeo",
        "neste video",
        "neste vídeo",
        "neste clipe",
    )
    return any(hint in low for hint in hints)


def _analysis_target_name(project: dict, preferred_name: str | None = None) -> str:
    if preferred_name:
        return f"«{preferred_name}»"
    videos = [
        asset.get("name", asset.get("asset_id"))
        for asset in (project.get("assets") or [])
        if asset.get("kind") == "video"
    ]
    if videos:
        return f"«{videos[0]}»"
    return "um vídeo do projeto"


def _format_analysis_answer(asset: dict[str, Any], *, with_moments: bool) -> dict[str, Any]:
    summary = asset.get("analysis_summary") or {}
    parts = []
    overall = summary.get("overall_summary") or summary.get("raw_excerpt")
    if overall:
        parts.append(overall)
    if with_moments and summary.get("important_moments"):
        parts.append("Momentos: " + "; ".join(summary["important_moments"][:4]))
    if summary.get("editing_opportunities"):
        parts.append("Melhorias: " + "; ".join(summary["editing_opportunities"][:4]))
    mock_note = " (análise simulada)" if summary.get("is_mock") else ""
    return {
        "intent": "question",
        "reply": (
            f"No vídeo «{asset.get('name', asset.get('asset_id'))}»{mock_note}: "
            + " ".join(parts)
        )[:1500],
        "needs_confirmation": False,
        "pending_text": None,
        "pending_kind": None,
    }


def _analysis_needed_reply(project: dict, preferred_name: str | None = None) -> dict[str, Any]:
    target = _analysis_target_name(project, preferred_name)
    return {
        "intent": "question",
        "reply": (
            "Ainda não analisei esse vídeo — sem análise não adivinho o conteúdo. "
            f"Seleciona {target} e prime «Analisar vídeo» no painel Propriedades; "
            "eu vejo-o de verdade e depois respondo sobre o que lá está."
        ),
        "needs_confirmation": False,
        "pending_text": None,
        "pending_kind": None,
    }


def _ambiguous_video_reply(project: dict) -> dict[str, Any]:
    analysed = [
        asset for asset in (project.get("assets") or [])
        if isinstance(asset.get("analysis_summary"), dict)
    ]
    names = ", ".join(f"«{a.get('name', a.get('asset_id'))}»" for a in analysed[:4])
    return {
        "intent": "question",
        "reply": (
            f"Tenho análises de vários vídeos ({names}). "
            "Seleciona nos Recursos aquele sobre o qual queres perguntar e repete a pergunta — "
            "respondo só sobre o vídeo selecionado para não misturar conteúdos."
        ),
        "needs_confirmation": False,
        "pending_text": None,
        "pending_kind": None,
    }


def _selected_video_asset(project: dict) -> dict[str, Any] | None:
    """The Recursos selection, only when it is a video of this project."""
    selected_id = project.get("selected_asset_id")
    if not selected_id:
        return None
    for asset in project.get("assets") or []:
        if asset.get("asset_id") == selected_id and asset.get("kind") == "video":
            return asset
    return None


def _ranked_analyses(project: dict, job: dict) -> list[dict[str, Any]]:
    """Analysed assets ordered by reference strength (ADR-061).

    1. The asset explicitly selected in Recursos (never a silent guess: the
    user pointed at it). 2. The asset matching the open job's source bytes.
    3. Everything else, in library order. Summaries only ever come from
    assets of this project (built that way upstream).
    """
    assets = project.get("assets") or []
    analysed = [
        asset for asset in assets
        if isinstance(asset.get("analysis_summary"), dict)
    ]
    if not analysed:
        return []
    selected = _selected_video_asset(project)
    if selected is not None and isinstance(selected.get("analysis_summary"), dict):
        return [selected]
    job_sha = job.get("source_sha256")
    if job_sha:
        linked = [a for a in analysed if a.get("sha256") == job_sha]
        if linked:
            return linked
    return analysed


def _meta_history_question(low: str) -> bool:
    meta = (
        "entendeste a minha pergunta",
        "entendeste a pergunta",
        "percebeste a minha pergunta",
        "percebeste a pergunta",
        "a minha pergunta anterior",
        "pergunta anterior",
        "última pergunta",
        "ultima pergunta",
        "pergunta sobre o numero de videos",
        "pergunta de quantos videos",
    )
    return any(phrase in low for phrase in meta)


def answer_project_question(
    message: str,
    context: dict | None,
    *,
    has_clip: bool = False,
    has_texts: bool = False,
) -> dict | None:
    """Direct Q&A over the real context. Returns None when the message is not
    an informational question so the router can continue to proposals."""

    low = norm_chat_text(message)
    context = context or {}
    project = context.get("project", {})
    job = context.get("job", {})
    history = context.get("history") or []

    if _requests_visual_analysis(low) and not editorial_intent_verifiable(message):
        selected = _selected_video_asset(project)
        if selected is not None:
            if isinstance(selected.get("analysis_summary"), dict):
                return _format_analysis_answer(selected, with_moments=True)
            return _analysis_needed_reply(project, selected.get("name"))
        ranked = _ranked_analyses(project, job)
        if ranked:
            if len(ranked) == 1:
                return _format_analysis_answer(ranked[0], with_moments=True)
            lines = []
            for asset in ranked[:3]:
                summary = asset["analysis_summary"]
                text = summary.get("overall_summary") or summary.get("raw_excerpt") or "sem resumo"
                mock_note = " (simulada)" if summary.get("is_mock") else ""
                lines.append(f"«{asset.get('name', asset.get('asset_id'))}»{mock_note}: {text}")
                if summary.get("editing_opportunities"):
                    lines.append(
                        "Melhorias: " + "; ".join(summary["editing_opportunities"][:4])
                    )
                if summary.get("important_moments"):
                    lines.append(
                        "Momentos: " + "; ".join(summary["important_moments"][:4])
                    )
            return {
                "intent": "question",
                "reply": " ".join(lines)[:1500],
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
        return _analysis_needed_reply(project)

    if _asks_about_video_content(low):
        selected = _selected_video_asset(project)
        if selected is not None:
            if isinstance(selected.get("analysis_summary"), dict):
                return _format_analysis_answer(selected, with_moments=True)
            return _analysis_needed_reply(project, selected.get("name"))
        ranked = _ranked_analyses(project, job)
        if not ranked:
            return _analysis_needed_reply(project)
        if len(ranked) > 1:
            return _ambiguous_video_reply(project)
        asset = ranked[0]
        summary = asset["analysis_summary"]
        parts = []
        if summary.get("overall_summary"):
            parts.append(summary["overall_summary"])
        elif summary.get("raw_excerpt"):
            parts.append(summary["raw_excerpt"])
        if summary.get("important_moments"):
            parts.append(
                "Momentos: " + "; ".join(summary["important_moments"][:4])
            )
        mock_note = " (análise simulada)" if summary.get("is_mock") else ""
        return {
            "intent": "question",
            "reply": (
                f"No vídeo «{asset.get('name', asset.get('asset_id'))}»{mock_note}: "
                + " ".join(parts)
            )[:1500],
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }

    if _meta_history_question(low):
        prior = None
        for item in reversed(history):
            if item.get("role") != "user":
                continue
            candidate = str(item.get("text", "")).strip()
            if not candidate:
                continue
            # Studio pushes the current user bubble before the request, so the
            # same text repeated in history is the question being asked now.
            if candidate.lower() == message.strip().lower():
                continue
            prior = candidate
            break
        if prior:
            return {
                "intent": "question",
                "reply": (
                    f"Entendi: tinhas perguntado «{prior}». Não transformei isso numa edição."
                ),
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
        return {
            "intent": "question",
            "reply": (
                "Entendi: perguntaste sobre o projeto, não me pediste para editar. "
                "Diz-me o que queres contar, listar ou verificar e eu respondo com os dados reais."
            ),
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }

    if _needs_project_answer(low) or (
        "quantos" in low or "quanto" in low or ("qual" in low and "projeto" in low)
    ):
        assets = project.get("assets") or []
        counts = project.get("assets_by_kind") or {}
        total = int(project.get("assets_total") or 0)
        wanted = _wanted_kind(low)
        parts: list[str] = []
        if wanted:
            label_singular, label_plural = _PT_KIND.get(wanted, (wanted, wanted))
            count = int(counts.get(wanted, 0))
            parts.append(
                f"No projeto tens {count} {label_singular if count == 1 else label_plural}, "
                f"de um total de {total} asset(s) ({_counts_line(context)})."
            )
        elif total:
            parts.append(
                f"No projeto tens {total} asset(s) ({_counts_line(context)})."
            )
        else:
            parts.append("Ainda não tens assets neste projeto.")
        if assets:
            parts.append("Ex.: " + "; ".join(asset["line"] for asset in assets[:2]))
        if parts:
            return {
                "intent": "question",
                "reply": " ".join(parts[:2]),
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }

    if "selecion" in low and ("video" in low or "vídeo" in low or "clipe" in low or "qual" in low or "que" in low or "tenho" in low or "tens" in low):
        selected = _selected_video_asset(project)
        if selected is not None:
            analysed = isinstance(selected.get("analysis_summary"), dict)
            name = selected.get("name", selected.get("asset_id"))
            if analysed:
                return _format_analysis_answer(selected, with_moments=False)
            return {
                "intent": "question",
                "reply": (
                    f"Tens selecionado nos Recursos o {name}, ainda sem análise. "
                    "Prime «Analisar vídeo» no painel Propriedades e eu vejo-o de verdade."
                ),
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
        assets = project.get("assets") or []
        if assets:
            names = ", ".join(f"«{a.get('name', a.get('asset_id'))}»" for a in assets[:4])
            return {
                "intent": "question",
                "reply": (
                    f"Não tens nenhum vídeo selecionado nos Recursos. Tens: {names}. "
                    "Seleciona um e repete a pergunta."
                ),
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
        return {
            "intent": "question",
            "reply": "Não tens nenhum vídeo selecionado e o projeto ainda não tem assets.",
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }

    if any(phrase in low for phrase in ("que clipe", "qual o clipe", "qual é o vídeo", "nome do vídeo", "qual o ficheiro")):
        if job.get("has_clip"):
            clip = (
                f"O clipe aberto é «{job.get('filename')}» "
                f"({job.get('source_label')}, {job.get('status')}/{job.get('stage')})."
            )
        else:
            clip = "Não tens um clipe de edição aberto neste momento."
        return {
            "intent": "question",
            "reply": clip,
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }

    if any(
        phrase in low
        for phrase in (
            "o que foi feito",
            "o que já fizemos",
            "o que já foi feito",
            "o que fizemos",
            "estado do projeto",
            "onde estamos",
        )
    ):
        bits: list[str] = []
        if job.get("has_clip"):
            bits.append(
                f"Estás no projeto «{project.get('title') or 'sem título'}» "
                f"({project.get('mode') or 'edit'}), com o clipe «{job.get('filename')}» "
                f"({job.get('source_label')}; {job.get('status')}/{job.get('stage')}; "
                f"{job.get('render_label')}) e {len(job.get('texts', []))} texto(s)."
            )
        elif project.get("title"):
            bits.append(
                f"Estás no projeto «{project['title']}» ({project.get('mode') or 'edit'}), "
                f"com {project.get('assets_total', 0)} asset(s) ({_counts_line(context)}), "
                "sem um clipe de edição aberto."
            )
        else:
            bits.append("Ainda não há um projeto carregado neste turno.")
        idea = context.get("idea")
        if idea and not idea.get("missing"):
            bits.append(
                f"A ideia ativa é «{idea.get('brief')}» ({idea.get('status')}/{idea.get('stage')}; "
                f"{len(idea.get('scenes', []))} cena(s))."
            )
        return {
            "intent": "question",
            "reply": " ".join(bits),
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }

    if is_direct_question(low) and (
        job.get("has_clip") or project.get("title") or context.get("idea")
    ):
        if any(phrase in low for phrase in ("o que eu tenho", "o que tenho")):
            if job.get("has_clip"):
                return {
                    "intent": "question",
                    "reply": (
                        f"Tens o clipe «{job.get('filename')}» "
                        f"({job.get('source_label')}; {job.get('status')}/{job.get('stage')}) "
                        f"e {len(job.get('texts', []))} texto(s) no vídeo."
                    ),
                    "needs_confirmation": False,
                    "pending_text": None,
                    "pending_kind": None,
                }
            if project.get("title"):
                examples = "; ".join(asset["line"] for asset in project.get("assets", [])[:2])
                suffix = f" Ex.: {examples}" if examples else ""
                return {
                    "intent": "question",
                    "reply": (
                        f"No projeto «{project['title']}» tens {project.get('assets_total', 0)} asset(s) "
                        f"({_counts_line(context)}).{suffix}"
                    ),
                    "needs_confirmation": False,
                    "pending_text": None,
                    "pending_kind": None,
                }

    return None


_ACTIONABLE_NOUNS = (
    "fundo",
    "texto",
    "titulo",
    "título",
    "legenda",
    "legendas",
    "video",
    "vídeo",
    "clipe",
    "clip",
    "cor",
    "cores",
    "tamanho",
    "contraste",
    "brilho",
    "luminosidade",
    "saturacao",
    "saturação",
    "posicao",
    "posição",
    "animacao",
    "animação",
    "efeito",
    "transicao",
    "transição",
    "cena",
    "timeline",
    "audio",
    "áudio",
    "musica",
    "música",
    "projeto",
    "projecto",
    "moldura",
    "enquadramento",
)


def has_actionable_edit_signal(text: str) -> bool:
    """True when a message carries a recognizable edit verb or edit target.

    Gibberish ("HSDJS", "asdf") has neither, so the router must clarify
    instead of proposing execution. A bare target noun ("o fundo", "borra o
    fundo") still proposes — the director/approval flow judges the wording.
    """

    low = norm_chat_text(text)
    if not low:
        return False
    if editorial_intent_verifiable(text):
        return True
    return any(noun in low for noun in _ACTIONABLE_NOUNS)


def editorial_intent_verifiable(text: str) -> bool:
    """True when a pending message is a real edit instruction."""

    low = norm_chat_text(text)
    if not low:
        return False
    if is_direct_question(low):
        return False
    verbs = (
        "desfoca",
        "desfoque",
        "blur",
        "remove",
        "remover",
        "tira",
        "tirar",
        "troca",
        "trocar",
        "substitui",
        "substituir",
        "adiciona",
        "adicionar",
        "cria legendas",
        "legenda",
        "traduz",
        "traduza",
        "traduza",
        "acrescent",
        "corta",
        "corte",
        "muda",
        "mudar",
        "altera",
        "alterar",
        "aumenta",
        "aumentar",
        "reduz",
        "reduzir",
        "aument",
        "esconde",
        "monta",
        "text",
        "texto",
        "fundo",
        "legend",
    )
    return any(verb in low for verb in verbs)
