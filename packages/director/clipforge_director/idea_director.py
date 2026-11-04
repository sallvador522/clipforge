"""Creative Director for the idea-to-video product flow.

Two paths share the validated Storyboard contract:
- `MockIdeaDirector` builds a deterministic board from the brief and options.
  It never pretends to be a model: the API exposes `director_mode=mock` and the
  UI labels the plan as simulated.
- `create_storyboard_live` performs exactly one Muse Spark call through the
  existing one-shot authorization rails. No retries, no fallback.

Model output can only describe animation with allowlisted primitives; no code,
paths, URLs or arbitrary parameters ever leave the contract.
"""

from __future__ import annotations

import hashlib
import os

from clipforge_contracts.idea import IdeaAsset, IdeaOptions, scene_count_for
from clipforge_contracts.storyboard import AnimationStep, AssetSpec, SceneSpec, Storyboard
from clipforge_director.creative import CREATIVE_BRIEF, CreativeDirectorProvider
from clipforge_director.ledger import LiveCallAuthorization

MAX_PLATES = 6

CREATIVE_MODE_ENV = "CLIPFORGE_CREATIVE_DIRECTOR_MODE"
IDEA_IMAGE_MODE_ENV = "CLIPFORGE_IDEA_IMAGE_MODE"
CREATIVE_EFFORT_ENV = "CLIPFORGE_CREATIVE_DIRECTOR_EFFORT"

# Target ids the shared SceneRenderer understands. The engine looks elements
# up by `data-el` id, renders conditional elements only when targeted, and
# ignores camera/parallax targets (they always move the backdrop). A board
# that targets anything else animates nothing — the failure that produced a
# fully static 5 s scene and a qa_failed render. Targets are validated at
# plan time so a dead board fails fast instead of after a 5-minute capture.
ENGINE_ELEMENTS = frozenset(
    {
        "title",
        "line1",
        "line2",
        "line3",
        "line4",
        "line5",
        "conclusion",
        "counter",
        "grid",
        "orb",
        "particles",
        "asteroid",
        "plasma_trail",
        "shockwave",
        "flash",
        "divider",
        "chart",
    }
)

#: Primitives that ignore their target (they always move the backdrop layers).
CAMERA_PRIMITIVES = frozenset({"camera_zoom", "camera_pan", "parallax"})

#: Primitives bound to exactly one element id.
FIXED_TARGETS = {
    "flash": "flash",
    "counter": "counter",
    "chart_bar": "chart",
    "svg_draw": "divider",
    "gradient_shift": "bg",
}

#: Primitives that only make sense on on-screen text.
TEXT_ONLY_PRIMITIVES = frozenset(
    {"text_reveal", "kinetic_typography", "tracking", "mask_reveal"}
)

#: Easing vocabulary the scene engine executes (Anime.js 4.5 names).
#: Anything else is flattened to outQuad at render, so it is rejected here.
ENGINE_EASES = frozenset(
    {
        "linear",
        "inQuad",
        "outQuad",
        "inOutQuad",
        "outExpo",
        "outCirc",
        "outBack",
        "outElastic",
        "outBounce",
    }
)


def creative_effort() -> str:
    """Reasoning effort for the live storyboard call only.

    Verified values come from the Spark contract (`minimal`/`low`/`medium`/
    `high`/`xhigh`); anything else raises instead of silently downgrading a
    paid call. Applies exclusively to idea-to-video planning — the editing
    director, transcription, SAM and image providers are untouched.
    """
    from clipforge_director.spark import REASONING_EFFORTS

    effort = os.environ.get(CREATIVE_EFFORT_ENV, "medium").strip().lower()
    if effort not in REASONING_EFFORTS:
        raise RuntimeError(
            f"Unknown {CREATIVE_EFFORT_ENV}={effort!r}; verified values: "
            f"{sorted(REASONING_EFFORTS)}. No request was attempted."
        )
    return effort


def idea_modes() -> dict[str, str]:
    """Provider modes for the idea flow.

    Deliberately independent from the editing director/image switches and
    defaulting to `mock`: enabling the paid path is an explicit, documented
    action, never a side effect of another live mode. `effort` only affects
    the live storyboard call.
    """
    director = os.environ.get(CREATIVE_MODE_ENV, "mock").strip().lower()
    image = os.environ.get(IDEA_IMAGE_MODE_ENV, "mock").strip().lower()
    if director not in ("mock", "live"):
        director = "mock"
    if image not in ("mock", "live"):
        image = "mock"
    effort = "medium"
    if director == "live":
        # Loud on a typo: a bad effort with a live director raises instead of
        # silently planning at another effort. Mock flows never touch this.
        effort = creative_effort()
    return {"director": director, "image": image, "effort": effort}


