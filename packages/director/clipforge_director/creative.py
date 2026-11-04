"""Creative Director for idea-to-video projects (post-MVP cinematic mode).

Two paths share one validated contract:
- MockCreativeDirector: deterministic fixture storyboard for tests and
  offline development. No network, no billing.
- CreativeDirectorProvider: live Muse Spark storyboard planning through the
  same single-POST, no-retry rails as the editing director. Responses are
  validated as Storyboard; animation stays inside the allowlisted primitives.
"""

from __future__ import annotations

import hashlib
from typing import Any

from clipforge_contracts import TranscriptResult
from clipforge_contracts.storyboard import AnimationPrimitive, Storyboard
from clipforge_director.spark import (
    DirectorValidationError,
    LiveCallAuthorization,
    LiveCallNotAuthorizedError,
    MetaEditingDirectorProvider,
)

CREATIVE_BRIEF = """You are ClipForge Creative Director for idea-to-video projects.
Return ONLY a JSON Storyboard matching the provided schema. Rules:
- Animation uses ONLY the allowlisted primitives; never emit code or scripts.
- Scene durations sum exactly to the project duration.
- Scientific claims need source references; never invent precise energies or
  death tolls without labelled assumptions. When impact size, speed,
  composition or location materially changes the scenario, ask one focused
  clarification OR label assumptions explicitly and keep them conservative.
- On-screen text is short; images carry no embedded text (typography renders separately).
- Each scene has at least one animation step; steps must fit the scene duration.
- The user_request field must echo the user's idea verbatim.
- SIGNATURE TEXT STYLES (use these 5 to make typography cinematic — pick the
  one that fits the beat, never invent a sixth):
  1. Fundido a subir: text slide rise + fade, ease outQuad.
  2. Revelacao: mask_reveal clip-path wipe, ease inOutQuad.
  3. Pop: elastic_pop scale 0.6→1, ease outBack (outElastic for extra bounce).
  4. Cinetico: kinetic_typography per-character cascade, ease outExpo.
  5. Tracking: tracking letterspacing settle, ease outQuad.
"""


def storyboard_request_id(idea: str) -> str:
    # Pattern-compatible with DirectorAudit.request_id (^req_[a-z0-9]{8,32}$).
    return "req_sb" + hashlib.sha256(idea.encode()).hexdigest()[:10]


class MockCreativeDirector:
    """Deterministic fixture director. Offline only."""

    provider_name = "mock-creative-director"
    execution_mode = "mock"

    def __init__(self, storyboard: Storyboard | None = None) -> None:
        self._storyboard = storyboard or asteroid_reels_storyboard()

    def create_storyboard(self, idea: str) -> Storyboard:
        board = self._storyboard.model_copy(deep=True)
        return board.model_copy(update={"user_request": idea})


