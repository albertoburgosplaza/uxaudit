from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from uxaudit.audit import run_audit
from uxaudit.config import AuditConfig, Settings

app = typer.Typer(add_completion=False)


@app.callback()
def _callback() -> None:
    """UX/UI audit CLI."""
    return


def _run(
    url: str,
    model: str,
    out: Path,
    max_pages: int,
    max_total_screenshots: int,
    max_sections_per_page: int,
    viewport_width: int,
    viewport_height: int,
    wait_until: Literal["load", "domcontentloaded", "networkidle"],
    timeout_ms: int,
    user_agent: str | None,
) -> None:
    settings = Settings()
    if not settings.api_key:
        typer.echo("Missing API key. Set GEMINI_API_KEY or GOOGLE_API_KEY.")
        raise typer.Exit(code=1)

    config = AuditConfig(
        url=url,
        model=model,
        max_pages=max_pages,
        max_total_screenshots=max_total_screenshots,
        max_sections_per_page=max_sections_per_page,
        output_dir=out,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        user_agent=user_agent,
    )
    _, run_dir = run_audit(config, settings)
    typer.echo(f"Report written to {run_dir / 'report.json'}")


@app.command()
def analyze(
    url: str = typer.Argument(..., help="URL to analyze"),
    model: str = typer.Option("flash", help="Model name or alias: flash|pro"),
    out: Path = typer.Option(Path("runs"), help="Output directory"),
    max_pages: int = typer.Option(1, help="Maximum pages to visit"),
    max_total_screenshots: int = typer.Option(1, help="Maximum screenshots to capture"),
    max_sections_per_page: int = typer.Option(
        8, help="Maximum sections per page to capture"
    ),
    viewport_width: int = typer.Option(1440, help="Viewport width"),
    viewport_height: int = typer.Option(900, help="Viewport height"),
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = typer.Option(
        "networkidle", help="Navigation wait condition"
    ),
    timeout_ms: int = typer.Option(45_000, help="Navigation timeout in ms"),
    user_agent: str | None = typer.Option(None, help="Custom user agent"),
) -> None:
    _run(
        url=url,
        model=model,
        out=out,
        max_pages=max_pages,
        max_total_screenshots=max_total_screenshots,
        max_sections_per_page=max_sections_per_page,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        user_agent=user_agent,
    )