_STYLE_LABELS = {
    "cinematic": "Documentário cinematográfico",
    "documentary": "Documentário",
    "product": "Apresentação de produto",
    "bold": "Manifesto visual",
}

_STYLE_BIBLES = {
    "cinematic": "Paleta escura, luz volumétrica, grão de filme, tipografia condensada, acento quente.",
    "documentary": "Tons naturais, contraste contido, textura documental, tipografia editorial, acento sóbrio.",
    "product": "Fundo limpo, superfícies suaves, luz de estúdio, tipografia geométrica, acento vivo.",
    "bold": "Alto contraste, cores saturadas, formas grandes, tipografia pesada, movimento rápido.",
}

_BEATS = {
    "cinematic": [
        ("O INÍCIO", "Tudo começa com uma ideia."),
        ("O CONFLITO", "O que está em jogo?"),
        ("O CLÍMAX", "O momento decisivo."),
        ("O DEPOIS", "O que fica connosco."),
    ],
    "documentary": [
        ("O PONTO DE PARTIDA", "Uma pergunta por responder."),
        ("O CONTEXTO", "O que já sabemos."),
        ("A DESCOBERTA", "O que muda a leitura."),
        ("O QUE FICA", "A conclusão, em aberto."),
    ],
    "product": [
        ("O PROBLEMA", "O obstáculo de todos os dias."),
        ("A SOLUÇÃO", "Uma forma mais simples."),
        ("O RESULTADO", "O que muda na prática."),
        ("O PRÓXIMO PASSO", "Experimenta tu."),
    ],
    "bold": [
        ("IMAGINA", "Uma ideia sem limites."),
        ("AGORA", "O momento é este."),
        ("SENTE", "O impacto é imediato."),
        ("PARTILHA", "Leva isto contigo."),
    ],
}

_VISUALS = [
    "Plano de abertura com profundidade, luz a atravessar o fundo e movimento lento de câmara.",
    "Plano intermédio com camadas em parallax e uma linha gráfica a desenhar-se.",
    "Plano de tensão com anel de choque a expandir-se e partículas a dispersar.",
    "Plano de fecho com composição limpa, divisor gráfico e tipografia em destaque.",
]


def _subject_from_brief(brief: str) -> str:
    cleaned = " ".join(brief.strip().split())
    for separator in (".", "?", "!", "\n"):
        cleaned = cleaned.split(separator)[0].strip()
    if not cleaned:
        cleaned = brief.strip()
    return cleaned[:40].upper()


def _scene_durations(total_ms: int, count: int) -> list[int]:
    base = total_ms // count
    durations = [base] * count
    durations[-1] += total_ms - sum(durations)
    return durations


def _steps_for(index: int, duration_ms: int) -> list[AnimationStep]:
    def at(fraction: float) -> int:
        return int(duration_ms * fraction)

    def dur(fraction: float) -> int:
        return max(600, int(duration_ms * fraction))

    camera = AnimationStep(
        primitive="camera_zoom" if index % 2 == 0 else "camera_pan",
        target="camera",
        start_ms=0,
        duration_ms=duration_ms,
        params=(
            {"from_scale": 1.0, "to_scale": 1.08}
            if index % 2 == 0
            else {"from_x": 0.48, "from_y": 0.5, "to_x": 0.52, "to_y": 0.46}
        ),
        ease="linear",
    )
    reveal = AnimationStep(
        primitive="kinetic_typography" if index == 0 else "text_reveal",
        target="title",
        start_ms=at(0.08),
        duration_ms=dur(0.34),
        ease="outQuad",
    )
    line = AnimationStep(
        primitive="fade",
        target="line1",
        start_ms=at(0.42),
        duration_ms=dur(0.26),
        ease="outQuad",
    )
    steps = [camera, reveal, line]
    if index == 1:
        steps.append(
            AnimationStep(
                primitive="svg_draw",
                target="divider",
                start_ms=at(0.30),
                duration_ms=dur(0.35),
                ease="linear",
            )
        )
    if index == 2:
        steps.extend(
            [
                AnimationStep(
                    primitive="shockwave_ring",
                    target="shockwave",
                    start_ms=at(0.20),
                    duration_ms=dur(0.55),
                    params={"from_r": 0.05, "to_r": 0.85},
                    ease="outQuad",
                ),
                AnimationStep(
                    primitive="particle_burst",
                    target="particles",
                    start_ms=at(0.25),
                    duration_ms=dur(0.5),
                    params={"count": 90},
                    ease="outQuad",
                ),
            ]
        )
    if index == 3:
        steps.append(
            AnimationStep(
                primitive="fade",
                target="line2",
                start_ms=at(0.60),
                duration_ms=dur(0.22),
                ease="outQuad",
            )
        )
        steps.append(
            AnimationStep(
                primitive="elastic_pop",
                target="line1",
                start_ms=at(0.30),
                duration_ms=dur(0.50),
                ease="outElastic",
            )
        )
    if index == 0:
        steps.append(
            AnimationStep(
                primitive="mask_reveal",
                target="title",
                start_ms=at(0.10),
                duration_ms=dur(0.40),
                ease="outExpo",
            )
        )
    # Never let a step overrun its scene (contract validation would reject it).
    for step in steps:
        if step.start_ms + step.duration_ms > duration_ms:
            step.duration_ms = max(100, duration_ms - step.start_ms)
    return steps


