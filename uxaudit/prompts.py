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

REDESIGN_PROMPT_TEMPLATE = """You are a senior UX/UI designer.
Create {variants} distinct redesign concepts for the screenshot. These should be
bold, clearly different directions, not minor tweaks.
Return ONLY valid JSON with this shape:
{{
  "summary": "short summary",
  "concepts": [
    {{
      "id": "concept-01",
      "title": "short name",
      "narrative": "design story and what changes",
      "experience_goals": ["goal 1", "goal 2"],
      "layout_changes": ["change 1", "change 2"],
      "visual_style": "short descriptor",
      "palette": ["#112233", "#445566", "#778899"],
      "typography": ["Primary font usage", "Secondary font usage"],
      "component_changes": ["component change 1", "component change 2"],
      "render_aspect_ratio": "1:1|2:3|3:2|3:4|4:3|4:5|5:4|9:16|16:9|21:9",
      "render_image_size": "1K|2K|4K",
      "render_frame": "full_page_vertical|full_page_horizontal|single_screen|detail",
      "image_prompt": "prompt for NanoBanana Pro or similar image generator",
      "render_notes": "aspect ratio, framing, any settings"
    }}
  ]
}}

Context:
- Page URL: {page_url}
- Page title: {page_title}
- Auth state: {auth_state}
{brief_block}

Guidance:
- Always specify render_aspect_ratio and render_frame.
- If the concept implies a vertical scrolling page, set render_frame to
  full_page_vertical and use a tall aspect ratio (9:16, 4:5, or 3:4).
- If the concept is a single wide view, use full_page_horizontal and a wide ratio
  (16:9 or 21:9).
- The render must show the full page in one frame (hero through footer).

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


def build_redesign_prompt(
    page: PageTarget,
    variants: int,
    brief_block: str,
    auth_state: str | None = None,
) -> str:
    page_title = page.title or ""
    auth_state_value = auth_state or "unknown"
    return REDESIGN_PROMPT_TEMPLATE.format(
        page_url=page.url,
        page_title=page_title,
        auth_state=auth_state_value,
        variants=variants,
        brief_block=brief_block,
    )