class CreativeDirectorProvider(MetaEditingDirectorProvider):
    """Live Muse Spark storyboard planning. Single POST, no retries."""

    provider_name = "meta-muse-spark-creative-director"
    wire_schema = "storyboard"

    def _wire_schema(self) -> dict[str, Any]:
        return Storyboard.model_json_schema()

    def _schema_name(self) -> str:
        return "Storyboard"

    def _validate_content(
        self,
        content: str,
        expected_request_id: str,
        transcript: TranscriptResult,
        server_request_id: str | None = None,
    ) -> Storyboard:
        import json

        try:
            raw = json.loads(content)
        except ValueError as exc:
            raise DirectorValidationError(
                "Storyboard content is not valid JSON.", server_request_id, category="invalid_json"
            ) from exc
        try:
            board = Storyboard.model_validate(raw)
        except Exception as exc:
            raise DirectorValidationError(
                f"Storyboard failed validation: {exc}",
                server_request_id,
                category="validation",
            ) from exc
        if board.user_request != transcript.text:
            raise DirectorValidationError(
                "Storyboard user_request must echo the idea verbatim.",
                server_request_id,
                category="idea_mismatch",
            )
        return board

    def create_storyboard(
        self,
        idea: str,
        *,
        request_id: str | None = None,
        authorization: LiveCallAuthorization | None = None,
        instructions: str | None = None,
    ) -> Storyboard:
        """Generate exactly one storyboard via a single Chat Completions call.

        `instructions` carries validated project options (duration, aspect,
        fps, style). It is appended to the developer playbook, never to the
        user message, so `user_request` still echoes the brief verbatim.
        """
        import httpx

        from clipforge_director.spark import (
            CHAT_COMPLETIONS_PATH,
            DirectorAPIError,
            DirectorRateLimitedError,
            DirectorTimeoutError,
            DirectorValidationError,
            DirectorValidationStatus,
            SparkDirectorError,
            build_developer_prompt,
        )

        if not isinstance(authorization, LiveCallAuthorization):
            raise LiveCallNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live storyboard request. "
                "No request was attempted."
            )
        transcript = TranscriptResult(text=idea, language="pt-BR", provider_name="user", is_mock=False)
        expected_request_id = request_id or storyboard_request_id(idea)
        playbook = CREATIVE_BRIEF
        if instructions:
            playbook = f"{CREATIVE_BRIEF}\n\nPROJECT OPTIONS (must obey):\n{instructions}"
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "developer",
                    "content": build_developer_prompt(
                        playbook_text=playbook,
                        capability_summary="storyboard-only",
                    ),
                },
                {"role": "user", "content": idea},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": self._schema_name(), "schema": self._wire_schema(), "strict": False},
            },
            "max_completion_tokens": self._max_output_tokens,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        self.last_usage = None
        self.last_request_id = expected_request_id
        self.last_server_request_id = None
        self.last_audit = self._new_audit(expected_request_id)
        try:
            authorization.reserve()
        except Exception as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="budget_refused",
                error_code=type(exc).__name__,
            )
            raise
        try:
            response = self._client.post(
                CHAT_COMPLETIONS_PATH,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="timeout",
                error_code=type(exc).__name__,
            )
            raise DirectorTimeoutError(
                f"Storyboard request timed out after {self._timeout_seconds:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="transport",
                error_code=type(exc).__name__,
            )
            raise SparkDirectorError("Could not reach the storyboard service.") from exc
        server_request_id = response.headers.get("x-request-id")
        self.last_server_request_id = server_request_id
        if response.status_code == 429:
            self._update_audit(
                server_request_id=server_request_id,
                http_status=response.status_code,
                validation_status=DirectorValidationStatus.ERROR,
                error_category="rate_limited",
                error_code="DirectorRateLimitedError",
            )
            raise DirectorRateLimitedError(
                "Storyboard is rate limited. No automatic retry was attempted.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            message, _ = self._safe_error(response)
            self._update_audit(
                server_request_id=server_request_id,
                http_status=response.status_code,
                validation_status=DirectorValidationStatus.ERROR,
                error_category="api_error",
                error_code="DirectorAPIError",
            )
            raise DirectorAPIError(
                response.status_code, f"Storyboard failed with HTTP {response.status_code}: {message}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DirectorAPIError(502, "Storyboard returned invalid JSON.") from exc
        self.last_usage = self._record_usage(body)
        self._update_audit(
            server_request_id=server_request_id,
            http_status=response.status_code,
            prompt_tokens=self.last_usage.prompt_tokens,
            completion_tokens=self.last_usage.completion_tokens,
            total_tokens=self.last_usage.total_tokens,
            estimated_cost_usd=self.last_usage.cost_usd,
        )
        try:
            content = self._extract_content(body, server_request_id)
            board = self._validate_content(content, expected_request_id, transcript, server_request_id)
        except DirectorValidationError as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.REJECTED,
                error_category=exc.category,
                error_code=type(exc).__name__,
            )
            raise
        self._update_audit(validation_status=DirectorValidationStatus.ACCEPTED)
        return board


def asteroid_reels_storyboard() -> Storyboard:
    """PoC fixture: 20 s, 9:16 asteroid-impact storyboard (4 scenes, 5 s each)."""
    return Storyboard.model_validate(
        {
            "project_title": "E se um asteroide gigante atingisse a Terra?",
            "user_request": "PLACEHOLDER_IDEA",
            "target_audience": "Curious general audience",
            "tone": "Cinematic scientific documentary",
            "duration_seconds": 20,
            "aspect_ratio": "9:16",
            "output_fps": 24,
            "resolution": "720x1280",
            "visual_style_bible": "Dark space blues, ember orange accents, volumetric light, film grain, bold condensed typography.",
            "scientific_assumptions": [
                "Impactor ~1 km stony asteroid at ~20 km/s, ocean-adjacent land strike; labelled as illustrative assumptions."
            ],
            "narration_script": "Narration recorded by the user; captions render on screen.",
            "scenes": [
                {
                    "scene_id": "scene_1",
                    "duration_ms": 5000,
                    "narrative_purpose": "Hook: a silent rock crossing the dark.",
                    "visual_description": "Starfield with Earth small below; asteroid enters on a motion path.",
                    "image_generation_prompt": "Deep space starfield, small blue Earth below, dark rocky asteroid, cinematic, vertical 9:16, no text",
                    "foreground_elements": ["asteroid"],
                    "background_elements": ["starfield", "earth"],
                    "on_screen_text": ["UM VISITANTE SILENCIOSO"],
                    "narration_segment": "",
                    "animation_sequence": [
                        {"primitive": "motion_path", "target": "asteroid", "start_ms": 0, "duration_ms": 4500, "params": {"from_x": 0.85, "from_y": -0.1, "to_x": 0.45, "to_y": 0.55}, "ease": "inQuad"},
                        {"primitive": "kinetic_typography", "target": "title", "start_ms": 500, "duration_ms": 1500},
                        {"primitive": "camera_zoom", "target": "camera", "start_ms": 0, "duration_ms": 5000, "params": {"from_scale": 1.0, "to_scale": 1.15}},
                    ],
                    "transition_in": "fade",
                    "transition_out": "dissolve",
                    "scientific_claims": ["Most asteroids are rocky bodies orbiting the Sun."],
                    "source_references": ["NASA CNEOS overview"],
                },
                {
                    "scene_id": "scene_2",
                    "duration_ms": 5000,
                    "narrative_purpose": "Atmospheric entry: compression heats the air.",
                    "visual_description": "Asteroid streaks over the limb of Earth, plasma trail and particles.",
                    "image_generation_prompt": "Asteroid entering Earth atmosphere with glowing plasma trail over ocean, cinematic vertical 9:16, no text",
                    "foreground_elements": ["asteroid", "plasma_trail"],
                    "background_elements": ["earth_limb", "clouds"],
                    "on_screen_text": ["20 KM/S", "O AR INCENDEIA-SE"],
                    "narration_segment": "",
                    "animation_sequence": [
                        {"primitive": "motion_path", "target": "asteroid", "start_ms": 0, "duration_ms": 3500, "params": {"from_x": 0.1, "from_y": 0.1, "to_x": 0.7, "to_y": 0.6}, "ease": "inQuad"},
                        {"primitive": "particle_burst", "target": "plasma_trail", "start_ms": 800, "duration_ms": 2700, "params": {"count": 120}},
                        {"primitive": "flash", "target": "flash", "start_ms": 3300, "duration_ms": 700},
                    ],
                    "transition_in": "dissolve",
                    "transition_out": "cut",
                    "scientific_claims": ["Entry speed converts kinetic energy into heat and light."],
                    "source_references": [],
                },
                {
                    "scene_id": "scene_3",
                    "duration_ms": 5000,
                    "narrative_purpose": "Impact: flash and shockwave ring.",
                    "visual_description": "Blinding flash on the horizon, expanding shockwave ring over terrain.",
                    "image_generation_prompt": "Asteroid impact flash on horizon with expanding dust ring, dramatic vertical 9:16, no text",
                    "foreground_elements": ["shockwave"],
                    "background_elements": ["terrain", "sky"],
                    "on_screen_text": ["IMPACTO"],
                    "narration_segment": "",
                    "animation_sequence": [
                        {"primitive": "flash", "target": "flash", "start_ms": 0, "duration_ms": 1200},
                        {"primitive": "shockwave_ring", "target": "shockwave", "start_ms": 400, "duration_ms": 3000, "params": {"from_r": 0.05, "to_r": 0.9}},
                        {"primitive": "camera_pan", "target": "camera", "start_ms": 0, "duration_ms": 5000, "params": {"from_x": 0.5, "from_y": 0.5, "to_x": 0.5, "to_y": 0.42}},
                    ],
                    "transition_in": "cut",
                    "transition_out": "dissolve",
                    "scientific_claims": ["Effects depend on size, composition, velocity and location."],
                    "source_references": [],
                },
                {
                    "scene_id": "scene_4",
                    "duration_ms": 5000,
                    "narrative_purpose": "Conclusion: scale infographic and sources.",
                    "visual_description": "Dark chart backdrop, animated counter and bars comparing impactors.",
                    "image_generation_prompt": "Dark scientific infographic backdrop with subtle grid, vertical 9:16, no text",
                    "foreground_elements": ["chart", "counter"],
                    "background_elements": ["grid"],
                    "on_screen_text": ["TAMANHO IMPORTA", "Fontes na descricao"],
                    "narration_segment": "",
                    "animation_sequence": [
                        {"primitive": "counter", "target": "counter", "start_ms": 300, "duration_ms": 2500, "params": {"from": 0, "to": 1000, "unit": "m"}},
                        {"primitive": "chart_bar", "target": "chart", "start_ms": 800, "duration_ms": 2500, "params": {"bars": 3}},
                        {"primitive": "text_reveal", "target": "conclusion", "start_ms": 2800, "duration_ms": 1500},
                    ],
                    "transition_in": "dissolve",
                    "transition_out": "fade",
                    "scientific_claims": ["A 1 km impactor is a global-catastrophe class event (illustrative)."],
                    "source_references": ["NASA CNEOS overview"],
                },
            ],
            "asset_plan": [
                {"asset_id": "asset_space", "scene_ids": ["scene_1"], "description": "Starfield with Earth", "orientation": "portrait", "style_tags": ["space", "dark"]},
                {"asset_id": "asset_entry", "scene_ids": ["scene_2"], "description": "Atmospheric entry", "orientation": "portrait", "style_tags": ["plasma", "ocean"]},
                {"asset_id": "asset_impact", "scene_ids": ["scene_3"], "description": "Impact flash terrain", "orientation": "portrait", "style_tags": ["flash", "dust"]},
                {"asset_id": "asset_chart_bg", "scene_ids": ["scene_4"], "description": "Dark grid backdrop", "orientation": "portrait", "style_tags": ["infographic", "dark"]},
            ],
            "source_references": ["NASA CNEOS overview"],
            "music_and_sound_cues": ["Low drone bed, impact hit at scene_3, user-recorded narration"],
        }
    )


def allowed_primitives() -> list[str]:
    return [primitive.value for primitive in AnimationPrimitive]


def _scale_patch_steps(steps: list, new_ms: int, factor: float) -> list:
    """Scale animation steps into a new scene duration (no static tails)."""
    scaled = []
    for step in steps:
        start_ms = min(round(step.start_ms * factor), max(0, new_ms - 100))
        duration_ms = max(100, round(step.duration_ms * factor))
        duration_ms = min(duration_ms, max(100, new_ms - start_ms))
        scaled.append(step.model_copy(update={"start_ms": start_ms, "duration_ms": duration_ms}))
    return scaled


def apply_storyboard_patch(board: Storyboard, patch) -> Storyboard:
    """Apply a validated StoryboardPatch. Returns a fully revalidated board.

    Scene durations stay authoritative (ADR-036): deleting or adding a scene
    changes the derived project duration instead of being rescaled away.
    Unknown scenes/targets raise ValueError; nothing is applied partially
    because the result is built on a deep copy and validated at the end.
    """
    from clipforge_contracts.storyboard import Storyboard as _Board

    result = board.model_copy(deep=True)

    def scene_or_raise(scene_id: str):
        scene = next((s for s in result.scenes if s.scene_id == scene_id), None)
        if scene is None:
            raise ValueError(f"Patch references unknown scene {scene_id!r}.")
        return scene

    for operation in patch.operations:
        kind = operation.op
        if kind == "set_tone":
            update = {}
            if operation.tone is not None:
                update["tone"] = operation.tone
            if operation.visual_style_bible is not None:
                update["visual_style_bible"] = operation.visual_style_bible
            result = result.model_copy(update=update)
        elif kind == "set_transition":
            scene = scene_or_raise(operation.scene_id)
            update = {"transition_out": operation.transition_out}
            if operation.transition_ms is not None:
                update["transition_ms"] = operation.transition_ms
            updated = scene.model_copy(update=update)
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "add_overlay":
            if any(o.overlay_id == operation.overlay.overlay_id for o in result.overlays):
                raise ValueError(f"Overlay {operation.overlay.overlay_id!r} already exists.")
            if len(result.overlays) >= 3:
                raise ValueError("A video holds at most 3 overlays.")
            result = result.model_copy(update={"overlays": [*result.overlays, operation.overlay]})
        elif kind == "set_overlay_text":
            if not any(o.overlay_id == operation.overlay_id for o in result.overlays):
                raise ValueError(f"Patch references unknown overlay {operation.overlay_id!r}.")
            result = result.model_copy(
                update={
                    "overlays": [
                        o.model_copy(update={"text": operation.text})
                        if o.overlay_id == operation.overlay_id
                        else o
                        for o in result.overlays
                    ]
                }
            )
        elif kind == "remove_overlay":
            if not any(o.overlay_id == operation.overlay_id for o in result.overlays):
                raise ValueError(f"Patch references unknown overlay {operation.overlay_id!r}.")
            result = result.model_copy(
                update={
                    "overlays": [
                        o for o in result.overlays if o.overlay_id != operation.overlay_id
                    ]
                }
            )
        elif kind == "set_scene_duration":
            scene = scene_or_raise(operation.scene_id)
            factor = operation.duration_ms / scene.duration_ms
            updated = scene.model_copy(
                update={
                    "duration_ms": operation.duration_ms,
                    "animation_sequence": _scale_patch_steps(
                        list(scene.animation_sequence), operation.duration_ms, factor
                    ),
                }
            )
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "split_scene":
            scene = scene_or_raise(operation.scene_id)
            if len(result.scenes) >= 12:
                raise ValueError("Storyboard already has the maximum of 12 scenes.")
            cut = operation.at_ms
            first_ms, second_ms = cut, scene.duration_ms - cut
            if first_ms < 1000 or second_ms < 1000:
                raise ValueError(
                    f"Split of {operation.scene_id} needs both halves >= 1000 ms."
                )
            existing = {s.scene_id for s in result.scenes}
            n = max(
                [int(s.scene_id.split("_")[1]) for s in result.scenes if s.scene_id.startswith("scene_")],
                default=0,
            ) + 1
            new_id = f"scene_{n}"
            while new_id in existing:
                n += 1
                new_id = f"scene_{n}"
            first = scene.model_copy(
                update={
                    "duration_ms": first_ms,
                    "animation_sequence": _scale_patch_steps(
                        list(scene.animation_sequence), first_ms, first_ms / scene.duration_ms
                    ),
                }
            )
            second = scene.model_copy(
                update={
                    "scene_id": new_id,
                    "duration_ms": second_ms,
                    "animation_sequence": _scale_patch_steps(
                        list(scene.animation_sequence), second_ms, second_ms / scene.duration_ms
                    ),
                }
            )
            scenes = [
                first if s.scene_id == scene.scene_id else s for s in result.scenes
            ]
            idx = next(i for i, s in enumerate(scenes) if s.scene_id == scene.scene_id)
            scenes.insert(idx + 1, second)
            asset_plan = []
            used_ids = {spec.asset_id for spec in result.asset_plan}
            for spec in result.asset_plan:
                if operation.scene_id not in spec.scene_ids:
                    asset_plan.append(spec)
                    continue
                asset_plan.append(
                    spec.model_copy(
                        update={"scene_ids": [sid for sid in spec.scene_ids]}
                    )
                )
                copy_id = f"{spec.asset_id}_b"[:40]
                suffix = 2
                while copy_id in used_ids:
                    copy_id = f"{spec.asset_id}_b{suffix}"[:40]
                    suffix += 1
                used_ids.add(copy_id)
                asset_plan.append(
                    spec.model_copy(update={"asset_id": copy_id, "scene_ids": [new_id]})
                )
            result = result.model_copy(update={"scenes": scenes, "asset_plan": asset_plan})
        elif kind == "move_scene":
            scene = scene_or_raise(operation.scene_id)
            scenes = [s for s in result.scenes if s.scene_id != operation.scene_id]
            original = [s.scene_id for s in result.scenes].index(operation.scene_id)
            target = original + operation.direction
            if target < 0 or target > len(scenes):
                raise ValueError(f"Cannot move {operation.scene_id} further in that direction.")
            scenes.insert(target, scene)
            result = result.model_copy(update={"scenes": scenes})
        elif kind == "add_scene":
            if any(s.scene_id == operation.scene.scene_id for s in result.scenes):
                raise ValueError(f"Scene {operation.scene.scene_id!r} already exists.")
            if len(result.scenes) >= 12:
                raise ValueError("Storyboard already has the maximum of 12 scenes.")
            scenes = list(result.scenes)
            if operation.after_scene_id:
                scene_or_raise(operation.after_scene_id)
                index = next(
                    i for i, s in enumerate(scenes) if s.scene_id == operation.after_scene_id
                )
                scenes.insert(index + 1, operation.scene)
            else:
                scenes.append(operation.scene)
            result = result.model_copy(update={"scenes": scenes})
        elif kind == "delete_scene":
            scene_or_raise(operation.scene_id)
            if len(result.scenes) <= 1:
                raise ValueError("The last scene cannot be deleted.")
            scenes = [s for s in result.scenes if s.scene_id != operation.scene_id]
            asset_plan = [
                spec.model_copy(
                    update={"scene_ids": [sid for sid in spec.scene_ids if sid != operation.scene_id]}
                )
                for spec in result.asset_plan
            ]
            asset_plan = [spec for spec in asset_plan if spec.scene_ids]
            result = result.model_copy(update={"scenes": scenes, "asset_plan": asset_plan})
        elif kind == "set_scene_text":
            scene = scene_or_raise(operation.scene_id)
            updated = scene.model_copy(update={"on_screen_text": list(operation.lines)})
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "set_text_style":
            scene = scene_or_raise(operation.scene_id)
            changes = {
                key: value
                for key, value in operation.style.model_dump().items()
                if value is not None
            }
            if not changes:
                raise ValueError("set_text_style needs at least one style field.")
            style = scene.text_style.model_copy(update=changes)
            updated = scene.model_copy(update={"text_style": style})
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "set_scene_visual":
            scene = scene_or_raise(operation.scene_id)
            update = {}
            if operation.backdrop_hue_deg is not None:
                update["backdrop_hue_deg"] = operation.backdrop_hue_deg
            if operation.visual_description is not None:
                update["visual_description"] = operation.visual_description
            if not update:
                raise ValueError("set_scene_visual needs at least one field.")
            updated = scene.model_copy(update=update)
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "set_animation_step":
            scene = scene_or_raise(operation.scene_id)
            steps = list(scene.animation_sequence)
            index = next(
                (
                    i
                    for i, step in enumerate(steps)
                    if step.target == operation.target
                    and (operation.primitive is None or step.primitive == operation.primitive)
                ),
                None,
            )
            if index is None:
                raise ValueError(
                    f"Scene {operation.scene_id} has no animation step on {operation.target!r}."
                )
            update = {}
            if operation.start_ms is not None:
                update["start_ms"] = operation.start_ms
            if operation.duration_ms is not None:
                update["duration_ms"] = operation.duration_ms
            if operation.ease is not None:
                update["ease"] = operation.ease
            if operation.params is not None:
                update["params"] = {**steps[index].params, **operation.params}
            if operation.primitive is not None:
                update["primitive"] = operation.primitive
            if not update:
                raise ValueError("set_animation_step needs at least one field to change.")
            steps[index] = steps[index].model_copy(update=update)
            updated = scene.model_copy(update={"animation_sequence": steps})
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "add_animation_step":
            scene = scene_or_raise(operation.scene_id)
            if len(scene.animation_sequence) >= 12:
                raise ValueError(f"Scene {operation.scene_id} already has 12 animation steps.")
            updated = scene.model_copy(
                update={"animation_sequence": [*scene.animation_sequence, operation.step]}
            )
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        elif kind == "remove_animation_step":
            scene = scene_or_raise(operation.scene_id)
            steps = [
                step
                for step in scene.animation_sequence
                if not (
                    step.target == operation.target
                    and (operation.primitive is None or step.primitive == operation.primitive)
                )
            ]
            if len(steps) == len(scene.animation_sequence):
                raise ValueError(
                    f"Scene {operation.scene_id} has no animation step on {operation.target!r}."
                )
            if not steps:
                raise ValueError("A scene must keep at least one animation step.")
            updated = scene.model_copy(update={"animation_sequence": steps})
            result = result.model_copy(
                update={"scenes": [updated if s.scene_id == scene.scene_id else s for s in result.scenes]}
            )
        else:  # pragma: no cover - discriminated union is exhaustive
            raise ValueError(f"Unknown patch operation {kind!r}.")
    return _Board.model_validate(result.model_dump(mode="json"))


REFINEMENT_BRIEF = """You are ClipForge Refinement Director. You receive the CURRENT storyboard of a video project as JSON plus one user instruction (often spoken, in Portuguese). Return ONLY one flat JSON patch object matching the provided schema (fields: instruction, outcome, summary, clarification_question, operations). Rules:
- The instruction field must echo the user instruction verbatim.
- Inspect the storyboard first: scene_id values, on_screen_text lines (first line of a scene is its title, target ids 'title', 'line1', 'line2'...), text_style, and animation_sequence steps (primitive, target, start_ms, duration_ms, ease).
- Each entry in operations is a FLAT object with an "op" field. Never nest operation-specific models:
  - set_scene_text: scene_id + lines (array of strings, max 6).
  - set_text_style: scene_id + style (flat object with any of family ['sans','serif','mono'], weight, size_scale, color hex like '#FFE9C9', align, valign, letter_spacing_em).
  - set_animation_step: scene_id + target + any of primitive, start_ms, duration_ms, ease, params to change.
  - add_animation_step: scene_id + step_primitive, step_target, step_start_ms, step_duration_ms, optional step_ease, step_params.
  - remove_animation_step: scene_id + target (+ optional primitive).
  - delete_scene: scene_id.
  - add_scene: scene_json (the complete new scene as a JSON STRING: scene_id like 'scene_5', duration_ms 1000-15000, narrative_purpose, visual_description, on_screen_text, animation_sequence with steps fitting the duration) + optional after_scene_id.
  - set_scene_visual: scene_id + backdrop_hue_deg (-180 to 180) and/or visual_description.
  - set_tone: tone and/or visual_style_bible.
  - set_transition: scene_id + transition_out (cut, fade, dissolve, wipe, zoom_blur) + optional transition_ms (200–1000) — the outgoing boundary into the next scene; inert on the last scene.
  - add_overlay: overlay_json (the complete new overlay as a JSON STRING: overlay_id like 'overlay_1', kind 'text' with text max 140 chars, or kind 'image' with asset_id of an already generated plate — never invent plates, reuse only; start_ms/end_ms inside the video). Overlays use the default style.
  - set_overlay_text / remove_overlay: overlay_id (+ text for the former).
  - set_scene_duration (trim): scene_id + duration_ms (1000–15000) — steps scale along; total duration follows the scenes.
  - split_scene: scene_id + at_ms (cut point in ms) — both halves need ≥1000 ms; each half repeats the animation compressed; text is repeated in both halves.
  - move_scene: scene_id + direction (-1 back, +1 forward).
- Scene references: scenes are numbered in storyboard order — 'a segunda cena' is the second entry, 'a última cena' the final one. 'Este texto', 'o título' and similar references mean the FIRST scene's title unless the storyboard or instruction identifies another scene.
- Overlays are global text banners above the scenes (max 3 per video); transitions are per-scene outgoing boundaries rendered by the engine.
- Use ONLY scene_id and target values that exist in the storyboard. Never invent ids, code, paths or parameters outside the patch schema.
- Map creative language to concrete operations: elegant typography -> style family 'serif'; modern typography -> family 'sans'; bigger/smaller -> size_scale up/down relative to the current value; white/another colour -> color hex; centred -> align 'center'; higher/lower on screen -> valign 'top'/'lower'; smoother/softer animation -> longer duration_ms and ease 'outExpo' or 'outQuad'; faster/slower -> shorter/longer duration_ms; enter from the left -> primitive 'slide'; calmer/more cinematic tone -> set_tone plus set_scene_visual backdrop_hue_deg shifts and slower steps.
- SIGNATURE TEXT ANIMATIONS (the 5 powers the engine renders best — prefer these): Fundido a subir = text_reveal/slide + outQuad; Revelacao = mask_reveal + inOutQuad; Pop = elastic_pop + outBack/outElastic; Cinetico = kinetic_typography + outExpo; Tracking = tracking + outQuad.
- 'Este texto', 'o título' and similar references mean the FIRST scene's title unless the storyboard or instruction identifies another scene. If the instruction could plausibly target several different scenes/texts and nothing identifies which one, return outcome 'clarification' with ONE focused question naming the candidates, and no operations. Never guess silently between scenes.
- Sequential instructions build on the storyboard you were given: it already includes every previously approved change.
- Animation steps must fit their scene duration (start_ms + duration_ms <= scene duration_ms). Keep at least one step per scene and at least two motion steps where the board already has them.
- Adding a scene: reuse the next free scene_N id, keep its steps inside its duration, and remember total duration is derived from the scenes (never rescale other scenes to compensate).
- summary: one short sentence in the user's language describing what will change, shown to the user for approval before anything is applied.
"""


class RefinementDirectorProvider(CreativeDirectorProvider):
    """Live Muse Spark refinement planning. Single POST, no retries."""

    provider_name = "meta-muse-spark-refinement-director"
    wire_schema = "storyboard_patch"

    def _wire_schema(self) -> dict[str, Any]:
        from clipforge_contracts.refinement_lite import PATCH_LITE_WIRE_SCHEMA

        return PATCH_LITE_WIRE_SCHEMA

    def _schema_name(self) -> str:
        return "StoryboardPatchLite"

    def _validate_content(  # type: ignore[override]
        self,
        content: str,
        expected_request_id: str,
        transcript: TranscriptResult,
        server_request_id: str | None = None,
    ):
        import json

        from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

        try:
            raw = json.loads(content)
        except ValueError as exc:
            raise DirectorValidationError(
                "Refinement content is not valid JSON.", server_request_id, category="invalid_json"
            ) from exc
        try:
            patch = lite_to_full_patch(LitePatch.model_validate(raw))
        except Exception as exc:
            raise DirectorValidationError(
                f"StoryboardPatch failed validation: {exc}",
                server_request_id,
                category="validation",
            ) from exc
        if patch.instruction != transcript.text:
            raise DirectorValidationError(
                "StoryboardPatch instruction must echo the user instruction verbatim.",
                server_request_id,
                category="idea_mismatch",
            )
        return patch

    def create_patch(
        self,
        board: Storyboard,
        instruction: str,
        *,
        request_id: str | None = None,
        authorization: LiveCallAuthorization | None = None,
        clarification_context: str | None = None,
    ):
        """Generate exactly one StoryboardPatch via a single Chat Completions call."""
        import httpx

        from clipforge_director.spark import (
            CHAT_COMPLETIONS_PATH,
            DirectorAPIError,
            DirectorRateLimitedError,
            DirectorTimeoutError,
            DirectorValidationStatus,
            SparkDirectorError,
            build_developer_prompt,
        )

        if not isinstance(authorization, LiveCallAuthorization):
            raise LiveCallNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live refinement request. "
                "No request was attempted."
            )
        transcript = TranscriptResult(
            text=instruction, language="pt-BR", provider_name="user", is_mock=False
        )
        expected_request_id = request_id or storyboard_request_id("refine:" + instruction)
        user_lines = [
            "CURRENT STORYBOARD (JSON, already includes every approved change):",
            board.model_dump_json(),
            "",
            f"USER INSTRUCTION (echo verbatim in the patch instruction field): {instruction}",
        ]
        if clarification_context:
            user_lines.append(
                "The user is answering your previous clarification question: "
                f"{clarification_context}. Resolve the ambiguity now; do not ask again."
            )
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "developer",
                    "content": build_developer_prompt(
                        playbook_text=REFINEMENT_BRIEF,
                        capability_summary="storyboard-patch-only",
                    ),
                },
                {"role": "user", "content": "\n".join(user_lines)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": self._schema_name(),
                    "schema": self._wire_schema(),
                    "strict": False,
                },
            },
            "max_completion_tokens": self._max_output_tokens,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        self.last_usage = None
        self.last_request_id = expected_request_id
        self.last_server_request_id = None
        self.last_audit = self._new_audit(expected_request_id)
        try:
            authorization.reserve()
        except Exception as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="budget_refused",
                error_code=type(exc).__name__,
            )
            raise
        try:
            response = self._client.post(
                CHAT_COMPLETIONS_PATH,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="timeout",
                error_code=type(exc).__name__,
            )
            raise DirectorTimeoutError(
                f"Refinement request timed out after {self._timeout_seconds:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.ERROR,
                error_category="transport",
                error_code=type(exc).__name__,
            )
            raise SparkDirectorError("Could not reach the refinement service.") from exc
        server_request_id = response.headers.get("x-request-id")
        self.last_server_request_id = server_request_id
        if response.status_code == 429:
            self._update_audit(
                server_request_id=server_request_id,
                http_status=response.status_code,
                validation_status=DirectorValidationStatus.ERROR,
                error_category="rate_limited",
                error_code="DirectorRateLimitedError",
            )
            raise DirectorRateLimitedError(
                "Refinement is rate limited. No automatic retry was attempted.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            message, _ = self._safe_error(response)
            self._update_audit(
                server_request_id=server_request_id,
                http_status=response.status_code,
                validation_status=DirectorValidationStatus.ERROR,
                error_category="api_error",
                error_code="DirectorAPIError",
            )
            raise DirectorAPIError(
                response.status_code,
                f"Refinement failed with HTTP {response.status_code}: {message}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DirectorAPIError(502, "Refinement returned invalid JSON.") from exc
        self.last_usage = self._record_usage(body)
        self._update_audit(
            server_request_id=server_request_id,
            http_status=response.status_code,
            prompt_tokens=self.last_usage.prompt_tokens,
            completion_tokens=self.last_usage.completion_tokens,
            total_tokens=self.last_usage.total_tokens,
            estimated_cost_usd=self.last_usage.cost_usd,
        )
        try:
            content = self._extract_content(body, server_request_id)
            patch = self._validate_content(
                content, expected_request_id, transcript, server_request_id
            )
        except DirectorValidationError as exc:
            self._update_audit(
                validation_status=DirectorValidationStatus.REJECTED,
                error_category=exc.category,
                error_code=type(exc).__name__,
            )
            raise
        self._update_audit(validation_status=DirectorValidationStatus.ACCEPTED)
        return patch


def apply_correction(board: Storyboard, patch: dict) -> Storyboard:
    """Apply a validated correction patch to one scene. Patch schema:
    {"scene_id": str, "steps": [AnimationStep-dict, ...], "on_screen_text": [str, ...]?}.
    Only allowlisted primitives accepted; steps must fit the scene duration.
    """
    from clipforge_contracts.storyboard import AnimationStep

    scene_id = patch.get("scene_id")
    scene = next((s for s in board.scenes if s.scene_id == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene {scene_id!r}.")
    raw_steps = patch.get("steps", [])
    if not raw_steps:
        raise ValueError("Correction patch must contain at least one step.")
    steps = [AnimationStep.model_validate(step) for step in raw_steps]
    update: dict = {"animation_sequence": steps}
    if "on_screen_text" in patch:
        texts = patch["on_screen_text"]
        if not isinstance(texts, list) or len(texts) > 6 or not all(isinstance(t, str) for t in texts):
            raise ValueError("on_screen_text must be a list of at most 6 strings.")
        update["on_screen_text"] = texts
    scenes = [
        s.model_copy(update=update) if s.scene_id == scene_id else s for s in board.scenes
    ]
    return board.model_copy(update={"scenes": scenes})