class MockIdeaDirector:
    """Deterministic, offline storyboard built from the brief and options."""

    provider_name = "mock-idea-director"
    execution_mode = "mock"

    def create_storyboard(self, brief: str, options: IdeaOptions) -> Storyboard:
        count = min(scene_count_for(options.duration_seconds), MAX_PLATES)
        durations = _scene_durations(options.duration_seconds * 1000, count)
        beats = _BEATS[options.style_preset]
        subject = _subject_from_brief(brief)
        orientation = "portrait" if options.aspect_ratio == "9:16" else "landscape"
        scenes: list[SceneSpec] = []
        assets: list[AssetSpec] = []

        for index in range(count):
            beat_title, beat_line = beats[index]
            title = subject if index == 0 else beat_title
            texts = [title, beat_line]
            if index >= 2:
                texts.append("Plano simulado localmente.")
            visual = _VISUALS[index]
            prompt = ""
            if options.use_generated_images:
                prompt = (
                    f"{visual} {_STYLE_BIBLES[options.style_preset]} "
                    f"{'Vertical 9:16' if orientation == 'portrait' else 'Horizontal 16:9'} composition, "
                    "no text, no letters, no watermark, no logos, no recognizable real people."
                )
                assets.append(
                    AssetSpec(
                        asset_id=f"asset_scene_{index + 1}",
                        scene_ids=[f"scene_{index + 1}"],
                        description=visual[:280],
                        orientation=orientation,  # type: ignore[arg-type]
                        style_tags=[options.style_preset],
                    )
                )
            scenes.append(
                SceneSpec(
                    scene_id=f"scene_{index + 1}",
                    duration_ms=durations[index],
                    narrative_purpose=beat_title.title(),
                    visual_description=visual,
                    image_generation_prompt=prompt,
                    foreground_elements=["title", "line1"] if index < 3 else ["title", "line1", "line2"],
                    background_elements=["gradient"],
                    on_screen_text=texts,
                    narration_segment="",
                    animation_sequence=_steps_for(index, durations[index]),
                    transition_in="fade" if index == 0 else "dissolve",
                    transition_out="cut" if index == count - 1 else "dissolve",
                    scientific_claims=[],
                    source_references=[],
                )
            )

        return Storyboard(
            project_title=subject.title()[:120],
            user_request=brief,
            target_audience="Público geral",
            tone=_STYLE_LABELS[options.style_preset],
            duration_seconds=options.duration_seconds,
            aspect_ratio=options.aspect_ratio,
            output_fps=options.fps,
            resolution=f"{options.width}x{options.height}",
            visual_style_bible=_STYLE_BIBLES[options.style_preset],
            scientific_assumptions=[
                "Plano gerado localmente em modo simulado (mock): não houve chamada a um modelo de IA."
            ],
            narration_script="",
            scenes=scenes,
            asset_plan=assets,
            source_references=[],
            music_and_sound_cues=[],
        )


