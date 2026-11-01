"""Live-budget safety tests: fail-closed ledger, locks, concurrency, authorization."""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from clipforge_api.transcribe import AudioValidationError, transcribe_upload
from clipforge_contracts import TranscriptResult, capability_summary_for_prompt
from clipforge_director import (
    DirectorAPIError,
    LedgerIntegrityError,
    LedgerLockedError,
    LiveBudgetExceeded,
    LiveCallAuthorization,
    LiveCallBudget,
    LiveCallNotAuthorizedError,
    MetaEditingDirectorProvider,
)
from clipforge_providers import ProviderBundle, get_providers
from clipforge_providers.transcription_meta import MetaVoiceTranscriptionProvider, TranscriptionAPIError


def _storage(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


def _write_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(24000)
        fh.writeframes(b"\x00\x00" * 2400)
    return path


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    module_name = "_safety_" + name.replace(".py", "").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corrupt_ledger_blocks_reservations(tmp_path):
    storage = _storage(tmp_path)
    ledger = storage / "live-call-ledger.json"
    corrupt = '{"director": 1,'
    ledger.write_text(corrupt, encoding="utf-8")

    budget = LiveCallBudget(storage)
    with pytest.raises(LedgerIntegrityError):
        budget.reserve("director")

    assert ledger.read_text(encoding="utf-8") == corrupt
    assert not (storage / "live-call-ledger.lock").exists()
    assert not (storage / "live-call-ledger.tmp").exists()


def test_unreadable_ledger_blocks_reservations(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    ledger = storage / "live-call-ledger.json"
    ledger.write_text('{"director": 1}', encoding="utf-8")
    real_read_text = Path.read_text

    def guarded_read(self, *args, **kwargs):
        if self == ledger:
            raise PermissionError("denied for test")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    budget = LiveCallBudget(storage)
    with pytest.raises(LedgerIntegrityError):
        budget.reserve("director")

    assert ledger.read_bytes() == b'{"director": 1}'


def test_invalid_structure_and_counts_are_rejected(tmp_path):
    storage = _storage(tmp_path)
    ledger = storage / "live-call-ledger.json"
    for payload in (
        '{"director": 0, "unknown": 1}',
        '{"director": "1"}',
        '{"director": -1}',
        '[]',
    ):
        ledger.write_text(payload, encoding="utf-8")
        with pytest.raises(LedgerIntegrityError):
            LiveCallBudget(storage).reserve("director")
        assert ledger.read_text(encoding="utf-8") == payload


def test_valid_counters_are_preserved_and_cap_is_enforced(tmp_path):
    storage = _storage(tmp_path)
    ledger = storage / "live-call-ledger.json"
    budget = LiveCallBudget(storage, limits={"director": 2})
    assert budget.reserve("director") == 1
    assert budget.reserve("director") == 2
    before = ledger.read_text(encoding="utf-8")

    with pytest.raises(LiveBudgetExceeded):
        budget.reserve("director")

    assert ledger.read_text(encoding="utf-8") == before
    assert json.loads(before) == {"director": 2}


def test_lock_contention_refuses_without_auto_deleting_the_lock(tmp_path):
    storage = _storage(tmp_path)
    ledger = storage / "live-call-ledger.json"
    ledger.write_text('{"director": 0}', encoding="utf-8")
    lock = storage / "live-call-ledger.lock"
    lock.write_text("held by another process", encoding="utf-8")

    with pytest.raises(LedgerLockedError):
        LiveCallBudget(storage).reserve("director")

    assert lock.exists()
    assert json.loads(ledger.read_text(encoding="utf-8")) == {"director": 0}
    lock.unlink()


def test_concurrent_reservations_cannot_exceed_the_limit(tmp_path):
    storage = _storage(tmp_path)
    budget = LiveCallBudget(storage, limits={"director": 1})
    barrier = threading.Barrier(8)

    def attempt(_):
        barrier.wait()
        try:
            return ("ok", budget.reserve("director"))
        except Exception as exc:  # LedgerLockedError or LiveBudgetExceeded
            return (type(exc).__name__, None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))

    successes = [value for status, value in results if status == "ok"]
    assert successes == [1]
    assert budget.used("director") == 1
    assert not (storage / "live-call-ledger.lock").exists()


def test_authorization_is_one_shot(tmp_path):
    storage = _storage(tmp_path)
    budget = LiveCallBudget(storage, limits={"director": 2})
    authorization = LiveCallAuthorization(budget, "director")

    assert authorization.reserve() == 1
    assert authorization.reserved is True
    with pytest.raises(LiveCallNotAuthorizedError):
        authorization.reserve()
    assert budget.used("director") == 1


def test_live_transcription_without_budget_is_rejected_before_network():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"transcript": "should not be reached"})

    live = MetaVoiceTranscriptionProvider(
        "test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
        ),
    )
    bundle = get_providers("mock")
    bundle = ProviderBundle(
        transcription=live,
        planner=bundle.planner,
        segmentation=bundle.segmentation,
        background=bundle.background,
        mode="mock",
        transcription_mode="live",
    )

    with pytest.raises(AudioValidationError) as exc:
        transcribe_upload(
            b"not audio",
            "recording.wav",
            providers=bundle,
            mock_fixture_id=None,
            budget=None,
        )
    assert exc.value.code == "live_budget_not_configured"
    assert calls["n"] == 0


