---
name: clipforge-video-pipeline
description: Rules for the ClipForge video pipeline — mask storage/validation, FFmpeg+OpenCV rendering, compositing, audio preservation, output verification, and CPU benchmarking. Use for any work in apps/worker, masks, rendering, or benchmarks.
---

# ClipForge Video Pipeline

- Stack: FFmpeg (decode, normalize, audio preservation, encode, export) + OpenCV (frames, masks, compositing). CPU-only (ADR-002, ADR-006). No PyTorch/CUDA/local SAM (ADR-001). No MediaBunny (ADR-003).
- Masks: canonical format is PNG sequence + manifest.json (ADR-005). 8-bit grayscale, 0=background, 255=subject, never JPEG. Loader validates missing/corrupt/wrong-size/unexpected frames and never silently resizes; explicit resize is nearest-neighbour only; edge smoothing happens in the renderer, not the loader.
- Mocks return real local mask data the renderer consumes — never bare success messages.
- Rendering must actually decode frames, build alpha, smooth edges, blur or replace background, keep subject sharp, preserve original audio, and encode a real MP4.
- Verify the actual output file (readable, valid duration, video + audio streams present, audio sync, frame integrity). Never trust an API response alone. Preserve originals until verification passes.
- Performance: benchmark is 300 frames / 1280x720 / 30 FPS, blur and replacement measured separately, with machine specs recorded. Start sequential with bounded memory; optimize (pipelining, parallelism, downscale-blur) only after profiling. Never promise timings before measurement, never trade mask correctness for speed unmeasured.
- Synthetic fixtures validate pipeline and mask handling, not SAM quality (ADR-007).
