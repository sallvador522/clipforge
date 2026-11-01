# LIVE BUDGET SAFETY HARDENING

**Date:** 2026-11-01
**Status:** Complete. **No live API request was made. No API credits were consumed.**
**Tests:** 226 backend tests passing; 12 budget-safety tests; `scripts/check.ps1` exit 0.

## 1. Problem

The pre-live audit found:

1. `LiveCallBudget._read()` returned `{}` for corrupted/unreadable ledgers — fail-open.
2. Direct `create_plan()` / `transcribe_audio()` calls bypassed reservations.
3. `transcribe_upload(budget=None)` allowed live execution without a guard.
4. Historical live-call scripts called providers directly.
5. An orphaned lock could block calls with no explicit recovery procedure.
6. Dev launchers loaded a live `.env` and could activate live unexpectedly.

## 2. Fail-closed ledger

`packages/director/clipforge_director/ledger.py`:

- Missing ledger file → `{}` (valid new phase).
- Invalid JSON → `LedgerIntegrityError`; bytes are left unchanged.
- Unreadable file / `OSError` / decoding error → `LedgerIntegrityError`.
- Non-object JSON, unknown function keys, non-integer or negative counts → `LedgerIntegrityError`.
- A reservation is never written when integrity cannot be established.
- Existing valid counters are preserved.
- `tmp` + `os.replace` atomic write retained.
- Lock acquisition failure → `LedgerLockedError`; the lock is **not** deleted automatically.
- A reservation is never released after a timeout/HTTP/validation failure; there are no automatic retries.
- Concurrent reservations: the `O_CREAT|O_EXCL` lock serializes; a second process gets `LedgerLockedError`, and the limit cannot be exceeded.
- Stale-lock recovery is manual and documented; no code path removes an unknown lock.

## 3. One-shot authorization

`LiveCallAuthorization` (same module) wraps a `LiveCallBudget` and a function:

- `reserve()` calls the ledger exactly once.
- A second `reserve()` raises `LiveCallNotAuthorizedError`.
- There is no `release()` after an uncertain network outcome.

Guarded entry points:

| Entry point | Guard |
|---|---|
| `MetaEditingDirectorProvider.create_plan` | requires `authorization`; reserves immediately before POST |
| `LiteMetaEditingDirectorProvider` (inherits) | same |
| `MetaVoiceTranscriptionProvider.transcribe_audio` | requires `authorization`; reserves after local WAV validation, immediately before POST |
| `JobProcessor` director branch | creates a director authorization per job |
| `POST /api/transcribe` / `transcribe_upload` | creates a transcription authorization from the live budget |
| `transcribe_upload(budget=None)` in live mode | raises `live_budget_not_configured` before conversion/network |
| Historical scripts 001/003/004 | now construct a ledger authorization before `create_plan` |
| `scripts/prepare_live_call_006.py` | dry-run only; no `create_plan` and a network-blocking MockTransport |

Mock providers do not require credentials or a budget.

## 4. Development configuration

- `.env.example` now documents `CLIPFORGE_DIRECTOR_MODE=mock`, optional per-function limits, and the dev opt-in.
- `scripts/dev_api.py` and `scripts/dev_worker.py` force `transcribe=mock` and `director=mock` unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is set.
- With the current `.env` (live flags + key), the launcher prints:
  `Dev safety: transcription/director forced to mock. Set CLIPFORGE_DEV_ALLOW_LIVE=1 to opt in to live.`
  and `/health` reports `transcribe_mode=mock`, `director_mode=mock`.
- The real API key was not changed or printed.
- No billing or privacy setting was changed.

## 5. Live provider entry-point audit

Inspected and protected:

- `packages/director/clipforge_director/spark.py` — director POST.
- `packages/providers/clipforge_providers/transcription_meta.py` — transcription POST.
- `apps/api/clipforge_api/transcribe.py` — live upload path and `budget=None` guard.
- `apps/worker/clipforge_worker/processor.py` — director job path.
- `apps/api/clipforge_api/main.py` — budget construction/health.
- `packages/providers/clipforge_providers/factory.py` — live provider selection only; no request at construction.
- `scripts/live_call_001_spark.py`, `003`, `004` — now ledger-authorized.
- `scripts/live_e2e_audio_blur.py` — uses API/worker, which are guarded.
- `scripts/prepare_live_call_006.py` — dry-run only.

Any direct live provider call without `LiveCallAuthorization` now raises `LiveCallNotAuthorizedError` before the HTTP POST.

## 6. Tests

New `tests/test_budget_safety.py` covers:

1. Corrupted JSON blocks reservations and leaves bytes unchanged.
2. Unreadable ledger blocks reservations.
3. Invalid structure/counts rejected.
4. Valid counters preserved; cap enforced.
5. Lock contention refuses and preserves the lock.
6. Concurrent reservations cannot exceed the limit.
7. One-shot authorization rejects a second reservation.
8. Live transcription without a budget is rejected before network.
9. Mock mode works without credentials/budget.
10. Dev launchers force mock unless opted in.
11. Director failure reserves once and does not retry.
12. Transcription failure reserves once and does not retry.

Existing provider/API/worker tests were updated to pass authorization; all use `MockTransport` and temporary storage. No external requests.

## 7. Current configuration

- `.env` local: `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=live`, `CLIPFORGE_DIRECTOR_MODE=live`, limits 100/25.
- Dev launchers: force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1`.
- Ledger: `{"transcription":3,"director":2}`; limits 100/25; no lock/tmp.
- User-indicated Meta balance: $31.78; no new credits consumed by this milestone.
- Live mode later requires: explicit `CLIPFORGE_DEV_ALLOW_LIVE=1` (for dev launchers), live mode flags, server-side key, a valid ledger, and explicit approval.

## 8. Remaining risks

- A stale/orphaned lock requires manual recovery; the code refuses rather than deleting it. Verify no call is in flight before removing.
- The ledger default is 2/2; the local `.env` overrides to 100/25. A process that does not load `.env` will see the default limits and may refuse because the current ledger is 3/2. This is safe (fail-closed) but operationally important.
- A corrupted ledger now blocks all live calls until repaired; that is intentional.
- Actual billed cost remains external (Meta panel); the audit stores estimates only.
- LIVE-CALL 006 remains unexecuted.
- SAM 3.1 and Muse Image remain unintegrated.

## 9. Files modified

- `packages/director/clipforge_director/ledger.py`
- `packages/director/clipforge_director/__init__.py`
- `packages/director/clipforge_director/spark.py`
- `packages/providers/clipforge_providers/transcription_meta.py`
- `apps/api/clipforge_api/transcribe.py`
- `apps/worker/clipforge_worker/processor.py`
- `scripts/dev_api.py`, `scripts/dev_worker.py`
- `scripts/live_call_001_spark.py`, `scripts/live_call_003_spark_lite.py`,
  `scripts/live_call_004_spark_lite.py`
- `.env.example`
- `tests/test_budget_safety.py` (new)
- `tests/test_director_spark.py`, `tests/test_director_lite.py`,
  `tests/test_transcription_meta.py`, `tests/test_live_director.py`
- `docs/DECISIONS.md` (ADR-017), `docs/STATUS.md`, `docs/TASKS.md`,
  `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/LIVE_DIRECTOR_HARDENING_REPORT.md`,
  `README.md`
