# Web Standards — Guía Unificada de Desarrollo

> **Propósito:** Referencia única de buenas prácticas para el desarrollo de este dashboard,
> sintetizada de las guías de industria (Web.dev/Core Web Vitals, WCAG 2.2, OWASP, Nielsen
> Norman Group, Material Design 3, Apple HIG, MDN/W3C) y adaptada a la arquitectura real del
> proyecto (FastAPI + Jinja2 + htmx + SQLite + Plotly). Cualquier cambio de interfaz, template
> o ruta debe respetar estos principios; los ítems de la sección 10 son la lista de verificación
> mínima antes de declarar una tarea completa.

---

## 1. Principio rector — Server-First por diseño

La arquitectura del proyecto **es** el patrón recomendado por la industria para webs rápidas:
HTML renderizado en servidor + htmx para actualizaciones parciales, con JavaScript como capa
de **mejora progresiva** (el dashboard funciona sin JS; el JS solo añade interacción).

- HTML5 semántico obligatorio (`<header>`, `<nav>`, `<main>`, `<section>`, `<article>`,
  `<form>`, `<button>`, `<label>`). Un `<div>` interactivo (con click handlers) es un
  antipatrón: usa `<button>` o `<a>`.
- Prohibido introducir SPAs, frameworks client-side o hidratación: la UI se compone en el
  servidor (Jinja2) y se actualiza con fragmentos htmx + `hx-swap-oob`.
- La validación de negocio y el cálculo de datos **siempre** en el servidor; el cliente solo
  previsualiza (p. ej. `alimento_map` para mostrar macros, nunca para decidirlos).
- Los handlers siguen siendo `def` síncronos (FastAPI los ejecuta en threadpool): no
  bloquear el event loop ni introducir I/O asíncrono innecesario.

## 2. Rendimiento — barreras objetivas (Core Web Vitals)

| Métrica | Qué mide | Umbral | Guardrail en este proyecto |
|---|---|---|---|
| **LCP** | Carga del elemento visual principal | ≤ 2.5 s | Plotly no debe bloquear el LCP; el HTML del editor/tablas llega primero |
| **INP** | Capacidad de respuesta a interacciones | ≤ 200 ms | Fragmentos htmx ligeros; sin JS de bloqueo tras la interacción |
| **CLS** | Estabilidad visual | ≤ 0.1 | Nunca insertar contenido encima de existente; dimensiones reservadas |

Reglas:

- Los swaps de htmx **no** deben causar layout shift: reserva espacio (o usa `hx-swap`
  adecuado) para noticias, tablas y gráficas.
- Cero JavaScript inicial no crítico: `app.js` y módulos ES se cargan como módulos; no
  agregar scripts de terceros ni librerías client-side nuevas sin revisar el presupuesto.
- El peso de las gráficas Plotly se mantiene bajo control (no duplicar bundles ni inline
  gigantes); revisar `base.html` ante cualquier cambio de recursos.
- Imágenes con dimensiones definidas (`assets/body_map.svg` incluido) y `alt` descriptivo.
- Medición: tras cambios visuales significativos, auditar con Lighthouse/PageSpeed Insights
  y verificar que Performance, Accessibility, Best Practices y SEO ≥ 90.

## 3. Sistema de diseño y tokens

La coherencia visual se sistematiza, no se diseña página por página.

- **Fuente única de verdad:** `tailwind.config.js` (paleta matte/burgundy, escala) + CSS
  custom properties. **Si un valor no está en un token, no se usa.**
- Paleta vigente: fondo `matte-950`/`neutral-900`, acento `burgundy-700`/`burgundy-400`
  (`#9b1b30`/`#e56d88`), toques neón (`neon-border`, `neon-title`).
- Escalas: espaciado en múltiplos de 4/8 px; tipografía base 16 px con interlineado ~1.5;
  jerarquía tipográfica por tamaño/peso, no por capricho.
- Gráficas Plotly con `plot_bgcolor`/`paper_bgcolor` transparentes para integrarse al tema.
- **Estados siempre diseñados:** vacío, carga, error y éxito — no solo el estado ideal.
  El patrón de notices OOB (`#notice-container`, `#editor-notice`) cubre los estados de
  feedback: mantenerlo uniforme en nuevas features.

## 4. Accesibilidad — WCAG 2.2 nivel AA (mínimo)

Principios POUR aplicados al proyecto:

- **Perceptible:** contraste ≥ 4.5:1 en texto normal (verificar burgundy sobre matte en
  texto pequeño); nunca comunicar con color únicamente (un error es rojo **+ icono + texto**).
  Respetar `prefers-reduced-motion` en transiciones/animaciones (htmx, fade-in).
- **Operable:** 100% navegable por teclado; foco siempre visible (nunca `outline: none`
  indiscriminado); objetivos táctiles ≥ 44×44 px en botones/inputs del editor.
- **Comprensible:** jerarquía de encabezados h1→h2 sin saltos; labels asociados a inputs;
  mensajes de error predictivos junto al campo (notices con texto claro).
- **Robusto:** HTML semántico; WAI-ARIA solo cuando no existe elemento nativo (modales,
  menús); `alt` descriptivo en imágenes.

Verificación: incluir chequeo de teclado en los e2e Playwright y ejecutar axe/WAVE ante
cambios de template.

## 5. Seguridad — resumen operativo

Detalle completo en `docs/architecture/security-model.md`. Invariantes:

