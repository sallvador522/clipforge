# Third-Party Notices

## browser-use/video-use (MIT)

- Upstream: https://github.com/browser-use/video-use
- Pinned commit studied: `43cfc56` (“README: point link to video-use.com waitlist”, 2026-10-08)
- License: MIT, Copyright (c) 2026 Browser Use (see `LICENSES/video-use-MIT.txt`)

### What was used

Editorial methodology and production discipline adapted at the idea level:

- Audio-first reasoning with on-demand bounded visuals.
- Ask → Confirm → Execute → Iterate → Persist workflow.
- Edit Decision List as a declarative plan artefact.
- Rendered-output self-evaluation with a capped correction loop.
- Session persistence philosophy (`project.md` adapted to ClipForge `job.json` history).

### What was NOT used

- No upstream source file was copied into ClipForge.
- No upstream helper was executed (`transcribe.py`, `render.py`, `timeline_view.py`,
  `pack_transcripts.py`, `grade.py`, animation engines).
- No dependency was adopted (`requests`, `librosa`, `matplotlib`, Manim, HyperFrames,
  Remotion, yt-dlp).
- No ElevenLabs/Scribe integration. ClipForge transcription remains Muse Voice Transcribe.

### ClipForge distinctions

- Capability Registry is authoritative; the upstream “invent freely” rule is rejected.
- Timing/segment execution stays forbidden while `timeline.trim` is disabled.
- Word-level timestamps are not assumed; ClipForge uses turn-level transcripts.
- All rendering stays local (FFmpeg/OpenCV); no hosted video model is called.

If a future change copies a substantial portion of upstream code, the upstream
copyright notice and MIT text (already preserved in `LICENSES/video-use-MIT.txt`) must
also be included in the borrowing file header, per the license terms.
