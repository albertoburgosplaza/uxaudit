# uxaudit

[![PyPI](https://img.shields.io/pypi/v/uxaudit.svg)](https://pypi.org/project/uxaudit/)
[![Python](https://img.shields.io/pypi/pyversions/uxaudit.svg)](https://pypi.org/project/uxaudit/)
[![CI](https://github.com/albertoburgosplaza/uxaudit/actions/workflows/ci.yml/badge.svg)](https://github.com/albertoburgosplaza/uxaudit/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/uxaudit.svg)](https://github.com/albertoburgosplaza/uxaudit/blob/main/LICENSE)

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