def _stage_model_instructions(options: IdeaOptions) -> str:
    return (
        "STAGE MODEL (the exact engine that renders this board; design for it, not for imagination):\n"
        f"- Canvas {options.width}x{options.height} ({options.aspect_ratio}), origin top-left. "
        "Keep text inside 40 px margins. Title block lives at y≈10-30%; the bottom fifth holds "
        "conclusion/counter/chart/divider elements; section dividers sit at 86% height.\n"
        "- Mounted elements and their exact target ids: 'title' (first on-screen line, hook, biggest), "
        "'line1'..'line5' (later lines, only if that line exists), 'conclusion' (closing line, "
        "bottom), 'counter' (big number), 'chart' (3 bars), 'grid' (overlay), 'orb' (glow sphere), "
        "'particles' (burst host), 'asteroid' (rock), 'plasma_trail' (trail host), 'shockwave' (ring), "
        "'flash' (fullscreen), 'divider' (drawn rule). Conditional ones render only when targeted. "
        "Any other target id renders NOTHING and the board is rejected.\n"
        "- Motion dictionary (primitive: visual effect / key params): camera_zoom (slow push, "
        "from_scale→to_scale MUST differ, e.g. 1.0→1.15); camera_pan (drift, from_x/from_y→to_x/to_y "
        "MUST differ); parallax (layer drift across ALL backdrop layers at different speeds — multiplane when a foreground plate exists); text_reveal (rise+fade, text only); "
        "kinetic_typography (per-character cascade, text only); mask_reveal (clip-path wipe, text only); "
        "tracking (letterspacing settle, spread in em, text only); elastic_pop (scale bounce, pair with "
        "outElastic ease); shake (impact oscillation, amplitude px); flash (fullscreen blink, target "
        "'flash' only); shockwave_ring (expanding ring, from_r→to_r); particle_burst (burst, count); "
        "motion_path (point A→B travel); counter (number run, from→to MUST differ); chart_bar (bars grow, "
        "target 'chart' only); svg_draw (rule draw-on, target 'divider' only); fade/slide (basic moves); "
        "gradient_shift (backdrop hue drift in degrees, target 'bg' only, subtle over photos).\n"
        "- Easing vocabulary (only these execute, anything else is rejected): linear, inQuad, outQuad, "
        "inOutQuad, outExpo, outCirc, outBack, outElastic, outBounce. Elastic/bounce easings are MADE for "
        "elastic_pop and kinetic hits — use them, this is a motion piece, not a slideshow.\n"
        "- Timing grammar (rejected if violated): EVERY scene opens in motion (first moving step starts "
        "within 1000 ms) and NEVER ends static (motion runs into the final 500 ms); each scene carries "
        "AT LEAST 2 overlapping motion steps (stagger starts ≥200 ms apart, overlap their durations); "
        "across the video use AT LEAST 3 distinct primitives; vary the openers (never the same first "
        "primitive twice in a row); end cards are motion, not holds — keep a camera drifting under "
        "everything.\n"
    )


def options_instructions(options: IdeaOptions) -> str:
    """Developer-side instructions derived only from validated options."""
    return (
        f"- Exactly {scene_count_for(options.duration_seconds)} scenes.\n"
        f"- The scene duration_ms values MUST sum to exactly "
        f"{options.duration_seconds * 1000} (tolerance ±500 ms); any other total is "
        f"rejected and the plan is discarded — do not round scenes to neat "
        f"lengths.\n"
        f"- Aspect ratio {options.aspect_ratio} ({options.width}x{options.height}).\n"
        f"- Output FPS {options.fps}.\n"
        f"- Style preset: {options.style_preset}.\n"
        f"- Language for on-screen text: {options.language}.\n"
        "- 2 to 3 short on-screen text lines per scene; never more than 42 characters in the first line. "
        "Title is the hook (punchy), lines are support (short clauses).\n"
        "- At least one animation step per scene; all steps must fit inside the scene duration.\n"
        + _stage_model_instructions(options)
        + f"- At most {MAX_PLATES} image plates: at most ONE backdrop + ONE foreground per scene. "
        "The foreground renders as a bottom-anchored band (~62% height) drifting against the "
        "backdrop via parallax — request it with role 'foreground' only where depth pays "
        "(2-3 scenes, never by default everywhere): describe close foreground subjects with a "
        "simple dark upper area kept clear for text. "
        f"Generated images are {'enabled' if options.use_generated_images else 'disabled'}.\n"
        "- No code, paths, URLs, file names or arbitrary parameters anywhere in the storyboard."
    )