def test_mock_mode_works_without_credentials_or_budget():
    providers = get_providers("mock")
    result = providers.transcription.transcribe("pt_keep_me_sharp")
    assert result.is_mock is True
    assert result.text
    assert providers.transcription_mode == "mock"


def test_dev_launchers_force_mock_unless_explicitly_opted_in(monkeypatch):
    monkeypatch.delenv("CLIPFORGE_DEV_ALLOW_LIVE", raising=False)
    monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_DIRECTOR_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_SEGMENTATION_MODE", "live")

    for script in ("dev_api.py", "dev_worker.py"):
        monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "live")
        monkeypatch.setenv("CLIPFORGE_DIRECTOR_MODE", "live")
        monkeypatch.setenv("CLIPFORGE_SEGMENTATION_MODE", "live")
        _load_script(script).enforce_dev_safety()
        assert os.environ["CLIPFORGE_TRANSCRIBE_MODE"] == "mock"
        assert os.environ["CLIPFORGE_DIRECTOR_MODE"] == "mock"
        assert os.environ["CLIPFORGE_SEGMENTATION_MODE"] == "mock"

    monkeypatch.setenv("CLIPFORGE_DEV_ALLOW_LIVE", "1")
    monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_DIRECTOR_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_SEGMENTATION_MODE", "live")
    _load_script("dev_api.py").enforce_dev_safety()
    assert os.environ["CLIPFORGE_TRANSCRIBE_MODE"] == "live"
    assert os.environ["CLIPFORGE_DIRECTOR_MODE"] == "live"
    assert os.environ["CLIPFORGE_SEGMENTATION_MODE"] == "live"


def test_director_failure_reserves_once_and_never_retries(tmp_path):
    storage = _storage(tmp_path)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": {"message": "boom", "type": "server_error"}})

    provider = MetaEditingDirectorProvider(
        "test-key",
        "playbook",
        capability_summary_for_prompt(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
        ),
    )
    authorization = LiveCallAuthorization(LiveCallBudget(storage, limits={"director": 2}), "director")
    transcript = TranscriptResult(text="Keep me sharp.", language="en", provider_name="t", is_mock=True)

    with pytest.raises(DirectorAPIError):
        provider.create_plan(transcript, authorization=authorization)
    assert calls["n"] == 1
    assert LiveCallBudget(storage).used("director") == 1

    with pytest.raises(LiveCallNotAuthorizedError):
        provider.create_plan(transcript, authorization=authorization)
    assert calls["n"] == 1


def test_transcription_failure_reserves_once_and_never_retries(tmp_path):
    storage = _storage(tmp_path)
    wav = _write_wav(tmp_path / "recording.wav")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"type": "server_error", "message": "boom"})

    provider = MetaVoiceTranscriptionProvider(
        "test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
        ),
    )
    authorization = LiveCallAuthorization(
        LiveCallBudget(storage, limits={"transcription": 2}), "transcription"
    )

    with pytest.raises(TranscriptionAPIError):
        provider.transcribe_audio(wav, authorization=authorization)
    assert calls["n"] == 1
    assert LiveCallBudget(storage).used("transcription") == 1

    with pytest.raises(LiveCallNotAuthorizedError):
        provider.transcribe_audio(wav, authorization=authorization)
    assert calls["n"] == 1
