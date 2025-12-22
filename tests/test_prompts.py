from __future__ import annotations

import unittest

from uxaudit.prompts import build_prompt
from uxaudit.schema import PageTarget
from uxaudit.utils import extract_json


class PromptTemplateTests(unittest.TestCase):
    def test_prompt_includes_language_and_scope_rules(self) -> None:
        page = PageTarget(id="page-1", url="https://example.com", title="Example")
        prompt = build_prompt(page, "shot-1")

        self.assertIn("Language and style", prompt)
        self.assertIn("Scope rules", prompt)
        self.assertIn("summary", prompt)
        self.assertIn("recommendations", prompt)


class ExtractJsonSamplesTests(unittest.TestCase):
    def test_extract_json_parses_spanish_response(self) -> None:
        response = """
        {
          "summary": "Vista de sección con navegación primaria.",
          "recommendations": [
            {
              "id": "rec-01",
              "title": "Mejorar jerarquía",
              "description": "Ajusta contraste y tamaño de los enlaces principales para que destaquen sin desplazar el contenido.",
              "rationale": "Ayuda a que el usuario priorice las rutas clave de manera rápida.",
              "priority": "P1",
              "impact": "M",
              "effort": "M",
              "evidence": [
                {
                  "screenshot_id": "shot-99",
                  "note": "La barra superior compite con el hero.",
                  "location": "Parte superior centrada"
                }
              ],
              "tags": ["navigation", "visual"]
            }
          ]
        }
        """
        parsed = extract_json(response)

        self.assertEqual(parsed["summary"], "Vista de sección con navegación primaria.")
        self.assertEqual(parsed["recommendations"][0]["id"], "rec-01")
        self.assertEqual(
            parsed["recommendations"][0]["evidence"][0]["screenshot_id"],
            "shot-99",
        )

    def test_extract_json_parses_fenced_english_response(self) -> None:
        response = """
        Model output:
        ```
        {
          "summary": "Section-only review of the pricing table.",
          "recommendations": [
            {
              "id": "rec-01",
              "title": "Clarify CTAs",
              "description": "Use a single accent color for primary CTAs and align them to the right for consistency.",
              "rationale": "Reduces decision fatigue and improves scannability for the pricing options.",
              "priority": "P2",
              "impact": "L",
              "effort": "S",
              "evidence": [
                {
                  "screenshot_id": "shot-88",
                  "note": "Buttons blend with secondary links.",
                  "location": "Pricing table footer"
                }
              ],
              "tags": ["ctas", "layout"]
            }
          ]
        }
        ```
        """
        parsed = extract_json(response)

        self.assertEqual(
            parsed["summary"], "Section-only review of the pricing table."
        )
        self.assertEqual(parsed["recommendations"][0]["title"], "Clarify CTAs")


if __name__ == "__main__":
    unittest.main()
