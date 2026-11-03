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