# Client-side wait bound per effort. Long reasoning legitimately takes
# minutes (a high call already outlived the old 60 s default); the gateway
# has its own limits, but the client must never be the first to give up.
EFFORT_TIMEOUT_SECONDS = {
    "high": 300.0,
    "xhigh": 600.0,
}


def create_live_director(effort: str = "medium") -> CreativeDirectorProvider:
    api_key = os.environ.get("MODEL_API_KEY", "")
    if not api_key.strip():
        raise RuntimeError(
            "CLIPFORGE_CREATIVE_DIRECTOR_MODE=live requires MODEL_API_KEY (server-side only). "
            "No request was attempted."
        )
    from clipforge_director.spark import REASONING_EFFORTS

    if effort not in REASONING_EFFORTS:
        raise RuntimeError(
            f"Unknown reasoning effort {effort!r}; verified values: "
            f"{sorted(REASONING_EFFORTS)}. No request was attempted."
        )
    return CreativeDirectorProvider(
        api_key,
        CREATIVE_BRIEF,
        "storyboard-only",
        model="muse-spark-1.3-contributor",
        reasoning_effort=effort,
        timeout_seconds=EFFORT_TIMEOUT_SECONDS.get(effort, 60.0),
        require_contributor=True,
        max_output_tokens=16000,
    )


def create_live_refinement_director(effort: str = "medium"):
    """Live refinement director on the same one-shot rails (ADR-036)."""
    api_key = os.environ.get("MODEL_API_KEY", "")
    if not api_key.strip():
        raise RuntimeError(
            "Refinement requires CLIPFORGE_CREATIVE_DIRECTOR_MODE=live and MODEL_API_KEY "
            "(server-side only). No request was attempted."
        )
    from clipforge_director.creative import RefinementDirectorProvider
    from clipforge_director.spark import REASONING_EFFORTS

    if effort not in REASONING_EFFORTS:
        raise RuntimeError(
            f"Unknown effort {effort!r}; verified values: {sorted(REASONING_EFFORTS)}. "
            "No request was attempted."
        )
    return RefinementDirectorProvider(
        api_key,
        "refinement",
        "storyboard-patch-only",
        model="muse-spark-1.3-contributor",
        reasoning_effort=effort,
        timeout_seconds=EFFORT_TIMEOUT_SECONDS.get(effort, 60.0),
        require_contributor=True,
        max_output_tokens=16000,
    )


def create_refinement_live(provider, board, instruction, storage_root, *, clarification_context=None):
    """One authorised refinement request. Returns (patch, cost_usd, request_id)."""
    authorization = LiveCallAuthorization.from_storage(storage_root, "director")
    patch = provider.create_patch(
        board,
        instruction,
        authorization=authorization,
        clarification_context=clarification_context,
    )
    usage = getattr(provider, "last_usage", None)
    cost = float(usage.cost_usd) if usage is not None else 0.0
    return patch, cost, getattr(provider, "last_request_id", None)


def create_storyboard_live(
    provider: CreativeDirectorProvider,
    brief: str,
    options: IdeaOptions,
    storage_root,
) -> tuple[Storyboard, float, str | None]:
    """One authorised storyboard request. Returns (board, cost_usd, request_id)."""
    authorization = LiveCallAuthorization.from_storage(storage_root, "director")
    board = provider.create_storyboard(
        brief,
        authorization=authorization,
        instructions=options_instructions(options),
    )
    usage = getattr(provider, "last_usage", None)
    cost = float(usage.cost_usd) if usage is not None else 0.0
    return board, cost, getattr(provider, "last_request_id", None)


def validate_overlay_assets(board: Storyboard, generated_ids: set[str]) -> list[str]:
    """Overlay ids whose image plate is not generated (fail closed at render)."""
    return [
        overlay.overlay_id
        for overlay in (board.overlays or [])
        if overlay.kind == "image"
        and (not overlay.asset_id or overlay.asset_id not in generated_ids)
    ]


