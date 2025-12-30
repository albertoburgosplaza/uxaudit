from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from uxaudit.audit import run_audit
from uxaudit.config import AuditConfig, AuthConfig, Settings

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
    headless: bool,
    style_consistency: bool,
    style_consistency_batch_size: int,
    wait_until: Literal["load", "domcontentloaded", "networkidle"],
    timeout_ms: int,
    user_agent: str | None,
    auth_mode: Literal["none", "form", "storage_state", "basic"],
    auth_login_url: str | None,
    auth_post_login_url: str | None,
    auth_username: str | None,
    auth_password: str | None,
    auth_username_selector: str | None,
    auth_password_selector: str | None,
    auth_submit_selector: str | None,
    auth_success_selector: str | None,
    auth_success_url: str | None,
    auth_storage_state: Path | None,
    auth_save_storage_state: bool,
) -> None:
    settings = Settings()
    if not settings.api_key:
        typer.echo("Missing API key. Set GEMINI_API_KEY or GOOGLE_API_KEY.")
        raise typer.Exit(code=1)

    if auth_mode != "none":
        auth_config = AuthConfig(
            mode=auth_mode,
            login_url=auth_login_url,
            post_login_url=auth_post_login_url,
            username=auth_username or settings.auth_username,
            password=auth_password or settings.auth_password,
            username_selector=auth_username_selector,
            password_selector=auth_password_selector,
            submit_selector=auth_submit_selector,
            success_selector=auth_success_selector,
            success_url=auth_success_url,
            storage_state_path=auth_storage_state,
            save_storage_state=auth_save_storage_state,
        )
    else:
        auth_config = None

    config = AuditConfig(
        url=url,
        model=model,
        max_pages=max_pages,
        max_total_screenshots=max_total_screenshots,
        max_sections_per_page=max_sections_per_page,
        output_dir=out,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        headless=headless,
        style_consistency=style_consistency,
        style_consistency_batch_size=style_consistency_batch_size,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        user_agent=user_agent,
        auth=auth_config,
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
    headless: bool = typer.Option(True, help="Run browser headless"),
    style_consistency: bool = typer.Option(
        True, help="Run cross-screenshot style consistency analysis"
    ),
    style_consistency_batch_size: int = typer.Option(
        8, help="Screenshots per style consistency request"
    ),
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = typer.Option(
        "networkidle", help="Navigation wait condition"
    ),
    timeout_ms: int = typer.Option(45_000, help="Navigation timeout in ms"),
    user_agent: str | None = typer.Option(None, help="Custom user agent"),
    auth_mode: Literal["none", "form", "storage_state", "basic"] = typer.Option(
        "none", help="Authentication mode"
    ),
    auth_login_url: str | None = typer.Option(None, help="Login page URL"),
    auth_post_login_url: str | None = typer.Option(None, help="Post-login URL"),
    auth_username: str | None = typer.Option(None, help="Login username"),
    auth_password: str | None = typer.Option(None, help="Login password"),
    auth_username_selector: str | None = typer.Option(
        None, help="CSS selector for username input"
    ),
    auth_password_selector: str | None = typer.Option(
        None, help="CSS selector for password input"
    ),
    auth_submit_selector: str | None = typer.Option(
        None, help="CSS selector for submit button"
    ),
    auth_success_selector: str | None = typer.Option(
        None, help="Selector indicating login success"
    ),
    auth_success_url: str | None = typer.Option(
        None, help="URL or glob pattern indicating login success"
    ),
    auth_storage_state: Path | None = typer.Option(
        None, help="Path to Playwright storage_state JSON"
    ),
    auth_save_storage_state: bool = typer.Option(
        True, help="Save storage_state after login"
    ),
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
        headless=headless,
        style_consistency=style_consistency,
        style_consistency_batch_size=style_consistency_batch_size,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        user_agent=user_agent,
        auth_mode=auth_mode,
        auth_login_url=auth_login_url,
        auth_post_login_url=auth_post_login_url,
        auth_username=auth_username,
        auth_password=auth_password,
        auth_username_selector=auth_username_selector,
        auth_password_selector=auth_password_selector,
        auth_submit_selector=auth_submit_selector,
        auth_success_selector=auth_success_selector,
        auth_success_url=auth_success_url,
        auth_storage_state=auth_storage_state,
        auth_save_storage_state=auth_save_storage_state,
    )
