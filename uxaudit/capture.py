from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import ElementHandle, Page

from uxaudit.browser import BrowserConfig, browser_page
from uxaudit.config import AuditConfig


@dataclass
class SectionCapture:
    title: str | None
    selector: str | None
    path: Path
    width: int
    height: int


@dataclass
class CaptureResult:
    url: str
    title: str
    path: Path
    links: list[str]
    sections: list[SectionCapture]


def capture_full_page(
    url: str,
    output_path: Path,
    config: AuditConfig,
    max_sections: int = 0,
) -> CaptureResult:
    browser_config = BrowserConfig(
        viewport_width=config.viewport_width,
        viewport_height=config.viewport_height,
        user_agent=config.user_agent,
    )
    with browser_page(browser_config) as page:
        page.goto(url, wait_until=config.wait_until, timeout=config.timeout_ms)
        title = page.title()
        links = _extract_nav_links(page)
        page.screenshot(path=str(output_path), full_page=True)
        sections: list[SectionCapture] = []
        if max_sections > 0:
            sections = _capture_sections(page, output_path, config, max_sections)
        return CaptureResult(
            url=page.url,
            title=title,
            path=output_path,
            links=links,
            sections=sections,
        )


def _extract_nav_links(page: Page) -> list[str]:
    script = """
() => {
  const selector = 'nav a[href], header a[href], footer a[href]';
  return Array.from(document.querySelectorAll(selector))
    .map((el) => el.href)
    .filter((href) => href && typeof href === 'string');
}
"""
    try:
        links = page.evaluate(script)
    except Exception:
        return []
    if not isinstance(links, list):
        return []
    return [link for link in links if isinstance(link, str) and link]


def _capture_sections(
    page: Page,
    output_path: Path,
    config: AuditConfig,
    max_sections: int,
) -> list[SectionCapture]:
    candidates = _collect_section_candidates(page)
    min_width = config.viewport_width * 0.4
    min_height = 120
    max_height = config.viewport_height * 2.5
    viewport = page.viewport_size() or {
        "width": config.viewport_width,
        "height": config.viewport_height,
    }
    candidate_boxes: list[tuple[ElementHandle, dict[str, float]]] = []
    for element in candidates:
        box = element.bounding_box()
        if box:
            candidate_boxes.append((element, box))

    candidate_boxes.sort(
        key=lambda item: (item[1]["y"], -_box_area(item[1]))
    )

    accepted_boxes: list[dict[str, float]] = []
    captures: list[SectionCapture] = []

    for element, box in candidate_boxes:
        if len(captures) >= max_sections:
            break
        width = int(box["width"])
        height = int(box["height"])
        if width < min_width or height < min_height:
            continue
        if height > max_height:
            continue
        if not _intersects_viewport(box, viewport):
            continue
        if _has_no_visible_text(element):
            continue
        if any(_iou(box, existing) > 0.6 for existing in accepted_boxes):
            continue
        title = _section_title(element)
        selector = _section_selector(element)
        section_path = output_path.with_name(
            f"{output_path.stem}-section-{len(captures) + 1}.png"
        )
        try:
            element.screenshot(path=str(section_path))
        except Exception:
            continue
        accepted_boxes.append(box)
        captures.append(
            SectionCapture(
                title=title,
                selector=selector,
                path=section_path,
                width=width,
                height=height,
            )
        )
    return captures


def _collect_section_candidates(page: Page) -> list[ElementHandle]:
    selectors = [
        "section",
        "main",
        "article",
        "aside",
        "header",
        "footer",
        "[role='region']",
        "[role='main']",
        "[role='banner']",
        "[role='contentinfo']",
        "[aria-labelledby]",
    ]
    elements = list(page.query_selector_all(",".join(selectors)))
    headings = page.query_selector_all("h2, h3")
    for heading in headings:
        handle = heading.evaluate_handle(
            "el => el.closest('section, main, article, div')"
        )
        element = handle.as_element()
        if element:
            elements.append(element)
    return elements


def _box_area(box: dict[str, float]) -> float:
    return box["width"] * box["height"]


def _intersects_viewport(box: dict[str, float], viewport: dict[str, int]) -> bool:
    viewport_width = viewport.get("width") or 0
    viewport_height = viewport.get("height") or 0
    if viewport_width <= 0 or viewport_height <= 0:
        return True
    return not (
        box["x"] >= viewport_width
        or box["x"] + box["width"] <= 0
        or box["y"] >= viewport_height
        or box["y"] + box["height"] <= 0
    )


def _iou(box_a: dict[str, float], box_b: dict[str, float]) -> float:
    ax1, ay1 = box_a["x"], box_a["y"]
    ax2, ay2 = ax1 + box_a["width"], ay1 + box_a["height"]
    bx1, by1 = box_b["x"], box_b["y"]
    bx2, by2 = bx1 + box_b["width"], by1 + box_b["height"]

    inter_width = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_height = max(0, min(ay2, by2) - max(ay1, by1))
    inter_area = inter_width * inter_height
    if inter_area <= 0:
        return 0.0

    union_area = _box_area(box_a) + _box_area(box_b) - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def _has_no_visible_text(element: ElementHandle) -> bool:
    try:
        if not element.is_visible():
            return True
        text = element.evaluate("(el) => (el.innerText || '').trim()")
    except Exception:
        return True
    return not bool(text)


def _section_title(element: ElementHandle) -> str | None:
    try:
        title = element.evaluate(
            """
            (el) => {
              const label = el.getAttribute('aria-label');
              if (label) return label.trim();
              const labelledby = el.getAttribute('aria-labelledby');
              if (labelledby) {
                const labelEl = document.getElementById(labelledby);
                if (labelEl && labelEl.textContent) {
                  return labelEl.textContent.trim();
                }
              }
              const heading = el.querySelector('h1, h2, h3');
              if (heading && heading.textContent) {
                return heading.textContent.trim();
              }
              return '';
            }
            """
        )
    except Exception:
        return None
    if not title:
        return None
    return str(title)


def _section_selector(element: ElementHandle) -> str | None:
    try:
        selector = element.evaluate(
            """
            (el) => {
              const tag = el.tagName.toLowerCase();
              if (el.id) return `${tag}#${el.id}`;
              if (el.classList && el.classList.length) {
                const classes = Array.from(el.classList).slice(0, 2).join('.');
                if (classes) return `${tag}.${classes}`;
              }
              return tag;
            }
            """
        )
    except Exception:
        return None
    if not selector:
        return None
    return str(selector)
