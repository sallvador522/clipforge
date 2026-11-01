"""Offline Muse Image 1.0 provider tests.

No external request is made. The HTTP transport is injected and every generated
PNG is a local fixture.
"""

from __future__ import annotations

import base64
import io
import json
import socket
from pathlib import Path

import httpx
import pytest
from PIL import Image

from clipforge_contracts import BackgroundResult
from clipforge_director import LiveCallAuthorization, LiveCallBudget
from clipforge_providers import (
    MissingCredentialsError,
    MockBackgroundGenerationProvider,
    MuseImageAPIError,
    MuseImageBackgroundProvider,
    MuseImageMissingCredentialsError,
    MuseImageNotAuthorizedError,
    MuseImageRateLimitedError,
    MuseImageTimeoutError,
    MuseImageValidationError,
    get_providers,
)


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    local_hosts = {"127.0.0.1", "::1", "localhost"}

    def is_local(address) -> bool:
        return isinstance(address, tuple) and bool(address) and address[0] in local_hosts

    def connect(sock, address, *args, **kwargs):
        if is_local(address):
            return original_connect(sock, address, *args, **kwargs)
        raise AssertionError("External network access is forbidden in Muse Image tests.")

    def create_connection(address, *args, **kwargs):
        if is_local(address):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError("External network access is forbidden in Muse Image tests.")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


def _png(width: int = 32, height: int = 48, color=(20, 180, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width: int = 16, height: int = 16) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 180, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _auth(tmp_path: Path) -> LiveCallAuthorization:
    return LiveCallAuthorization(
        LiveCallBudget(tmp_path / "storage", limits={"image": 1}), "image"
    )


def _body(encoded: str | None = None, *, created: int = 1_784_584_435) -> dict:
    item = {"b64_json": encoded} if encoded is not None else {"url": "https://example.invalid/x.png"}
    return {
        "created": created,
        "data": [item],
        "output_format": "png",
        "background": "opaque",
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }


def _post_response(body: dict, *, status: int = 200, headers: dict | None = None):
    def post(_url, **_kwargs):
        return httpx.Response(status, json=body, headers=headers or {})

    return post


def test_request_schema_png_persistence_and_provenance(tmp_path):
    raw = _png()
    captured: dict = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-image-1"},
            json=_body(_b64(raw)),
        )

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    result = provider.generate(
        prompt="professional recording studio with controlled key light",
        orientation="portrait",
        output_dir=tmp_path / "job" / "background",
        job_id="job-image-1",
        authorization=_auth(tmp_path),
    )

    assert captured["url"] == "https://api.meta.ai/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    payload = captured["json"]
    assert payload["model"] == "muse-image-1.0"
    assert payload["n"] == 1
    assert payload["response_format"] == "b64_json"
    assert payload["output_format"] == "png"
    assert payload["size"] == "1024x1536"
    assert "professional recording studio" in payload["prompt"]
    assert "no people" in payload["prompt"].lower()
    assert "no text" in payload["prompt"].lower()
    assert payload["tool_enablement"] == {
        "enable_image_search": False,
        "enable_web_search": False,
        "enable_shell": False,
    }
    assert not {"image", "images", "file_id", "input_video", "mask", "video"} & set(payload)

    assert result.is_mock is False
    assert result.provider_name == "muse-image"
    assert result.model == "muse-image-1.0"
    assert result.request_id == "req-image-1"
    assert result.width == 32 and result.height == 48
    assert result.orientation == "portrait"
    assert result.output_format == "png"
    assert result.size_requested == "1024x1536"
    assert result.prompt == "professional recording studio with controlled key light"
    assert result.image_sha256
    assert result.image_path.endswith("background.png")
    assert Path(result.image_path).is_file()
    with Image.open(result.image_path) as image:
        assert image.format == "PNG"
        assert image.size == (32, 48)

    sidecar = tmp_path / "job" / "background" / "background.json"
    assert sidecar.is_file()
    persisted = BackgroundResult.model_validate_json(sidecar.read_text(encoding="utf-8"))
    assert persisted.image_sha256 == result.image_sha256
    assert persisted.request_id == "req-image-1"

    ledger = json.loads((tmp_path / "storage" / "live-call-ledger.json").read_text())
    assert ledger == {"image": 1}


def test_landscape_request_uses_landscape_aspect_ratio(tmp_path):
    captured: dict = {}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json=_body(_b64(_png(48, 32))))

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    result = provider.generate(
        prompt="minimal studio",
        orientation="landscape",
        output_dir=tmp_path / "background",
        authorization=_auth(tmp_path),
    )
    assert captured["json"]["size"] == "1536x1024"
    assert (result.width, result.height) == (48, 32)
    assert result.orientation == "landscape"


