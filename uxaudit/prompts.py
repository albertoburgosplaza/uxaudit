from __future__ import annotations

from uxaudit.schema import PageTarget, SectionTarget

PROMPT_TEMPLATE = """You are a senior UX/UI auditor.
Analyze the screenshot and return ONLY valid JSON with this shape:
{{
  "summary": "short summary",
  "recommendations": [
    {{
      "id": "rec-01",
      "title": "short title",
      "description": "what to change and how",
      "rationale": "why this matters",
      "priority": "P0|P1|P2",
      "impact": "H|M|L",
      "effort": "S|M|L",
      "evidence": [
        {{
          "screenshot_id": "{screenshot_id}",
          "note": "what to look at",
          "location": "where in the UI"
        }}
      ],
      "tags": ["tag1", "tag2"]
    }}
  ]
}}

Page URL: {page_url}
Page title: {page_title}
Auth state: {auth_state}
{section_block}
Return JSON only. No markdown, no code fences.
"""

CONSISTENCY_PROMPT_TEMPLATE = """You are a senior UX/UI auditor.
Analyze the screenshots and return ONLY valid JSON with this shape:
{{
  "summary": "short summary",
  "recommendations": [
    {{
      "id": "rec-01",
      "title": "short title",
      "description": "what to change and how to make styles consistent",
      "rationale": "why this matters",
      "priority": "P0|P1|P2",
      "impact": "H|M|L",
      "effort": "S|M|L",
      "evidence": [
        {{
          "screenshot_id": "shot-1",
          "note": "what to look at",
          "location": "where in the UI"
        }}
      ],
      "tags": ["consistency", "design-system"]
    }}
  ]
}}

Context:
- These screenshots belong to the same product and must feel consistent.
- Baseline screenshots are marked with baseline: yes. Use them as reference.
- Focus on typography, color, spacing, component styles, and interaction patterns.
- Use ONLY the screenshot_id values listed below in evidence.
- The images are provided in the same order as the list.
- Prefer recommendations that compare 2 or more screenshots.

Screenshots:
{shots_block}
Return JSON only. No markdown, no code fences.
"""


def build_prompt(
    page: PageTarget,
    screenshot_id: str,
    section: SectionTarget | None = None,
    auth_state: str | None = None,
) -> str:
    page_title = page.title or ""
    auth_state_value = auth_state or "unknown"
    section_block = ""
    if section:
        section_title = section.title or ""
        section_selector = section.selector or ""
        section_block = (
            f"Section title: {section_title}\nSection selector: {section_selector}\n"
        )
    return PROMPT_TEMPLATE.format(
        page_url=page.url,
        page_title=page_title,
        screenshot_id=screenshot_id,
        auth_state=auth_state_value,
        section_block=section_block,
    )


def build_consistency_prompt(shots_block: str) -> str:
    return CONSISTENCY_PROMPT_TEMPLATE.format(shots_block=shots_block)
