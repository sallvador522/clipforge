# apps/worker — Python Worker

Implemented: `clipforge_worker/masks.py` (ADR-005 mask writer/loader/validation), `clipforge_worker/fixtures.py` (deterministic synthetic fixtures, ADR-007), `clipforge_worker/processor.py` (mock pipeline per job: transcribe → plan → segment → optional background; clarification completes without segmentation; failures recorded with originals preserved), `clipforge_worker/worker_process.py` (persistent polling worker).

Run the worker as its own process: `python -m clipforge_worker.worker_process --storage storage --poll 0.5`. It claims ready jobs atomically (one worker per job), processes sequentially on CPU, and logs to `clipforge.worker`. `completed` means the mock AI pipeline finished — rendering (FFmpeg + OpenCV, Milestone 4) does not exist yet and is never faked (`render_status="not_implemented"`). No PyTorch, CUDA, local SAM, or MediaBunny.
