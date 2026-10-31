# apps/api — FastAPI (Milestone 3, implemented)

Run: `uvicorn clipforge_api.main:app` (with the repo `PYTHONPATH` covering `packages/*` and `apps/*`, storage root from `CLIPFORGE_STORAGE_ROOT`, default `storage/`).

Endpoints: `GET /health`, `POST /api/uploads` (validated multipart upload → queued job), `POST /api/jobs/{id}/voice`, `GET /api/jobs/{id}`, `GET /api/jobs`, `GET /api/jobs/{id}/result`. Contracts in `docs/API_CONTRACTS.md`. The API never processes jobs itself — the persistent worker does. There is no download endpoint until the Milestone 4 renderer produces a verified MP4.