def test_refuses_to_overwrite_an_existing_background(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=_body(_b64(_png())))

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    first = provider.generate(
        prompt="studio",
        orientation="portrait",
        output_dir=tmp_path / "background",
        authorization=_auth(tmp_path),
    )
    assert Path(first.image_path).is_file()
    second_auth = LiveCallAuthorization(
        LiveCallBudget(tmp_path / "storage", limits={"image": 2}), "image"
    )
    with pytest.raises(MuseImageValidationError, match="already exists"):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=second_auth,
        )
    assert calls["n"] == 1
    assert second_auth.reserved is False


@pytest.mark.parametrize(
    "body,error",
    [
        ({"created": 1, "data": []}, "exactly one image"),
        ({"created": 1, "data": [{"b64_json": "x"}, {"b64_json": "y"}]}, "exactly one image"),
        ({"created": 1, "data": [{"b64_json": "not-base64!"}]}, "invalid base64"),
        ({"created": 1, "data": [{"b64_json": ""}]}, "no b64_json"),
        ({"created": 1, "data": [{"b64_json": _b64(b"not an image")}]}, "could not be decoded"),
        ({"created": 1, "data": [{"b64_json": _b64(_jpeg())}], "output_format": "png"}, "expected PNG"),
    ],
)
def test_invalid_image_responses_are_rejected(tmp_path, body, error):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=body)

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    with pytest.raises(MuseImageValidationError, match=error):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=_auth(tmp_path),
        )
    assert calls["n"] == 1
    assert not (tmp_path / "background" / "background.png").exists()
    assert not (tmp_path / "background" / "background.json").exists()
    assert LiveCallBudget(tmp_path / "storage").used("image") == 1


def test_missing_authorization_makes_no_request(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=_body(_b64(_png())))

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    with pytest.raises(MuseImageNotAuthorizedError):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
        )
    assert calls["n"] == 0
    assert LiveCallBudget(tmp_path / "storage").used("image") == 0


def test_wrong_authorization_function_makes_no_request(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=_body(_b64(_png())))

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    authorization = LiveCallAuthorization(
        LiveCallBudget(tmp_path / "storage", limits={"image": 1}), "director"
    )
    with pytest.raises(MuseImageNotAuthorizedError):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=authorization,
        )
    assert calls["n"] == 0


def test_missing_key_is_rejected_without_request():
    with pytest.raises(MuseImageMissingCredentialsError):
        MuseImageBackgroundProvider("")


def test_http_401_is_reported_with_request_id_and_no_retry(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(
            401,
            headers={"x-request-id": "req-auth"},
            json={"error": {"type": "authentication_error", "message": "invalid key"}},
        )

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    with pytest.raises(MuseImageAPIError) as exc:
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=_auth(tmp_path),
        )
    assert exc.value.status_code == 401
    assert exc.value.request_id == "req-auth"
    assert "invalid key" in str(exc.value)
    assert calls["n"] == 1


def test_http_429_is_reported_with_retry_after_and_no_retry(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        return httpx.Response(
            429,
            headers={"retry-after": "30", "x-request-id": "req-rate"},
            json={"error": {"message": "slow down"}},
        )

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    with pytest.raises(MuseImageRateLimitedError) as exc:
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=_auth(tmp_path),
        )
    assert exc.value.retry_after == "30"
    assert calls["n"] == 1


def test_timeout_is_reported_and_not_retried(tmp_path):
    calls = {"n": 0}

    def post(_url, **_kwargs):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")

    provider = MuseImageBackgroundProvider("test-key", http_post=post)
    with pytest.raises(MuseImageTimeoutError):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=_auth(tmp_path),
        )
    assert calls["n"] == 1


def test_factory_defaults_to_mock_and_requires_key_for_live(monkeypatch, tmp_path):
    for name in (
        "CLIPFORGE_TRANSCRIBE_MODE",
        "CLIPFORGE_DIRECTOR_MODE",
        "CLIPFORGE_SEGMENTATION_MODE",
        "CLIPFORGE_IMAGE_MODE",
        "MODEL_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    bundle = get_providers("mock")
    assert isinstance(bundle.background, MockBackgroundGenerationProvider)
    assert bundle.image_mode == "mock"

    monkeypatch.setenv("CLIPFORGE_IMAGE_MODE", "live")
    with pytest.raises(MissingCredentialsError):
        get_providers("mock")

    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    bundle = get_providers("mock")
    assert isinstance(bundle.background, MuseImageBackgroundProvider)
    assert bundle.image_mode == "live"


def test_provider_errors_do_not_create_output(tmp_path):
    provider = MuseImageBackgroundProvider(
        "test-key",
        http_post=_post_response({"error": {"message": "server error"}}, status=500),
    )
    with pytest.raises(MuseImageAPIError):
        provider.generate(
            prompt="studio",
            orientation="portrait",
            output_dir=tmp_path / "background",
            authorization=_auth(tmp_path),
        )
    assert not (tmp_path / "background" / "background.png").exists()
    assert not (tmp_path / "background" / "background.json").exists()
