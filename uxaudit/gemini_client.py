from __future__ import annotations

import logging
import random
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from uxaudit.utils import extract_json

try:
    from google import genai
    from google.genai import types
except ImportError as exc:
    raise RuntimeError(
        "google-genai is required. Install dependencies with `pip install -e .`"
    ) from exc

logger = logging.getLogger(__name__)

DEFAULT_MAX_BACKOFF_S = 30.0
RETRIABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
RATE_LIMIT_MARKERS = {"RESOURCE_EXHAUSTED"}


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float,
        max_retries: int,
        backoff_initial_s: float,
        backoff_factor: float,
        max_image_dimension: int | None,
        max_image_bytes: int | None,
    ) -> None:
        if not api_key:
            raise ValueError("API key is required for Gemini analysis")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_initial_s = backoff_initial_s
        self.backoff_factor = backoff_factor
        self.max_image_dimension = max_image_dimension
        self.max_image_bytes = max_image_bytes

    def analyze_image(self, prompt: str, image_path: Path) -> tuple[dict | list, str]:
        image_bytes, mime_type = _compress_image(
            image_path,
            max_dimension=self.max_image_dimension,
            max_bytes=self.max_image_bytes,
        )
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type,
        )
        response = self._generate_with_retries(prompt, image_part)
        text = getattr(response, "text", "") or ""
        if not text:
            return {}, ""
        try:
            parsed = extract_json(text)
        except ValueError as exc:
            snippet = _truncate_text(text)
            logger.error(
                "Failed to parse JSON from Gemini response (len=%s). Snippet: %s",
                len(text),
                snippet,
            )
            raise ValueError(
                f"Failed to parse JSON from Gemini response. Snippet: {snippet}"
            ) from exc
        return parsed, text

    def _generate_with_retries(self, prompt: str, image_part: types.Part):
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                kwargs = {
                    "model": self.model,
                    "contents": [prompt, image_part],
                }
                if self.timeout_s and self.timeout_s > 0:
                    kwargs["request_options"] = {"timeout": self.timeout_s}
                return self.client.models.generate_content(**kwargs)
            except Exception as exc:  # noqa: BLE001
                status_code = _extract_status_code(exc)
                if not self._should_retry(attempt, attempts, exc, status_code):
                    logger.error(
                        "Gemini request failed (attempt %s/%s, status=%s): %s",
                        attempt,
                        attempts,
                        status_code or "-",
                        exc,
                    )
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Gemini request failed (attempt %s/%s, status=%s). Retrying in %.2fs",
                    attempt,
                    attempts,
                    status_code or "-",
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError("Gemini request retries exhausted")

    def _should_retry(
        self,
        attempt: int,
        max_attempts: int,
        exc: Exception,
        status_code: int | None,
    ) -> bool:
        if attempt >= max_attempts:
            return False
        message = str(exc).lower()
        code_marker = getattr(exc, "code", None)
        grpc_status = getattr(exc, "grpc_status", None)
        if status_code in RETRIABLE_STATUS_CODES:
            return True
        if isinstance(code_marker, str) and code_marker.upper() in RATE_LIMIT_MARKERS:
            return True
        if hasattr(code_marker, "name") and str(code_marker.name).upper() in RATE_LIMIT_MARKERS:
            return True
        if grpc_status and str(grpc_status).upper() in RATE_LIMIT_MARKERS:
            return True
        if "rate limit" in message or "quota" in message:
            return True
        return False

    def _backoff_delay(self, attempt: int) -> float:
        base = self.backoff_initial_s * (self.backoff_factor ** (attempt - 1))
        jitter = random.uniform(0.8, 1.2)
        return min(base * jitter, DEFAULT_MAX_BACKOFF_S)


def _guess_mime_type(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"


def _compress_image(
    path: Path,
    *,
    max_dimension: int | None,
    max_bytes: int | None,
) -> tuple[bytes, str]:
    if max_dimension is None and max_bytes is None:
        return path.read_bytes(), _guess_mime_type(path)

    with Image.open(path) as img:
        img = img.convert("RGB")
        if max_dimension:
            img = ImageOps.contain(
                img, (max_dimension, max_dimension), method=Image.Resampling.LANCZOS
            )

        quality = 85
        min_quality = 40
        format = "JPEG"
        buffer = BytesIO()
        while True:
            buffer.seek(0)
            buffer.truncate(0)
            img.save(buffer, format=format, quality=quality, optimize=True)
            data = buffer.getvalue()
            if max_bytes is None or len(data) <= max_bytes or quality <= min_quality:
                mime_type = "image/jpeg" if format.lower() == "jpeg" else f"image/{format.lower()}"
                if max_bytes and len(data) > max_bytes and max_dimension:
                    new_width = max(1, int(img.width * 0.9))
                    new_height = max(1, int(img.height * 0.9))
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    quality = 85
                    continue
                return data, mime_type
            quality = max(min_quality, quality - 10)


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        if hasattr(value, "value") and isinstance(value.value, int):
            return value.value
    response = getattr(exc, "response", None)
    if response and hasattr(response, "status_code"):
        code = getattr(response, "status_code")
        if isinstance(code, int):
            return code
    return None


def _truncate_text(text: str, limit: int = 500) -> str:
    cleaned = text.strip().replace("\n", " ")
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}…"
