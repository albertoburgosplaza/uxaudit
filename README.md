# uxaudit

Command-line UX/UI audit tool that captures screenshots and analyzes them with Gemini.

## Quick start

```bash
uxaudit analyze https://example.com --model flash
```

Outputs are written to `runs/<run_id>/` with `manifest.json` and `report.json`.

## Crawling multiple pages

Use `--max-pages` to visit links discovered in `nav`, `header`, and `footer` on the same domain.

```bash
uxaudit analyze https://example.com --max-pages 5
```
