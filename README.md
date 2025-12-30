# uxaudit

[![PyPI](https://img.shields.io/pypi/v/uxaudit.svg)](https://pypi.org/project/uxaudit/)
[![Python](https://img.shields.io/pypi/pyversions/uxaudit.svg)](https://pypi.org/project/uxaudit/)
[![CI](https://github.com/albertoburgosplaza/uxaudit/actions/workflows/ci.yml/badge.svg)](https://github.com/albertoburgosplaza/uxaudit/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/uxaudit.svg)](https://github.com/albertoburgosplaza/uxaudit/blob/main/LICENSE)

<img src="docs/uxaudit-logo.png" alt="UXAudit logo" width="220">

UX/UI audit tool that captures screenshots and analyzes them with Gemini.

## Highlights

- Full-page and section screenshots with evidence links.
- Multi-page crawling from header, nav, and footer.
- Structured JSON output for agents and pipelines.

## Requirements

- Python 3.10+
- Playwright browsers: `playwright install`
- Gemini API key: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)

## Install

### PyPI

```bash
python3 -m pip install uxaudit
```

### Editable (dev)

```bash
python3 -m pip install -e .[dev]
```

## Usage

```bash
export GEMINI_API_KEY="your-key"
uxaudit analyze https://example.com --model flash
```

Outputs are written to `runs/<run_id>/` with `manifest.json` and `report.json`.

## Crawling multiple pages

```bash
uxaudit analyze https://example.com --max-pages 5
```

## Style consistency analysis

By default uxaudit runs a cross-screenshot style consistency pass. You can disable
it or tune the batch size:

```bash
uxaudit analyze https://example.com --no-style-consistency
uxaudit analyze https://example.com --style-consistency-batch-size 10
```

## Login (form-based)

```bash
# Example with fake credentials
export UXAUDIT_AUTH_USERNAME="alex.rios@example.test"
export UXAUDIT_AUTH_PASSWORD="P@ssw0rd-Example-123"

uxaudit analyze https://demo.example.test \\
  --auth-mode form \\
  --auth-login-url https://demo.example.test/login \\
  --auth-post-login-url https://demo.example.test/app \\
  --auth-username-selector "#email" \\
  --auth-password-selector "#password" \\
  --auth-submit-selector "button[type=submit]" \\
  --auth-success-selector ".dashboard"
```

## Login (storage state)

```bash
uxaudit analyze https://app.example.com \\
  --auth-mode storage_state \\
  --auth-storage-state /path/to/storage_state.json
```

## Development

```bash
ruff check .
ruff format .
mypy uxaudit
pytest
```

## Project links

- Source: https://github.com/albertoburgosplaza/uxaudit
- Issues: https://github.com/albertoburgosplaza/uxaudit/issues
- Changelog: https://github.com/albertoburgosplaza/uxaudit/blob/main/CHANGELOG.md

## CLI options

```bash
uxaudit analyze --help
```