def validate_board_for_options(board: Storyboard, brief: str, options: IdeaOptions) -> None:
    """Reject a live board that ignores the approved project options."""
    if board.user_request.strip() != brief.strip():
        raise ValueError("Storyboard user_request must echo the brief verbatim.")
    # ADR-036: duration is NOT checked here. The director's delivered scene
    # durations are authoritative and Storyboard derives duration_seconds
    # from them; diverging from the requested duration never rejects a board.
    if board.aspect_ratio != options.aspect_ratio:
        raise ValueError(
            f"Storyboard aspect ratio is {board.aspect_ratio}; approved options require "
            f"{options.aspect_ratio}."
        )
    if board.output_fps != options.fps:
        raise ValueError(
            f"Storyboard fps is {board.output_fps}; approved options require {options.fps}."
        )
    if len(board.asset_plan) > MAX_PLATES:
        raise ValueError(f"Storyboard requests {len(board.asset_plan)} plates; max is {MAX_PLATES}.")
    known_scenes = {scene.scene_id for scene in board.scenes}
    scene_roles: dict[str, list[str]] = {}
    for spec in board.asset_plan:
        for scene_id in spec.scene_ids:
            if scene_id not in known_scenes:
                raise ValueError(
                    f"Asset {spec.asset_id} references unknown {scene_id}."
                )
            scene_roles.setdefault(scene_id, []).append(spec.role)
    for scene_id, roles in scene_roles.items():
        if len(roles) > 2 or len(set(roles)) != len(roles):
            raise ValueError(
                f"{scene_id}: at most one backdrop + one foreground plate."
            )


def _num(params: dict, key: str, default: float, scene_id: str, primitive: str) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(
            f"{scene_id}: {primitive} param {key!r} must be numeric, "
            f"got {params.get(key)!r}."
        )


def _step_moves(step_params: dict, primitive: str, scene_id: str) -> bool:
    """Whether a step visibly changes anything (guards against no-op params)."""
    if primitive == "camera_zoom":
        return _num(step_params, "from_scale", 1.0, scene_id, primitive) != _num(
            step_params, "to_scale", 1.1, scene_id, primitive
        )
    if primitive == "camera_pan":
        return (
            _num(step_params, "from_x", 0.5, scene_id, primitive),
            _num(step_params, "from_y", 0.5, scene_id, primitive),
        ) != (
            _num(step_params, "to_x", 0.5, scene_id, primitive),
            _num(step_params, "to_y", 0.5, scene_id, primitive),
        )
    if primitive == "counter":
        return _num(step_params, "from", 0, scene_id, primitive) != _num(
            step_params, "to", 100, scene_id, primitive
        )
    if primitive == "shockwave_ring":
        return _num(step_params, "from_r", 0.05, scene_id, primitive) != _num(
            step_params, "to_r", 0.9, scene_id, primitive
        )
    if primitive == "motion_path":
        return (
            _num(step_params, "from_x", 0, scene_id, primitive),
            _num(step_params, "from_y", 0, scene_id, primitive),
        ) != (
            _num(step_params, "to_x", 1, scene_id, primitive),
            _num(step_params, "to_y", 1, scene_id, primitive),
        )
    if primitive == "particle_burst":
        try:
            return int(step_params.get("count", 60)) > 0
        except (TypeError, ValueError):
            raise ValueError(
                f"{scene_id}: particle_burst param 'count' must be numeric, "
                f"got {step_params.get('count')!r}."
            )
    # fade, slide, text_reveal, kinetic_typography, flash, chart_bar,
    # svg_draw and parallax always interpolate while their element exists.
    return True


