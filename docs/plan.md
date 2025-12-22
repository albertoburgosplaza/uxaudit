# Plan técnico y de producto: paquete Python para auditoría UX/UI con capturas + Gemini 3

## Objetivo
Construir un **paquete Python** que, dado un **URL**, descubra y recorra “todas las secciones” relevantes (con límites), genere **capturas de pantalla** (por página y por sección), las analice con **Gemini 3 Pro o Gemini 3 Flash** (seleccionable por parámetro) y devuelva **recomendaciones priorizadas** de mejoras de diseño, en **JSON estructurado** apto para agentes.

## Supuestos y compatibilidad (modelos/SDK)
- Modelos (preview): `gemini-3-pro-preview`, `gemini-3-flash-preview`.
- SDK recomendado en Python: `google-genai`.
- En Vertex AI, Gemini 3 requiere `google-genai` **1.51.0+** y configuración global (location global).

---

## 1) Resultado deseado (definición operativa)

### Entrada
- `url: str`
- `model: Literal["gemini-3-pro-preview","gemini-3-flash-preview"]` (o alias `pro|flash`)
- Config adicional (ejemplos):
  - límites de rastreo: `max_pages`, `depth`, `max_sections_per_page`, `max_total_screenshots`
  - auth: cookies / credenciales / sin autenticación
  - formato de salida: JSON

### Salida
- **JSON estructurado con esquema estable**, incluyendo:
  - targets visitados: páginas y secciones
  - artefactos capturados: rutas/URLs a screenshots + metadatos
  - recomendaciones accionables: prioridad, impacto, esfuerzo, evidencia

---

## 2) Arquitectura de alto nivel (pipeline)

### Paso A — Descubrimiento (qué significa “todas las secciones”)
**Objetivo:** construir un “mapa navegable” desde el URL inicial.

**Fuentes de descubrimiento**
- Enlaces internos (mismo dominio) desde:
  - navegación (`nav`), header, footer
  - elementos visibles/clicables (menú hamburguesa, dropdowns)
  - `sitemap.xml` (opcional)
- Secciones dentro de una página:
  - anchors `#...`, elementos con `id`
  - `<section>`, landmarks ARIA
  - encabezados `h1/h2/h3` como delimitadores heurísticos

**Targets resultantes**
- `PageTarget(url)`
- `SectionTarget(url, selector|element_handle, title)`

**Control de explosión**
- Presupuestos: máximo páginas, profundidad, patrones include/exclude
- Normalización y deduplicación de URLs (evitar loops)

---

### Paso B — Render y captura (screenshots + contexto)
**Tecnología recomendada:** Playwright (headless).

**Acciones**
- Cargar URL (incluye SPA) y esperar estabilidad:
  - `networkidle` + timeouts razonables
- Capturar:
  - **full-page screenshot** (desktop)
- **screenshots por sección** (clip por bounding box del elemento)
- Opcional:
  - snapshot HTML
  - metadatos de UI (títulos, CTAs detectados, colores dominantes)

**Defaults sugeridos**
- Desktop: 1440×900
- `user_agent` configurable
- modo dark/light (opcional)

---

### Paso C — Preprocesamiento (coste y límites multimodales)
**Objetivo:** reducir coste y latencia antes de llamar al modelo.
- Convertir/redimensionar (p.ej. PNG→JPEG, ancho máx 1280)
- Deduplicar capturas casi iguales (hash perceptual)
- Muestrear/seleccionar set representativo por página para no exceder presupuesto

---

### Paso D — Análisis con Gemini (visión + heurísticas UX)
**Llamadas multimodales** a Gemini 3 con:
- Prompt de rol: “auditor UX/UI senior”
- Instrucciones para devolver:
  - problemas detectados: jerarquía visual, spacing, tipografía, contraste, consistencia, accesibilidad, densidad, claridad de CTA, etc.
  - cambios propuestos con racional y pasos concretos
  - evidencia: referencias a `screenshot_id` y ubicación (“dónde mirar”)
- Salida en **JSON** (ideal: structured outputs si se habilita)

**Parámetros**
- Selección de modelo: Pro vs Flash
- `thinking_level` (especialmente útil para controlar latencia/coste en Flash)

---

### Paso E — Agregación y priorización
**Objetivo:** entregar un backlog accionable para humanos o agentes.
- Normalizar recomendaciones (merge de duplicados, normalización de etiquetas)
- Asignar:
  - `impact`: H/M/L
  - `effort`: S/M/L
  - `priority`: P0/P1/P2 (derivada de impacto/esfuerzo + severidad)
