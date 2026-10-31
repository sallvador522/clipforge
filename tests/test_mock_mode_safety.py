"""Mock-mode safety (ADR-004): zero external requests, no credentials, no silent fallback."""

import os
import socket

import pytest

from clipforge_providers import get_providers
from clipforge_providers.live import LiveProviderNotImplementedError


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("External network access attempted in mock mode")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


def test_mock_mode_is_default_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIPFORGE_AI_MODE", raising=False)
    for key in list(os.environ):
        if "META" in key or "API_KEY" in key:
            monkeypatch.delenv(key, raising=False)
    providers = get_providers()
    assert providers.mode == "mock"
    # Full mock chain works with network blocked and no credentials present.
    transcript = providers.transcription.transcribe("pt_keep_me_sharp")
    plan = providers.planner.create_plan(transcript)
    assert plan.intent.value == "keep_sharp_blur_rest"
    seg = providers.segmentation.segment(
        job_id="job-1", source_video_id="src", output_dir=tmp_path / "masks",
        width=32, height=18, frame_count=3, fps=30.0,
    )
    assert seg.is_mock is True


def test_live_mode_raises_explicitly_no_silent_fallback():
    with pytest.raises(LiveProviderNotImplementedError):
        get_providers("live")


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        get_providers("banana")
