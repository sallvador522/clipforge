# Synthetic Fixtures (ADR-007)

Generated locally by `scripts/generate_fixtures.py` using `apps/worker/clipforge_worker/fixtures.py`. Deterministic (seeded); regenerate any time — output is identical.

Mask fixture cases (64x36, 12 frames, 30 FPS): `static_subject`, `moving_subject`, `multiple_subjects_crossing`, `partial_occlusion`, `mask_holes`, `irregular_edges`, `temporal_jitter`, plus error fixtures `missing_masks`, `corrupt_mask`, `wrong_dimensions` (loader must reject the last three).

Lighting conditions: lighting variation is a property of source video frames, not mask geometry, so there is no separate lighting mask. The renderer milestone pairs `moving_subject` masks with differently-lit synthetic source frames to validate compositing under different foreground/background lighting.

These fixtures validate the rendering pipeline and mask handling only. They do not validate real SAM tracking quality (accepted limitation, ADR-007). No external API calls are involved.
