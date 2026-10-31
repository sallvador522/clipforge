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
- AI (provider adapters, mock-first): speech transcription, reasoning/planning, SAM segmentation, image generation.

## Out of Scope

- Live Meta API integration (deferred until the gate in `docs/TASKS.md` Milestone 6 is passed and explicitly approved).
- Local model hosting, GPU infrastructure, multi-user accounts, cloud storage, payments, social sharing.