- Entregar:
  - `top_recommendations` (máx 10–20)
  - backlog completo con evidencia

---

## 3) Diseño del paquete (CLI, estructura)

### CLI (humano + CI)
- `uxaudit analyze <url> --model flash --out ./out --max-pages 30`

### Estructura sugerida
```

uxaudit/
**init**.py
config.py          # Pydantic Settings
crawler.py         # descubrimiento + filtros
browser.py         # wrapper Playwright
capture.py         # full-page + por sección
preprocess.py      # resize/dedupe/manifest
gemini_client.py   # google-genai
prompts.py         # plantillas
schema.py          # AuditResult, Recommendation, Evidence
aggregate.py       # merge/prioritize
report.py          # serialización JSON (opcional)
storage.py         # local/S3 opcional
cli.py             # Typer
tests/
pyproject.toml

```

---

## 4) Integración con Gemini (Developer API)
- Autenticación por API key
- Modelos preview: `gemini-3-pro-preview` / `gemini-3-flash-preview`

---

## 5) Controles imprescindibles (operabilidad, coste, robustez)
- Límites:
  - `max_pages`, `depth`, `max_sections_per_page`, `max_total_screenshots`
- Filtros include/exclude:
  - regex para excluir rutas (`/logout`, `/cart`, `?utm=...`)
  - mismo dominio vs incluir subdominios
- Política de navegación:
  - evitar loops (set de URLs normalizadas)
  - throttling / rate limit
- Robustez:
  - retries con backoff (timeouts, 429)
  - logging + artefactos reproducibles (`manifest.json`)
- Coste:
  - muestreo inteligente de capturas
  - caching por URL + timestamp + config hash

---

## 6) Roadmap por iteraciones

### Iteración 1 — MVP (1 URL, 1 página, 1 viewport)
- Render Playwright + full-page screenshot
- 1 llamada a Gemini (Flash por defecto)
- JSON con 8–15 recomendaciones

### Iteración 2 — Descubrimiento básico multi-página
- Extraer links desde `nav/header/footer`
- `max_pages` y dedupe
- Captura full-page por página
- Reporte consolidado

### Iteración 3 — Secciones dentro de página
- Detectar secciones (headings/sections/anchors)
- Capturas por sección (clip)
- Recomendaciones con evidencia por sección

### Iteración 4 — Señales objetivas
- Axe-core (accesibilidad) + Lighthouse (performance/SEO)
- Incluir métricas en prompts para recomendaciones más concretas

---

## 7) Plan de ejecución inmediato (Iteración 1–2)

### Iteración 1 — Tareas concretas
- Scaffold del paquete (`pyproject.toml`, estructura base, dependencias)
- Config mínima (modelo, provider developer, salida JSON, límites por defecto)
- Playwright: cargar URL y capturar full-page (1 viewport)
- Cliente Gemini: enviar prompt + imagen y parsear JSON
- Esquemas de salida (AuditResult, Recommendation, Evidence)
- CLI `uxaudit analyze` con salida en `runs/<run_id>/`

**Criterios de aceptación**
- `uxaudit analyze <url>` produce `manifest.json`, capturas y `report.json`
- Soporta `gemini-3-flash-preview` con entrada de imagen
- Respeta `max_pages=1` y `max_total_screenshots=1` por defecto

### Iteración 2 — Tareas concretas
- Descubrimiento básico de links desde `nav/header/footer`
- Normalización + dedupe de URLs; filtro de dominio
- Captura full-page por página y consolidación de resultados
- Reporte agregado con lista de páginas visitadas

**Criterios de aceptación**
- Con `max_pages>1` visita múltiples páginas sin loops
- Salida incluye artefactos y recomendaciones por página

---

## 8) Alcance cerrado (Iteración 1–2)
1. “Todas las secciones”: páginas desde menú + secciones dentro de página.
2. Dominio: solo mismo dominio.
3. Autenticación: no analizar contenido autenticado.
4. Presupuesto por corrida: parametrizable.
5. Salida: JSON.
6. Proveedor Gemini: Developer API (API key).
7. Responsive: no analizar.

---

## 9) Defaults propuestos (si se arranca sin decisión)
- “todas las secciones” = páginas desde `nav` + secciones por `h2/h3`
- mismo dominio, profundidad 2
- `max_pages=25`, `max_total_screenshots=150` (parametrizable)
- viewport: desktop 1440×900
- modelo por defecto: `gemini-3-flash-preview`
- provider por defecto: `developer`
- salida: JSON
