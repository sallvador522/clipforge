"""ClipForge Professional Editing Director (Milestone 6B-PREP).

Deterministic mock director that produces ProfessionalEditingPlan v2 from a
confirmed transcript. It performs no network calls and is not wired into the
worker: the current v1 pipeline stays untouched until the Muse Spark integration
is explicitly approved.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from clipforge_contracts import TranscriptResult
from clipforge_contracts.capabilities import (
    BlurBackgroundParams,
    IsolateSubjectParams,
    PreserveAudioParams,
    RenderMp4Params,
    ReplaceBackgroundParams,
    VerifyOutputParams,
)
from clipforge_contracts.director_plan import (
    ApprovalStatus,
    DirectorOperation,
    OutputAspect,
    OutputTarget,
    PlanOutcome,
    ProfessionalEditingPlan,
    SubjectSelection,
    SubjectStrategy,
    VerificationRequirement,
)
from clipforge_contracts.director_stages import DirectorStage


class ProfessionalEditingDirector(Protocol):
    def create_plan(self, transcript: TranscriptResult) -> ProfessionalEditingPlan: ...


_VERIFICATION = [
    VerificationRequirement(check="duration", description="Output duration matches the rendered frame count."),
    VerificationRequirement(check="streams", description="Output has a video stream (and audio when expected)."),
    VerificationRequirement(check="frame_count", description="Frame count equals the source/mask count."),
    VerificationRequirement(check="audio_presence", description="Original audio survives when the source has audio."),
    VerificationRequirement(check="resolution", description="Resolution equals the target 720p/source size."),
]

_UNSUPPORTED_KEYWORDS: dict[str, str] = {
    "transition": "transition.apply",
    "transiÃ§Ã£o": "transition.apply",
    "transicao": "transition.apply",
    "keyframe": "keyframe.animate",
    "trim": "timeline.trim",
    "cortar": "timeline.trim",
    "multitrack": "multitrack.edit",
    "multicamada": "multitrack.edit",
    "color grade": "colour.grade",
    "colour grade": "colour.grade",
    "correÃ§Ã£o de cor": "colour.grade",
    "correcao de cor": "colour.grade",
    "speed ramp": "speed.ramp",
    "audio mix": "audio.mix",
    "mixagem": "audio.mix",
    "animated caption": "captions.animate",
    "legendas animadas": "captions.animate",
    "scene cut": "scene.detect_cuts",
    "cortes de cena": "scene.detect_cuts",
}

_VAGUE_PHRASES = (
    "make my video more professional",
    "make the video more professional",
    "make it more professional",
    "deixa o vÃ­deo mais profissional",
    "deixa o video mais profissional",
    "melhora o vÃ­deo",
    "improve my video",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _request_id(text: str) -> str:
    return "req_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _matches(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


def _verification_requirements() -> list[VerificationRequirement]:
    return [requirement.model_copy() for requirement in _VERIFICATION]


class MockProfessionalEditingDirector:
    """Deterministic, offline professional editing director."""

    def create_plan(self, transcript: TranscriptResult) -> ProfessionalEditingPlan:
        """Build a deterministic v2 plan. Pure local computation, no network."""
        return self._create_plan_impl(transcript)

    def create_edl(self, transcript: TranscriptResult) -> EditDecisionList:
        """Project the mock v2 plan into an EDL. Still offline, still unwired."""
        from clipforge_contracts.edl import edl_from_professional_plan

        return edl_from_professional_plan(self._create_plan_impl(transcript))

    def _create_plan_impl(self, transcript: TranscriptResult) -> ProfessionalEditingPlan:
        text = _normalize(transcript.text)
        request_id = _request_id(transcript.text)
        unsupported = self._unsupported_capabilities(text)
        if unsupported:
            return self._unsupported_plan(transcript, request_id, unsupported)

        if _matches(text, "desfoca ele", "desfoca-a", "desfoca ela", "blur him", "blur them", "that person"):
            return self._clarify_subject(transcript, request_id)

        if text in _VAGUE_PHRASES or _matches(text, *(_VAGUE_PHRASES)):
            return self._clarify_intent(transcript, request_id)

        if _matches(text, "sunset", "pÃ´r do sol", "por do sol", "luanda", "cinematic background"):
            return self._replace_plan(
                transcript,
                request_id,
                prompt="cinematic sunset in Luanda, warm golden hour, soft rim light",
                asset_source="mock_generated",
                interpretation="Place the subject in a warm cinematic sunset scene while keeping them sharp.",
            )

        if _matches(text, "replace the background", "substitui o fundo", "substituir o fundo", "studio", "estÃºdio", "estudio"):
            return self._replace_plan(
                transcript,
                request_id,
                prompt="professional recording studio with controlled key light",
                asset_source="local_asset",
                interpretation="Replace the background with a professional studio while keeping the subject sharp.",
            )

        if _matches(text, "blur", "desfoca", "desfocar", "sharp", "nÃ­tido", "nitido"):
            return self._blur_plan(transcript, request_id)

        return self._clarify_intent(transcript, request_id)

    # --- scenario builders ------------------------------------------------

    def _base_subject(self) -> SubjectSelection:
        return SubjectSelection(
            strategy=SubjectStrategy.LARGEST_SUBJECT,
            description="primary person in the foreground",
        )

    def _blur_plan(self, transcript: TranscriptResult, request_id: str) -> ProfessionalEditingPlan:
        ops = [
            DirectorOperation(
                operation_id="op_01_isolate",
                capability_id="subject.isolate",
                title="Isolate the primary subject",
                explanation="I isolate the main subject so the background can be treated without touching them.",
                params=IsolateSubjectParams(),
                expected_output="Per-frame subject alpha masks (mock masks in this build).",
            ),
            DirectorOperation(
                operation_id="op_02_blur",
                capability_id="background.blur",
                title="Apply background blur",
                explanation="I keep foreground detail sharp and apply a controlled depth-of-field blur behind the subject.",
                params=BlurBackgroundParams(strength=0.8, feather_px=5),
                dependencies=["op_01_isolate"],
                expected_output="Frames with a sharp subject and a softly blurred background.",
            ),
            DirectorOperation(
                operation_id="op_03_audio",
                capability_id="audio.preserve",
                title="Preserve original audio",
                explanation="Your original audio is kept untouched and muxed back into the export.",
                params=PreserveAudioParams(),
                expected_output="Original audio stream preserved.",
            ),
            DirectorOperation(
                operation_id="op_04_render",
                capability_id="video.render_mp4",
                title="Render the edit",
                explanation="I render the composited frames to a playable MP4 on the local CPU.",
                params=RenderMp4Params(),
                dependencies=["op_01_isolate", "op_02_blur", "op_03_audio"],
                expected_output="H.264/AAC MP4 with the original audio.",
            ),
            DirectorOperation(
                operation_id="op_05_verify",
                capability_id="output.verify",
                title="Verify the output file",
                explanation="I verify the actual file before calling the edit complete.",
                params=VerifyOutputParams(),
                dependencies=["op_04_render"],
                expected_output="Verified render facts (streams, duration, frames, audio).",
            ),
        ]
        return ProfessionalEditingPlan(
            request_id=request_id,
            raw_instruction=transcript.text,
            interpreted_intention="Keep the main subject sharp and blur the background.",
            subject=self._base_subject(),
            operations=ops,
            required_providers=["segmentation"],
            estimated_stages=[
                DirectorStage.PLAN_READY,
                DirectorStage.EXECUTING,
                DirectorStage.VERIFYING,
                DirectorStage.COMPLETED,
            ],
            expected_results=[
                "Subject stays sharp with clean mask edges.",
                "Background is blurred without changing the source audio.",
                "Output MP4 is verified before download.",
            ],
            verification_requirements=_verification_requirements(),
            summary_explanation=(
                "I'll isolate the main subject, preserve foreground detail and apply a controlled "
                "depth-of-field blur to the background. Your original audio stays intact."
            ),
            explanations=[
                "Subject isolation defines what must stay sharp.",
                "A feathered alpha keeps the subject edge natural.",
                "A controlled depth-of-field blur reduces background distraction.",
                "Audio is copied from the source, not regenerated.",
            ],
        )

    def _replace_plan(
        self,
        transcript: TranscriptResult,
        request_id: str,
        *,
        prompt: str,
        asset_source: str,
        interpretation: str,
    ) -> ProfessionalEditingPlan:
        simulated_note = (
            "The background is a simulated asset from the local mock provider; "
            "no image model is called."
            if asset_source == "mock_generated"
            else "A local studio background asset is used; no image model is called."
        )
        ops = [
            DirectorOperation(
                operation_id="op_01_isolate",
                capability_id="subject.isolate",
                title="Isolate the primary subject",
                explanation="I isolate the subject so the new background does not bleed into them.",
                params=IsolateSubjectParams(),
                expected_output="Per-frame subject alpha masks (mock masks in this build).",
            ),
            DirectorOperation(
                operation_id="op_02_replace",
                capability_id="background.replace",
                title="Replace the background",
                explanation=(
                    f"I replace the background with: {prompt}. {simulated_note}"
                ),
                params=ReplaceBackgroundParams(
                    prompt=prompt,
                    asset_source="mock_generated" if asset_source == "mock_generated" else "local_asset",
                    composition="rule_of_thirds",
                ),
                dependencies=["op_01_isolate"],
                expected_output="Frames with the subject composited over the new background.",
            ),
            DirectorOperation(
                operation_id="op_03_audio",
                capability_id="audio.preserve",
                title="Preserve original audio",
                explanation="Your original audio is kept untouched and muxed back into the export.",
                params=PreserveAudioParams(),
                expected_output="Original audio stream preserved.",
            ),
            DirectorOperation(
                operation_id="op_04_render",
                capability_id="video.render_mp4",
                title="Render the edit",
                explanation="I render the composite to a verified MP4 on the local CPU.",
                params=RenderMp4Params(),
                dependencies=["op_01_isolate", "op_02_replace", "op_03_audio"],
                expected_output="H.264/AAC MP4 with the original audio.",
            ),
            DirectorOperation(
                operation_id="op_05_verify",
                capability_id="output.verify",
                title="Verify the output file",
                explanation="I verify the actual file before calling the edit complete.",
                params=VerifyOutputParams(),
                dependencies=["op_04_render"],
                expected_output="Verified render facts (streams, duration, frames, audio).",
            ),
        ]
        return ProfessionalEditingPlan(
            request_id=request_id,
            raw_instruction=transcript.text,
            interpreted_intention=interpretation,
            subject=self._base_subject(),
            target=OutputTarget(aspect_ratio=OutputAspect.SOURCE),
            operations=ops,
            required_providers=["background_generation", "segmentation"],
            estimated_stages=[
                DirectorStage.PLAN_READY,
                DirectorStage.WAITING_FOR_APPROVAL,
                DirectorStage.EXECUTING,
                DirectorStage.VERIFYING,
                DirectorStage.COMPLETED,
            ],
            expected_results=[
                "Subject remains sharp over the new background.",
                "Background generation is labelled simulated when applicable.",
                "Audio is preserved and the MP4 is verified.",
            ],
            verification_requirements=_verification_requirements(),
            summary_explanation=(
                f"{interpretation} {simulated_note} The render and verification run locally."
            ),
            explanations=[
                "Isolation prevents background bleed on the subject edge.",
                "Compositing is non-destructive; the original file is preserved.",
                simulated_note,
            ],
            approval_status=ApprovalStatus.REQUIRED,
        )

    def _clarify_subject(self, transcript: TranscriptResult, request_id: str) -> ProfessionalEditingPlan:
        question = "Which person should stay sharp? Name or describe them so I don't pick the wrong subject."
        return ProfessionalEditingPlan(
            request_id=request_id,
            raw_instruction=transcript.text,
            interpreted_intention="The request names a subject ambiguously.",
            outcome=PlanOutcome.NEEDS_CLARIFICATION,
            subject=SubjectSelection(
                strategy=SubjectStrategy.NAMED_SUBJECT,
                description="unnamed person referred to as 'him'",
                is_ambiguous=True,
                clarification_question=question,
            ),
            summary_explanation="I need one detail before editing so I don't blur the wrong person.",
            clarification_questions=[question],
        )

    def _clarify_intent(self, transcript: TranscriptResult, request_id: str) -> ProfessionalEditingPlan:
        question = (
            "What would you like to change: keep you sharp and blur the background, "
            "replace the background, or something else?"
        )
        return ProfessionalEditingPlan(
            request_id=request_id,
            raw_instruction=transcript.text,
            interpreted_intention="The instruction is too broad to become a safe editing plan.",
            outcome=PlanOutcome.NEEDS_CLARIFICATION,
            subject=SubjectSelection(
                strategy=SubjectStrategy.LARGEST_SUBJECT,
                description="subject not yet specified",
                is_ambiguous=True,
                clarification_question=question,
            ),
            summary_explanation=(
                "That request is open-ended. I can keep the subject sharp and blur the background, "
                "replace the background, or both â€” tell me which one you want."
            ),
            clarification_questions=[question],
        )

    def _unsupported_capabilities(self, text: str) -> list[str]:
        found: list[str] = []
        for keyword, capability_id in _UNSUPPORTED_KEYWORDS.items():
            if keyword in text and capability_id not in found:
                found.append(capability_id)
        return found

    def _unsupported_plan(
        self, transcript: TranscriptResult, request_id: str, capability_ids: list[str]
    ) -> ProfessionalEditingPlan:
        from clipforge_contracts.capabilities import get_capability

        names = [get_capability(cid).name for cid in capability_ids if get_capability(cid)]
        listed = ", ".join(names)
        return ProfessionalEditingPlan(
            request_id=request_id,
            raw_instruction=transcript.text,
            interpreted_intention="The request needs editing capabilities that are not available in this build.",
            outcome=PlanOutcome.UNSUPPORTED,
            subject=self._base_subject(),
            summary_explanation=(
                f"This build cannot do {listed}. Available today: subject isolation, background blur, "
                "background replacement with local assets, audio preservation and verified MP4 rendering."
            ),
            unsupported_capabilities=capability_ids,
        )
