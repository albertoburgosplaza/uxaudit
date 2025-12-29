from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from uxaudit.config import AuditConfig, AuthConfig
from uxaudit.utils import ensure_dir


@dataclass
class AuthResult:
    storage_state_path: Path | None
    landing_url: str | None


def perform_login(
    context: BrowserContext,
    auth: AuthConfig,
    config: AuditConfig,
    run_dir: Path,
) -> AuthResult:
    login_url = auth.login_url or config.url
    _validate_form_auth(auth)

    page = context.new_page()
    try:
        page.goto(login_url, wait_until=config.wait_until, timeout=config.timeout_ms)
        page.fill(auth.username_selector or "", auth.username or "")
        page.fill(auth.password_selector or "", auth.password or "")
        if auth.submit_selector:
            page.click(auth.submit_selector)
        else:
            page.press(auth.password_selector or "", "Enter")
        _wait_for_success(page, auth, config)
        landing_url = page.url
    finally:
        page.close()

    storage_state_path = None
    if auth.save_storage_state:
        storage_state_path = _resolve_storage_state_path(auth, run_dir)
        ensure_dir(storage_state_path.parent)
        context.storage_state(path=str(storage_state_path))

    return AuthResult(storage_state_path=storage_state_path, landing_url=landing_url)


def _wait_for_success(page: Page, auth: AuthConfig, config: AuditConfig) -> None:
    if auth.success_url:
        page.wait_for_url(auth.success_url, timeout=config.timeout_ms)
        return
    if auth.success_selector:
        page.wait_for_selector(auth.success_selector, timeout=config.timeout_ms)
        return
    page.wait_for_load_state(config.wait_until, timeout=config.timeout_ms)


def _resolve_storage_state_path(auth: AuthConfig, run_dir: Path) -> Path:
    if auth.storage_state_path:
        return auth.storage_state_path
    return run_dir / "auth" / "storage_state.json"


def _validate_form_auth(auth: AuthConfig) -> None:
    missing = []
    if not auth.username:
        missing.append("username")
    if not auth.password:
        missing.append("password")
    if not auth.username_selector:
        missing.append("username_selector")
    if not auth.password_selector:
        missing.append("password_selector")
    if missing:
        raise ValueError("Missing auth fields for form login: " + ", ".join(missing))
