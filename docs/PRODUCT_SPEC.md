# ClipForge — Product Specification

## Vision

Voice-first AI video editing agent for content creators. "Your voice. Your vision. Your video."

Users upload a video and describe what they want changed through natural speech. The agent understands the instruction, creates an editing plan, invokes the appropriate AI tools, and produces a real edited video.

## MVP Scope (must support, in order)

1. Upload a video.
2. Record voice instructions.
3. Transcribe voice.
4. Understand editing intentions.
5. Identify the primary person in the video.
6. Segment and track the person (SAM, hosted — ADR-001).
7. Keep the primary subject sharp.
8. Blur the background.
9. Generate a new background (image generation provider).
10. Replace the original background.
11. Render a final MP4 while preserving original audio.
12. Present before/after result and allow download.

Nothing outside this list is MVP scope. Do not implement unrelated features.

## Editing Director (Milestone 6B-PREP)

ClipForge prepares a professional editing director without activating a live model. The capability registry defines what can actually be planned; the runtime playbook defines how the director reasons and communicates; v2 plans are validated and adapted to the v1 execution contract. Mock scenarios cover blur, replacement, simulated cinematic backgrounds, clarification and unsupported requests. No director capability is exposed to users until its backend handler and verification exist.

## Video-Use Methodology Adaptation (6B-PREP-R)

Upstream: browser-use/video-use at pinned commit `43cfc56` (MIT; see `docs/THIRD_PARTY_NOTICES.md` and `LICENSES/video-use-MIT.txt`). Adapted: audio-first reasoning, bounded on-demand visuals, Ask → Confirm → Execute → Iterate (max 3) → Persist, declarative EDL, objective self-evaluation with explicit human review. Rejected: segment extract/concat execution, subtitle/fade/cut-boundary rules, invented tools, raw FFmpeg strings, ElevenLabs, animation engines. Timing stays forbidden while `timeline.trim` is disabled; word-level timestamps are not assumed.

## Editing Experience (Milestone 5.1)

The product is a single editing workspace, not a dashboard: import a clip into the Media panel, preview it in the central Viewer, speak (or type) an instruction in the AI Assistant panel, confirm the recognised command, watch the real processing stages, compare before/after in the Viewer, and export the verified MP4 from the TopBar. A bottom Timeline (ruler, real frame thumbnails, real audio peaks, playhead) stays in sync with playback. The MVP edits one clip; the interface must never advertise multitrack, trimming, keyframes, or transitions it cannot perform.

## Constraints

- Source clips: 10 seconds, 720p, up to 30 FPS (300 frames max benchmark unit).
- Voice-first: voice interaction is the primary interface element.
- Ambiguity: when the intended subject is ambiguous, the agent asks a spoken clarification rather than silently selecting the wrong person.
- Rendering is always real (FFmpeg + OpenCV). Only AI services are mocked during mock-first development (ADR-004).

## Technology Stack (corrected)

- Frontend: Next.js, React, TypeScript, Tailwind CSS, customised shadcn/ui primitives, Motion for React.
- Backend: Python, FastAPI, Pydantic.
- Video: Python worker with FFmpeg (decode, normalize, audio preservation, encode, export) + OpenCV (frame processing, masks, compositing). MediaBunny is excluded (ADR-003).
- Infrastructure: local storage, persistent worker process for rendering.
- AI (provider adapters, mock-first): speech transcription (live-capable, ADR-008), reasoning/planning (live-capable, ADR-014), SAM 3.1 segmentation (implemented, offline-validated and live-validated once, ADR-019), image generation (mocked; Muse Image not integrated).

## Out of Scope

- Ungated live Meta API execution. Transcription, director and SAM provider contracts are implemented, but every live call needs explicit approval, a cost estimate and the budget ledger. SAM live inference has one validated run; further calls need approval.
- Muse Image generation and selective person blur (not implemented).
- Local model hosting, GPU infrastructure, multi-user accounts, cloud storage, payments, social sharing.