- **CSP estática** (`src/security.py`): `script-src 'self'` + orígenes CDN pinneados,
  **sin nonce y sin `'unsafe-inline'`** en script; `style-src 'self' 'unsafe-inline'`
  (requerido por Plotly); `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`.
  Cero scripts inline ejecutables; los datos viajan en `<script type="application/json">`
  (`#app-config`), que no se ejecuta.
- Cabeceras: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
  `X-Frame-Options: DENY`.
- **CSRF** en toda mutación: token firmado (`X-CSRF-Token` desde `#app-config`) + validación
  de Origin; exención solo por igualdad exacta de ruta (`CSRF_EXEMPT_PATHS`).
- **SQL parametrizado** (`?`) en todas las consultas; autoescape de Jinja2 como única
  frontera HTML; los fragmentos OOB solo tocan targets allow-listed.
- **Secretos:** nunca en el cliente. El token de HealthSync vive en `data/hc_sync_token`
  (server-side) y en Keystore/DataStore de la app Android.
- Modelo de despliegue: personal y loopback-only por defecto; cualquier exposición a red
  exige diseño de autenticación/autorización previo (ver security-model §"Before exposing
  on a network").

## 6. UX y arquitectura de información

Heurísticas de Nielsen aplicadas al dashboard:

- **Visibilidad del estado del sistema:** toda mutación responde con feedback inmediato
  (notices OOB con auto-dismiss).
- **Control y libertad del usuario:** la pila de undo (máx. 10) es un pilar de esta guía —
  cualquier nueva mutación debe registrarse en ella para ser deshacible.
- **Prevención y recuperación de errores:** validación en servidor + gating client-side
  (`#editor-state[data-readonly]`), backup automático antes de mutaciones/migraciones.
- **Consistencia:** mismos patrones de formulario, botonera y notificación en todas las
  features (entrenamiento, alimentación, plantillas).
- **Reconocimiento sobre recuerdo:** fecha visible en el navigator, ejercicios con
  autocomplete/lista, selección por categoría muscular.

Arquitectura de información: cada pantalla debe responder a
**"dónde estoy → qué puedo hacer → qué es importante → qué ocurre después"**
(date navigator → editor → guardar/undo).

## 7. SEO técnico (acotado)

App personal sin exposición pública: se aplica solo el subconjunto técnico que también
beneficia accesibilidad y mantenimiento:

- HTML semántico y jerarquía de encabezados correcta.
- `<title>` descriptivo y `<meta name="description">` en `base.html`.
- URLs limpias y estables (contratos de `current-ui-contract.md`).
- Contenido renderizable sin JS (ya garantizado por server-first).

Quedan fuera de alcance: sitemap.xml, robots.txt, Open Graph, datos estructurados
(schema.org) y estrategias SSR/SSG — se reconsideran solo si el proyecto se expone
públicamente.

## 8. Calidad y medición continua

Puertas de calidad (invariantes, ver `AGENTS.md` §8):

1. `uv run pytest` — unidad + integración + e2e Playwright (servidor aislado + DB temporal).
2. `uv run ruff format --check .` y `uv run ruff check .`.
3. `uv run mypy app.py src tests`.
4. Verificación visual local (`./scripts/start_server.sh` o `uv run uvicorn app:app --host 127.0.0.1 --reload`).
5. Auditoría Lighthouse ≥ 90 (Performance, Accessibility, Best Practices, SEO) ante cambios
   visuales significativos; registrar en `docs/operations/release-checklist.md`.
6. Los contratos de UI (`current-ui-contract.md`) y de sync (`health-sync-contract.md`) se
   actualizan cuando cambian IDs, `data-*`, campos de formulario o targets OOB — con su
   prueba de browser asociada.

## 9. Antipatrones a evitar

| Antipatrón | Por qué | Alternativa |
|---|---|---|
| SPA monolítica con megabytes de JS | Destruye LCP/INP y duplica la lógica de datos | Server-first + htmx (arquitectura actual) |
| Valores hardcodeados fuera de tokens | Incoherencia visual y deriva de estilo | Token de `tailwind.config.js`/custom properties |
| `<div>` con `onclick` / roles interactivos | Inaccesible y no navegable por teclado | `<button>`/`<a>` nativos |
| `outline: none` global | Destruye la navegación por teclado | Focus visible diseñado |
| Macros calculados en el cliente | El servidor debe ser la fuente de verdad | Recalcular en servidor (nutrientes, RM, PFR) |
| Ignorar estados vacío/error | Usuario no sabe qué ocurre | Estado diseñado + notice OOB |
| Mutaciones sin push a la pila de undo | Pérdida de control del usuario | Registrar backup + before/after en undo |
| Bloquear con scripts de terceros | Penaliza CWV y superficie de ataque | Recursos pinneados, módulos diferidos |

## 10. Checklist mínimo (antes de dar una tarea por completa)

- [ ] HTML semántico correcto (sin `<div>` interactivos, headings jerarquizados).
- [ ] Valores visuales desde tokens (sin colores/márgenes/fuentes hardcodeados).
- [ ] Estados vacío/error/éxito cubiertos con el patrón de notices existente.
- [ ] Navegable con teclado; foco visible; contraste ≥ 4.5:1; sin color-solo para errores.
- [ ] Sin scripts inline ejecutables; CSP intacta; mutaciones con CSRF; SQL parametrizado.
- [ ] Mutaciones: backup + push a la pila de undo (o justificación explícita de exclusión).
- [ ] Sin layout shift en swaps htmx (CLS < 0.1).
- [ ] `uv run pytest` + `ruff format --check` + `ruff check` + `mypy` en verde.
- [ ] Contratos (`current-ui-contract.md`) y este documento actualizados si aplica.
