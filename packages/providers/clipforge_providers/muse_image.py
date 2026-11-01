"""Real Meta Muse Image 1.0 background generation.

Official schema verified 2026-11-01:
POST {base_url}/images/generations with model=muse-image-1.0, prompt, n=1,
response_format=b64_json, output_format=png, and an aspect-ratio `size`.
The API returns base64 image data in data[0].b64_json; `size` does not promise
exact pixels. The provider decodes and validates the actual PNG before saving it.

Only the text prompt is sent. No video, frame, mask or source file is uploaded.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from clipforge_contracts import BackgroundResult

logger = logging.getLogger("clipforge.muse_image")

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-image-1.0"
DEFAULT_TIMEOUT_SECONDS = 180.0
IMAGE_SIZE_BY_ORIENTATION = {
    "landscape": "1536x1024",
    "portrait": "1024x1536",
}


class MuseImageError(Exception):
    pass


class MuseImageMissingCredentialsError(MuseImageError):
    pass


class MuseImageNotAuthorizedError(MuseImageError):
    pass


class MuseImageTimeoutError(MuseImageError):
    pass


class MuseImageRateLimitedError(MuseImageError):
    def __init__(self, message: str, *, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MuseImageAPIError(MuseImageError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class MuseImageValidationError(MuseImageError):
    pass


def _effective_prompt(prompt: str, orientation: str) -> str:
    base = " ".join(prompt.split()).strip()
    if not base:
        raise MuseImageValidationError("Muse Image requires a non-empty background prompt.")
    return (
        f"Create a clean, photorealistic background plate for a video composite: {base}. "
        "The image must contain no people, no human figures, no foreground subjects, "
        "no text, no labels, no logos, and no watermarks. Keep the central area "
        "unobstructed for a foreground subject. Use cinematic lighting, natural depth "
        "and a composition that reads as a real environment. "
        f"{'Portrait' if orientation == 'portrait' else 'Landscape'} composition."
    )


class MuseImageBackgroundProvider:
    """Official Muse Image 1.0 images/generations implementation (no retries)."""

    provider_name = "muse-image"
    execution_mode = "live"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        http_post: Callable[..., httpx.Response] | None = None,
    ) -> None:
        if not api_key.strip():
            raise MuseImageMissingCredentialsError(
                "Muse Image live mode requires MODEL_API_KEY (server-side only). "
                "No request was attempted."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._http_post = http_post or httpx.post
        self.last_request_id: str | None = None

    @property
    def model(self) -> str:
        return self._model

    def generate(
        self,
        *,
        prompt: str,
        orientation: str = "landscape",
        output_dir: str | Path | None = None,
        job_id: str | None = None,
        authorization=None,
    ) -> BackgroundResult:
        if orientation not in IMAGE_SIZE_BY_ORIENTATION:
            raise MuseImageValidationError(
                f"orientation must be one of {sorted(IMAGE_SIZE_BY_ORIENTATION)}; got {orientation!r}."
            )
        if output_dir is None:
            raise MuseImageValidationError(
                "Muse Image generation requires an output directory under job storage."
            )
        output_root = Path(output_dir)
        image_path = output_root / "background.png"
        sidecar_path = output_root / "background.json"
        if image_path.exists() or sidecar_path.exists():
            raise MuseImageValidationError(
                "A background image already exists for this job; refusing to overwrite or regenerate."
            )

        effective_prompt = _effective_prompt(prompt, orientation)
        size = IMAGE_SIZE_BY_ORIENTATION[orientation]
        self._require_authorization(authorization)

        payload = {
            "model": self._model,
            "prompt": effective_prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
            "output_format": "png",
            "reasoning_strength": "low",
            "tool_enablement": {
                "enable_image_search": False,
                "enable_web_search": False,
                "enable_shell": False,
            },
        }

        # Reserve immediately before the only billable POST. No retry is possible.
        authorization.reserve()
        try:
            response = self._http_post(
                f"{self._base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise MuseImageTimeoutError(
                "Muse Image generation timed out. No retry was attempted."
            ) from exc
        except httpx.HTTPError as exc:
            raise MuseImageAPIError(
                "Muse Image generation failed before a response was received."
            ) from exc

        self.last_request_id = response.headers.get("x-request-id")
        logger.info(
            "muse_image_status status=%d request_id=%s",
            response.status_code,
            self.last_request_id,
        )
        self._raise_for_status(response)

        try:
            body = response.json()
        except ValueError as exc:
            raise MuseImageValidationError("Muse Image returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise MuseImageValidationError("Muse Image response is not a JSON object.")
        data = body.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise MuseImageValidationError(
                "Muse Image must return exactly one image for n=1."
            )
        item = data[0]
        if not isinstance(item, dict):
            raise MuseImageValidationError("Muse Image image entry is not an object.")
        encoded = item.get("b64_json")
        if not isinstance(encoded, str) or not encoded.strip():
            raise MuseImageValidationError("Muse Image response has no b64_json image data.")
        echoed_format = body.get("output_format")
        if echoed_format is not None and echoed_format != "png":
            raise MuseImageValidationError(
                f"Muse Image returned output_format={echoed_format!r}; expected 'png'."
            )

        raw = self._decode_base64(encoded)
        width, height = self._validate_png(raw)
        image_sha256 = hashlib.sha256(raw).hexdigest()
        output_root.mkdir(parents=True, exist_ok=True)
        self._write_atomic(image_path, raw)

        created = body.get("created")
        generated_at = datetime.now(timezone.utc)
        if isinstance(created, (int, float)) and not isinstance(created, bool):
            try:
                generated_at = datetime.fromtimestamp(float(created), timezone.utc)
            except (OverflowError, OSError, ValueError):
                pass
        revised_prompt = item.get("revised_prompt")
        usage = body.get("usage")
        actual_orientation = "landscape" if width >= height else "portrait"
        if actual_orientation != orientation:
            logger.warning(
                "muse_image_orientation_mismatch requested=%s actual=%s size=%dx%d",
                orientation,
                actual_orientation,
                width,
                height,
            )

        result = BackgroundResult(
            asset_id=f"muse-image-{image_sha256[:12]}",
            image_path=str(image_path),
            width=width,
            height=height,
            orientation=actual_orientation,  # type: ignore[arg-type]
            simulated_prompt=prompt,
            provider_name=self.provider_name,
            is_mock=False,
            model=self._model,
            request_id=self.last_request_id,
            prompt=prompt,
            effective_prompt=effective_prompt,
            revised_prompt=revised_prompt if isinstance(revised_prompt, str) else None,
            output_format="png",
            size_requested=size,
            image_sha256=image_sha256,
            generated_at=generated_at,
            usage=usage if isinstance(usage, dict) else None,
        )
        self._write_atomic(
            sidecar_path,
            result.model_dump_json(indent=2).encode("utf-8"),
        )
        logger.info(
            "muse_image_completed job_id=%s request_id=%s size=%dx%d sha256=%s",
            job_id,
            self.last_request_id,
            width,
            height,
            image_sha256,
        )
        return result

    def _require_authorization(self, authorization) -> None:
        from clipforge_director import LiveCallAuthorization

        if not isinstance(authorization, LiveCallAuthorization):
            raise MuseImageNotAuthorizedError(
                "Muse Image generation requires a one-shot LiveCallAuthorization. "
                "No request was attempted."
            )
        if authorization.function != "image":
            raise MuseImageNotAuthorizedError(
                f"Authorization is for {authorization.function!r}, not 'image'. "
                "No request was attempted."
            )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        request_id = response.headers.get("x-request-id")
        message = f"Muse Image generation failed with HTTP {response.status_code}."
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = " ".join(error["message"].split())[:300]
                if detail:
                    message = f"{message} {detail}"
        except ValueError:
            pass
        if response.status_code in (401, 403):
            raise MuseImageAPIError(
                message,
                status_code=response.status_code,
                request_id=request_id,
            )
        if response.status_code == 429:
            raise MuseImageRateLimitedError(
                f"{message} No retry was attempted.",
                retry_after=response.headers.get("retry-after"),
            )
        raise MuseImageAPIError(
            message,
            status_code=response.status_code,
            request_id=request_id,
        )

    @staticmethod
    def _decode_base64(value: str) -> bytes:
        try:
            raw = base64.b64decode(value.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MuseImageValidationError("Muse Image returned invalid base64 data.") from exc
        if not raw:
            raise MuseImageValidationError("Muse Image returned empty image data.")
        return raw

    @staticmethod
    def _validate_png(raw: bytes) -> tuple[int, int]:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "PNG":
                    raise MuseImageValidationError(
                        f"Muse Image returned {image.format or 'an unknown format'}; expected PNG."
                    )
                width, height = image.size
                image.verify()
        except MuseImageValidationError:
            raise
        except Exception as exc:
            raise MuseImageValidationError(
                "Muse Image returned image data that could not be decoded as PNG."
            ) from exc
        if width <= 0 or height <= 0:
            raise MuseImageValidationError("Muse Image returned an image with invalid dimensions.")
        return width, height

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_bytes(content)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
