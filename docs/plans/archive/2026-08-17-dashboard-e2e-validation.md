# Plan 14: Dashboard — Validación E2E y checklist final

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 6)
**Depende de:** planes 2-13 que estén aprobados e implementados; si el retiro del popup no se aprueba, validar también el flujo que se conserve.
**Decisiones confirmadas:** validación final funcional, visual y de accesibilidad; sin commits automáticos; corroborar criterios globales del master §8.

## 1. Objetivo

Ejecutar la validación de cierre de todo el rediseño: suite completa unit/integración, e2e (dashboard, nutrición, splits, registro), accesibilidad axe/WCAG, auditorías de consistencia/UI y Lighthouse; revisar criterios globales del master §8 y detectar código muerto de rutas eliminadas.

## 2. Alcance

- Ejecución de todos los gates de calidad.
- Barrido `audit_ui.py` sobre copia de DB real.
- Auditoría de consistencia de componentes (`audit_consistency.py`).
- Verificación manual de los criterios globales (master §8).
- Limpieza de código muerto de rutas eliminadas (exports retirados plan 2) y validación de no-regresiones.

## 3. Fuera de alcance

- Nuevos features (si un e2e descubre hueco, se crea plan atómico aparte).
- Commits/PR.

## 4. Estado de referencia

- Gates por plan: `uv sync --locked`; unit con cobertura ≥90% (addopts); e2e separados (`--no-cov`); ruff format/check; mypy `app.py src tests`.
- CI (`.github/workflows/ci.yml`): jobs quality (ruff/mypy), unit (assets + frontend budget + test_ui_consistency + coverage por módulo), browser (e2e -q --no-cov), lighthouse (P90/A90/BP90/SEO90).
- Auditoría manual: `scripts/audit_ui.py --db <copia>` (nunca toca la DB original; findings P0/P1/P2).
- Gate de vocabulario: `scripts/audit_consistency.py` (vía `tests/test_ui_consistency.py` en CI).

## 5. Checklist de validación (paso a paso)

### 5.1 Suite completa

1. `uv sync --locked`.
2. `uv run pytest` (unit+integración): **cobertura 90% branch**; revisar `term-missing`.
3. Cobertura por módulo crítica: `uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py src/analysis_data.py src/dashboard_service.py --min 90`.
4. `uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py`.
5. `uv run pytest tests/e2e/test_accessibility.py -q --no-cov`.
6. `uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests`.
7. Assets al día (CI lo exige): `scripts/build_design_tokens.py --check` + `scripts/build_css.sh` + repro de `static/css/tailwind.css` commiteado.

### 5.2 Auditorías

1. `uv run python scripts/audit_consistency.py` (vocabulario canónico; sin repetir hex/utilidades prohibidas).
2. Antes del barrido, actualizar los marcadores y acciones esperadas de `scripts/audit_ui.py` al contrato final (incluido popup si se conserva o `/registro` si lo sustituye).
3. Crear la copia de DB dentro de `.tmp/audit/` mediante el mecanismo del script y ejecutar `uv run python scripts/audit_ui.py --db .tmp/audit/lifestyle.db --out .tmp/audit --report docs/analysis/<fecha>-dashboard-validation.md`. Recorrido: index → catálogo → selección → granularidad → resumen/tabla → `/registro` → sesión → nutrición → cardio → plantillas → undo → exports HC → `/nivel`/`/grafica`.
3. Meta: **0 findings P0/P1**; máx. P2 conocidas documentadas.

### 5.3 Lighthouse

1. `./scripts/run_lighthouse.sh` → asserts P90/A90/BP90/SEO90 en `lighthouserc.cjs`.
2. Foco en: LCP ≤2.5s, INP ≤200ms, CLS ≤0.1 (gráfica 450px + zonas reservadas del plan 3) y a11y.

### 5.4 Revisión de criterios globales (master §8)

Recorrer la lista punto a punto:
- [ ] Selección de músculos/ejercicios sin parpadeos visibles (plan 6).
- [ ] La página no cambia de altura perceptible (plans 3/4; CLS medido ≤1px).
- [ ] Catálogo de ejercicios a la izquierda en escritorio, usable en móvil (plan 4).
- [ ] La gráfica conserva contenedor/escala/posición durante actualizaciones.
- [ ] Reglas de líneas global/músculo/ejercicio consistentes (plan 7).
- [ ] La vista diaria es la predeterminada (plan 8).
- [ ] Semanas y meses muestran gráfica y resumen coherentes (plans 8/9).
- [ ] El registro diario permite editar entrenamiento/alimentación sin popup largo (plan 10).
- [ ] Controles RIR funcionan y persisten (plan 11).
- [ ] Se mantienen tokens, accesibilidad, seguridad, HTMX y cobertura.

### 5.5 Itinerario de no-regresiones y código muerto

1. Buscar solo contratos cuyo retiro haya sido aprobado. No exigir eliminar rutas CSV si el plan 2 solo retiró su UI.
2. Si se retira el popup, buscar `editor-popup|openEditorPopup` y permitir únicamente los documentos de línea base/archivo.
3. Verificar las rutas activas aprobadas: `/registro` si existe, `/splits` y export de Health Connect.

## 6. Pruebas a ejecutar (resumen del gate)

```bash
uv sync --locked
uv run pytest
uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
uv run python scripts/audit_ui.py --db .tmp/audit/lifestyle.db --out .tmp/audit --report docs/analysis/dashboard-validation.md
./scripts/run_lighthouse.sh
```

## 7. Riesgos

- **R1**: el barrido e2e descubre una regresión tardía → añadir plan de fix puntual antes de cerrar.
- **R2**: audit_ui sobre la DB real — usar siempre copia en `.tmp/` (nunca la original); sandbox.
- **R3**: Lighthouse puede fallar por perf del CDN de Plotly → optimizar lazy (ya existe) o adjudicar P90; documentar si es ambiental.
- **R4**: cobertura podría caer con código nuevo → reforzar tests en el plan que toque el módulo.

## 8. Criterios de aceptación (finales)

- Toda la suite (unit/sokay/ude/e2e/axe) verde.
- Cobertura ≥90% branch global y por módulos críticos.
- audit_ui sin P0/P1; hallazgos P2 documentados.
- Lighthouse P90/A90/BP90/SEO90.
- Criterios globales del master §8 verificados; checklist cerrado.
- Sin código muerto de rutas eliminadas; versión lista para revisión (sin commit automático).

## 9. Cierre

Con este plan verde, la rama queda lista para revisión humana y commit voluntario del usuario. No se hacen commits ni pushes automáticos.
