from __future__ import annotations

from pathlib import Path

from uxaudit.utils import extract_json

try:
    from google import genai
    from google.genai import types
except ImportError as exc:
    raise RuntimeError(
        "google-genai is required. Install dependencies with `pip install -e .`"
    ) from exc


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("API key is required for Gemini analysis")
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def analyze_image(self, prompt: str, image_path: Path) -> tuple[dict | list, str]:
        image_bytes = image_path.read_bytes()
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=_guess_mime_type(image_path),
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt, image_part],
        )
        text = getattr(response, "text", "") or ""
        if not text:
            return {}, ""
        try:
            parsed = extract_json(text)
        except ValueError:
            parsed = {}
        return parsed, text


def _guess_mime_type(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"
