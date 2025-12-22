from __future__ import annotations

from uxaudit.schema import PageTarget, SectionTarget

PROMPT_TEMPLATE = """You are a senior UX/UI auditor.
Analyze the screenshot and return ONLY valid JSON with this schema and limits:
{{
  "summary": string (<= 40 words; if a section is provided, state it is a section-only view),
  "recommendations": [
    {{
      "id": string like "rec-01", "rec-02" (sequential; at least one recommendation is required),
      "title": string (<= 12 words),
      "description": string (<= 80 words; specific action steps for this view),
      "rationale": string (<= 60 words; why it matters),
      "priority": one of ["P0","P1","P2"],
      "impact": one of ["H","M","L"],
      "effort": one of ["S","M","L"],
      "evidence": [
        {{
          "screenshot_id": "{screenshot_id}" (must reference the provided screenshot),
          "note": string (<= 30 words; what to look at),
          "location": string (<= 25 words; where in the UI)
        }}
      ],
      "tags": array of 1-5 short slug strings
    }}
  ]
}}

Language and style:
- Respond in Spanish if the page title, section title, or URL clearly indicate Spanish (e.g., contains ".es" or "/es/"); otherwise respond in English.
- Use concise, direct sentences with no markdown, bullets, or code fences.
- Keep strings plain text; do not add additional keys or commentary.

Scope rules:
- If a section is provided, only evaluate that section and phrase the summary/recommendations as section-specific.
- If no section is provided, evaluate the full page.

Always include at least one recommendation and at least one evidence item.
Return JSON only. No markdown, no code fences.

Page URL: {page_url}
Page title: {page_title}
{section_block}
"""


def build_prompt(
    page: PageTarget,
    screenshot_id: str,
    section: SectionTarget | None = None,
) -> str:
    page_title = page.title or ""
    section_block = ""
    if section:
        section_title = section.title or ""
        section_selector = section.selector or ""
        section_block = (
            f"Section title: {section_title}\n"
            f"Section selector: {section_selector}\n"
        )
    return PROMPT_TEMPLATE.format(
        page_url=page.url,
        page_title=page_title,
        screenshot_id=screenshot_id,
        section_block=section_block,
    )
