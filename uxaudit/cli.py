from __future__ import annotations

from pathlib import Path

import typer

from uxaudit.audit import run_audit
from uxaudit.config import AuditConfig, Settings
from uxaudit.schema import AuditResult

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
    capture_max_attempts: int = typer.Option(2, help="Retries for page capture"),
    capture_backoff_seconds: float = typer.Option(1.5, help="Backoff between capture retries"),
    analysis_max_attempts: int = typer.Option(2, help="Retries for analysis"),
    analysis_backoff_seconds: float = typer.Option(2.0, help="Backoff between analysis retries"),
    analysis_timeout_s: float = typer.Option(60.0, help="Timeout per analysis attempt in seconds"),
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
        capture_max_attempts=capture_max_attempts,
        capture_backoff_seconds=capture_backoff_seconds,
        analysis_max_attempts=analysis_max_attempts,
        analysis_backoff_seconds=analysis_backoff_seconds,
        analysis_timeout_s=analysis_timeout_s,
    )
    report, run_dir = run_audit(config, settings)
    _print_summary(report, run_dir)


def _print_summary(report: AuditResult, run_dir: Path) -> None:
    failed_pages = [page for page in report.pages if page.status != "captured"]
    failed_sections = [section for section in report.sections if section.status != "captured"]
    summary = [
        f"Pages: {len(report.pages)} (failed: {len(failed_pages)})",
        f"Sections: {len(report.sections)} (failed: {len(failed_sections)})",
        f"Screenshots: {len(report.screenshots)}",
        f"Recommendations: {len(report.recommendations)}",
    ]
    typer.echo("Report written to {}".format(run_dir / "report.json"))
    typer.echo("Summary: " + "; ".join(summary))

    if failed_pages:
        typer.echo("Failed pages:")
        for page in failed_pages:
            typer.echo(f" - {page.url} ({page.status}): {page.error}")
    if failed_sections:
        typer.echo("Failed sections:")
        for section in failed_sections:
            typer.echo(
                f" - {section.title or section.selector or section.id} "
                f"on page {section.page_id}: {section.error}"
            )
