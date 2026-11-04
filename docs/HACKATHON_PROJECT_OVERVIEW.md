# ClipForge — Hackathon Project Overview

**One line:** ClipForge is an AI-directed video studio: describe the edit in words and get a real, verified MP4.

**Creator:** António Salvador (Angola). **Development assistance:** Meta's Muse Wonder (development only — not a runtime model, not the owner).

## Problem
Video editing is powerful but slow to learn. Creators know what they want ("blur the background, keep me sharp") but translating that into tracks, masks, keyframes and export settings is the hard part. AI tools exist for each step but live in disconnected apps.

## Solution
A single Studio where an AI Creative Director (Muse Spark) understands the instruction, proposes a validated plan, and coordinates specialized models plus a real local production engine:

- **Muse Spark 1.3** — reasons about the brief, plans operations, calls validated tools.
- **Muse Voice Transcribe 1.0** — speech → text for voice instructions and timed captions.
- **SAM 3.1** — subject segmentation → real masks → foreground isolation.
- **Muse Image 1.0** — one background plate per approved job.
- **ClipForge engine** — Anime.js motion, FFmpeg/OpenCV compositing and encoding, ffprobe verification, project/timeline state.

The application — not the model — executes, renders and verifies. Model output never contains paths, commands or free parameters.

## What is demonstrably working (2026-11-04)
Edit-existing-video and create-from-idea tracks end to end: upload → voice/type → plan review → subject selection → approval → render → verified MP4 download. Multitrack timeline, Properties Inspector, timed captions, Magic Background, original-byte-identical downloads. 513 backend tests, typecheck + production build clean, 6+ browser E2E suites with zero console errors. Live model calls historically validated (transcription, direction, SAM, image); day-to-day development runs mock-first with zero spend.

## Limitations a judge should know
Short clips (edit track: 10 s / 720p / 30 FPS; timeline programs up to 15 min), no selective person blur, no multi-user accounts, single-user local service. Mock segmentation is synthetic geometry — clearly labelled, never presented as SAM output.

## Why it is different
Not a chatbot bolted onto an editor: the Director plans through a capability registry, every plan stops for explicit approval, and the output is a real file produced by a real pipeline — verified before download is allowed.
