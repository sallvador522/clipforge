# apps/worker — Python Worker

Implemented now: `clipforge_worker/masks.py` (ADR-005 mask writer/loader/validation, explicit nearest-neighbour resize) and `clipforge_worker/fixtures.py` (deterministic synthetic mask fixtures, ADR-007).

Later milestones: persistent job consumer (Milestone 3) and the real FFmpeg + OpenCV renderer (Milestone 4, ADR-002/ADR-006). CPU-only. No PyTorch, CUDA, local SAM, or MediaBunny.
