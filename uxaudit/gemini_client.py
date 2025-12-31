from __future__ import annotations

import random
import time
from pathlib import Path

from uxaudit.utils import extract_json

try:
    from google import genai
    from google.genai import errors, types
except ImportError as exc:
    raise RuntimeError(
        "google-genai is required. Install dependencies with `pip install -e .`"
    ) from exc


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("API key is required for Gemini analysis")
        self.request_timeout_ms = 60_000
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=self.request_timeout_ms),
        )
        self.model = model
        self.max_retries = 3
        self.initial_backoff = 1.0
        self.max_backoff = 8.0

    def analyze_image(self, prompt: str, image_path: Path) -> tuple[dict | list, str]:
        return self.analyze_images(prompt, [image_path])

    def analyze_images(
        self, prompt: str, image_paths: list[Path]
    ) -> tuple[dict | list, str]:
        if not image_paths:
            return {}, ""
        contents: list[types.Part | str] = [prompt]
        for image_path in image_paths:
            image_bytes = image_path.read_bytes()
            contents.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=_guess_mime_type(image_path),
                )
            )
        return self._generate(contents)

    def generate_image(
        self,
        prompt: str,
        model: str,
        reference_image: Path | None = None,
        response_modalities: list[str] | None = None,
        image_config: types.ImageConfig | None = None,
    ) -> bytes | None:
        contents: list[types.Part | str] = [prompt]
        if reference_image:
            contents.append(
                types.Part.from_bytes(
                    data=reference_image.read_bytes(),
                    mime_type=_guess_mime_type(reference_image),
                )
            )

        config = types.GenerateContentConfig(
            response_modalities=response_modalities or ["TEXT", "IMAGE"],
            image_config=image_config,
        )

        def _call():
            return self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

        response = self._call_with_retry(_call)
        return _extract_inline_image_bytes(response)

    def edit_image(
        self,
        prompt: str,
        reference_image: Path,
        model: str,
        response_modalities: list[str] | None = None,
        image_config: types.ImageConfig | None = None,
    ) -> bytes | None:
        return self.generate_image(
            prompt=prompt,
            model=model,
            reference_image=reference_image,
            response_modalities=response_modalities,
            image_config=image_config,
        )

    def _generate(self, contents: list[types.Part | str]) -> tuple[dict | list, str]:
        response = None
        delay = self.initial_backoff
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                )
                break
            except errors.APIError as exc:
                if not _should_retry(exc) or attempt >= self.max_retries:
                    raise
            except Exception:
                if attempt >= self.max_retries:
                    raise
            time.sleep(_with_jitter(delay))
            delay = min(delay * 2, self.max_backoff)
        if response is None:
            return {}, ""
        text = getattr(response, "text", "") or ""
        if not text:
            return {}, ""
        try:
            parsed = extract_json(text)
        except ValueError:
            parsed = {}
        return parsed, text

    def _call_with_retry(self, call):
        response = None
        delay = self.initial_backoff
        for attempt in range(self.max_retries + 1):
            try:
                response = call()
                break
            except errors.APIError as exc:
                if not _should_retry(exc) or attempt >= self.max_retries:
                    raise
            except Exception:
                if attempt >= self.max_retries:
                    raise
            time.sleep(_with_jitter(delay))
            delay = min(delay * 2, self.max_backoff)
        return response


def _guess_mime_type(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"


def _should_retry(exc: errors.APIError) -> bool:
    if isinstance(exc, errors.ServerError):
        return True
    return exc.code in {408, 429, 500, 502, 503, 504}


def _with_jitter(delay: float) -> float:
    return delay * (0.9 + random.random() * 0.2)


def _extract_inline_image_bytes(response: object) -> bytes | None:
    parts = getattr(response, "parts", None)
    if not parts:
        return None
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if inline_data and getattr(inline_data, "data", None):
            return inline_data.data
    return None