def validate_board_targets(board: Storyboard) -> None:
    """Reject steps the scene engine cannot resolve into motion.

    The renderer looks elements up by exact `data-el` id and only mounts
    conditional elements when targeted; unknown ids animate nothing. A scene
    with no motion-producing step renders as a static hold and trips the
    frozen-frame QA after a full capture — so it fails here, in seconds,
    before any image spend or render.
    """
    for scene in board.scenes:
        motion: list[tuple[int, int]] = []
        for step in scene.animation_sequence:
            primitive = getattr(step.primitive, "value", step.primitive)
            target = step.target
            if step.ease not in ENGINE_EASES:
                raise ValueError(
                    f"{scene.scene_id}: unknown ease {step.ease!r} for {primitive}. "
                    f"Use one of: {sorted(ENGINE_EASES)}."
                )
            if primitive in CAMERA_PRIMITIVES:
                if _step_moves(step.params, primitive, scene.scene_id):
                    motion.append((step.start_ms, step.start_ms + step.duration_ms))
                continue
            expected = FIXED_TARGETS.get(primitive)
            if expected is not None:
                if target != expected:
                    raise ValueError(
                        f"{scene.scene_id}: {primitive} must target {expected!r}, "
                        f"got {target!r}. Nothing would render."
                    )
                motion.append((step.start_ms, step.start_ms + step.duration_ms))
                continue
            if target not in ENGINE_ELEMENTS:
                raise ValueError(
                    f"{scene.scene_id}: unknown target {target!r} for {primitive}. "
                    f"Use one of: {sorted(ENGINE_ELEMENTS)}."
                )
            if primitive in TEXT_ONLY_PRIMITIVES or target == "title" or target.startswith("line"):
                if target == "title" and not scene.on_screen_text:
                    raise ValueError(f"{scene.scene_id}: target 'title' with no on-screen text.")
                if target.startswith("line"):
                    try:
                        line_index = int(target[4:])
                    except ValueError:
                        line_index = -1
                    if line_index < 1 or line_index >= len(scene.on_screen_text):
                        raise ValueError(
                            f"{scene.scene_id}: target {target!r} has no text line "
                            f"({len(scene.on_screen_text)} line(s) in the scene)."
                        )
            if primitive in ("shake", "gradient_shift", "tracking"):
                key = {"shake": "amplitude", "gradient_shift": "degrees", "tracking": "spread"}[
                    primitive
                ]
                default = {"shake": 12, "gradient_shift": 50, "tracking": 0.35}[primitive]
                _num(step.params, key, default, scene.scene_id, primitive)
            if _step_moves(step.params, primitive, scene.scene_id):
                motion.append((step.start_ms, step.start_ms + step.duration_ms))
        if len(motion) < 2:
            raise ValueError(
                f"{scene.scene_id}: needs at least 2 motion-producing steps "
                f"(has {len(motion)}); overlap them, never a single lonely move."
            )
        if min(start for start, _ in motion) > 1000:
            raise ValueError(
                f"{scene.scene_id}: motion starts too late; the opening must move "
                f"within the first second, never a dead hold."
            )
        if max(end for _, end in motion) < scene.duration_ms - 500:
            raise ValueError(
                f"{scene.scene_id}: motion ends too early; keep moving into the "
                f"last 500 ms, never a static tail."
            )

    distinct = {
        getattr(step.primitive, "value", step.primitive)
        for scene in board.scenes
        for step in scene.animation_sequence
    }
    if len(distinct) < 3:
        raise ValueError(
            f"Storyboard reuses only {sorted(distinct)}; use at least 3 distinct "
            f"primitives across the video, not one move on repeat."
        )


def _asset_prompt(spec: AssetSpec, board: Storyboard, options: IdeaOptions) -> str:
    orientation = "Vertical 9:16" if options.aspect_ratio == "9:16" else "Horizontal 16:9"
    fallback = (
        "Cinematic foreground band, large close subjects"
        if spec.role == "foreground"
        else "Cinematic scene background"
    )
    description = (spec.description.strip() or fallback).rstrip(".")
    if spec.role == "foreground":
        composition = (
            f"{orientation} foreground band for the lower frame: large close subjects, "
            "simple dark upper area kept clear for text"
        )
    else:
        composition = f"{orientation} composition"
    prompt = (
        f"{description}. {board.visual_style_bible.strip()} {composition}. "
        "No text, no letters, no watermark, no logos, no recognizable real people."
    )
    return " ".join(prompt.split())[:880]


def build_assets(board: Storyboard, options: IdeaOptions) -> list[IdeaAsset]:
    """Turn the validated asset plan into job-local asset records.

    Multiplane: at most one backdrop + one foreground band per scene, at most
    MAX_PLATES total. Prompts are built here, server-side; the model never
    supplies a final prompt or any parameter.
    """
    if not options.use_generated_images:
        return []
    orientation = "portrait" if options.aspect_ratio == "9:16" else "landscape"
    assets: list[IdeaAsset] = []
    scene_roles: dict[str, set[str]] = {}
    for spec in board.asset_plan:
        if len(assets) >= MAX_PLATES:
            break
        if any(spec.role in scene_roles.get(scene_id, set()) for scene_id in spec.scene_ids):
            continue
        prompt = _asset_prompt(spec, board, options)
        assets.append(
            IdeaAsset(
                asset_id=spec.asset_id,
                scene_ids=list(spec.scene_ids),
                prompt=prompt,
                prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                orientation=orientation,  # type: ignore[arg-type]
                role=spec.role,  # type: ignore[arg-type]
            )
        )
        for scene_id in spec.scene_ids:
            scene_roles.setdefault(scene_id, set()).add(spec.role)
    return assets
