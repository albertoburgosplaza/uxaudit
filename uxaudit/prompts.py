from __future__ import annotations

from uxaudit.schema import PageTarget

PROMPT_TEMPLATE = """You are a senior UX/UI auditor.
Analyze the screenshot and return ONLY valid JSON with this shape:
{
  "summary": "short summary",
  "recommendations": [
    {
      "id": "rec-01",
      "title": "short title",
      "description": "what to change and how",
      "rationale": "why this matters",
      "priority": "P0|P1|P2",
      "impact": "H|M|L",
      "effort": "S|M|L",
      "evidence": [
        {
          "screenshot_id": "{screenshot_id}",
          "note": "what to look at",
          "location": "where in the UI"
        }
      ],
      "tags": ["tag1", "tag2"]
    }
  ]
}

Page URL: {page_url}
Page title: {page_title}
Return JSON only. No markdown, no code fences.
"""


def build_prompt(page: PageTarget, screenshot_id: str) -> str:
    page_title = page.title or ""
    return PROMPT_TEMPLATE.format(
        page_url=page.url,
        page_title=page_title,
        screenshot_id=screenshot_id,
    )
