from __future__ import annotations

from pathlib import Path

import typer

from uxaudit.audit import run_audit
from uxaudit.config import AuditConfig, Settings

app = typer.Typer(add_completion=False)


@app.command()
def analyze(
    url: str = typer.Argument(..., help="URL to analyze"),
    model: str = typer.Option("flash", help="Model name or alias: flash|pro"),
    out: Path = typer.Option(Path("runs"), help="Output directory"),
    max_pages: int = typer.Option(1, help="Maximum pages to visit"),
    max_total_screenshots: int = typer.Option(1, help="Maximum screenshots to capture"),
    max_sections_per_page: int = typer.Option(8, help="Maximum sections per page to capture"),
    viewport_width: int = typer.Option(1440, help="Viewport width"),
    viewport_height: int = typer.Option(900, help="Viewport height"),
    wait_until: str = typer.Option("networkidle", help="Navigation wait condition"),
    timeout_ms: int = typer.Option(45_000, help="Navigation timeout in ms"),
    user_agent: str | None = typer.Option(None, help="Custom user agent"),
    analysis_timeout_s: float = typer.Option(60.0, help="Gemini analysis timeout in seconds"),
    analysis_max_retries: int = typer.Option(3, help="Gemini analysis max retries"),
    analysis_backoff_initial_s: float = typer.Option(1.0, help="Initial backoff (seconds) for Gemini retries"),
    analysis_backoff_factor: float = typer.Option(2.0, help="Backoff multiplier for Gemini retries"),
    max_image_dimension: int = typer.Option(1600, help="Max width/height for analysis images"),
    max_image_bytes: int = typer.Option(2_000_000, help="Target max image size (bytes) for analysis"),
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
        analysis_timeout_s=analysis_timeout_s,
        analysis_max_retries=analysis_max_retries,
        analysis_backoff_initial_s=analysis_backoff_initial_s,
        analysis_backoff_factor=analysis_backoff_factor,
        max_image_dimension=max_image_dimension,
        max_image_bytes=max_image_bytes,
    )
    _, run_dir = run_audit(config, settings)
    typer.echo(f"Report written to {run_dir / 'report.json'}")
