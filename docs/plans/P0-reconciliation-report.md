# P0 — Cierre de reconciliación y separación de contaminación semántica

**Fecha:** 2026-08-27
**Estado:** P0 ejecutado, separación completa (pure + métricas/cohortes) — visual 27 files
**Rama:** working tree actual (sin HEAD limpio), sin `git reset/checkout/clean`, sin commit/push
**Evidencia:** `.tmp/semantic-contamination.patch` (1101 líneas, diff completo pre-separación), `.tmp/P0-pure-contamination.patch` (128 líneas, RIR/daily_volume) y `.tmp/P0-domain-metrics-cohortes.patch` (645 líneas, métricas/cohortes)

## Alcance revisado

`git status --short` inicial: 37 M + 3 ??
`git diff --stat` inicial: 1844 ins / 266 del (37 files)
`git diff --check`: vacío
Validaciones iniciales: `uv sync --locked` ok, `ruff check/format` ok, `mypy` 81 files ok, `pytest --ignore=tests/e2e` 682 passed, coverage 92.94% (>90%)

Revisión archivo por archivo completa (ver entrega P0 previa). Clasificación en 4 categorías definida en `MASTER-PLAN.md:32`.

## Separación ejecutada (2026-08-27, build mode)

Trabajo del usuario preservado en `.tmp/semantic-contamination.patch` antes de cualquier revert.

### Contaminación pura separada (revertida del working tree, no borrada)

Estos cambios son **dominio no autorizado por P0/P1** y fueron revertidos a HEAD para dejar el commit visual limpio. Quedan preservados en `.tmp/P0-pure-contamination.patch` para commit independiente `domain: RIR + análisis` o plan propio:

| Archivo | Líneas | Cambio revertido |
|---|---|---|
| `src/analysis_data.py:129` | -13 | Eliminación `daily_volume()` (tonelaje diario) |
| `src/training_service.py:9` | 2 | `RIR_MIN -5.0 → -1.0` y comentario forzadas |
| `static/js/editor.js:195` | 4 | `RIR_MIN -5 → -1` + `FORZADA → FALLO PARCIAL` |
| `templates/session_editor.html:125` | 6 | `min="-5" → "-1"` + title/sr-only |
| `tests/test_analysis_data.py:17` | -14 | Borrado `test_volume_suma_diaria` |
| `tests/test_training_service.py:186` | 2 | `rir -2 → -0.9` |

Comando: `git show HEAD:<path> > <path>`. Tras primer revert, `git status` pasó a 30 M + 3 ??, `git diff --stat` 1832 ins / 227 del.

### Contaminación métricas/cohortes separada (autorizada 2026-08-27)

Separación selectiva (sin revert de archivos completos) preservando visual. Parche: `.tmp/P0-domain-metrics-cohortes.patch` (645 líneas, 7 files):

| Archivo | Dominio extraído (revertido) | Visual preservado |
|---|---|---|
| `src/metrics_engine.py:16` | `is_failure_set <0`, `MISSING_*`, `_weighted_group_timeline`, `cobertura` | — |
| `src/charts.py:198` | `posicion_ejercicio`, `get_exercise_cohort_summary`, `h_cobertura`/`cobertura`, `rm_primera`/`rm_ultima`/`caida_pct` (vuelve `total_tonelaje`) | `format_*_short`, `extract_point_values` (8), `point_comparison_id`, `_range_for_axis` padding Día, `margin t 48`/`legend y 1.08`, `HOVERTEMPLATE` 8 |
| `app.py:15` | `import get_exercise_cohort_summary` + `cohort_df` | `_validate_window 1–8` + OOB `dashboard-catalog-list` (orden dinámico P1.6) |
| `templates/exercise_detail.html:18` | `Posición`/`RMₐ 1ª/última`/`Caída` + tabla cohortes + `FALLO PARCIAL` | — (HEAD restaurado) |
| `tests/test_metrics_engine.py:22` | `is_failure_set`, `sets_fallo 2→1` | — |
| `tests/test_charts.py:143` | `posicion_ejercicio`/`cohort` asserts | `format_*`, `extract_point_values`, `point_comparison_id`, `HOVERTEMPLATE` 8, padding, etc. |
| `tests/test_coverage_edges.py:113` | `total_tonelaje` assert | — |

Tras revert, `git status` queda en **27 M + 4 ??** (vs 30), `git diff --stat` 1593 ins / 174 del. No quedan imports ni templates rotos (`grep cohort` vacío, `uv run python -c` imports ok).

## Estado actual del working tree (post-separación completa)

```
 M app.py
 M docs/architecture/current-ui-contract.md
 M docs/operations/release-checklist.md
 M docs/plans/app-router-modularization.md
 M docs/plans/codebase-factorization-plan.md
 M docs/plans/dashboard-implementation-gap-and-recovery.md
 M docs/plans/dashboard-recovery-1-vertical-slice.md
 M docs/plans/dashboard-recovery-2-3-catalog-granularity-summary.md
 M src/charts.py
 M src/database.py
 M src/response_fragments.py
 M src/summary_service.py
 M static/css/cascade.css
 M static/css/components.css
 M static/css/period-summary.css
 M static/css/tailwind.css
 M static/js/chart-interaction.js
 M static/js/level-cascade.js
 M templates/index.html
 M templates/partials/period_summary_panel.html
 M tests/e2e/test_accessibility.py
 M tests/e2e/test_dashboard_flow.py
 M tests/test_app.py
 M tests/test_charts.py
 M tests/test_database.py
 M tests/test_frontend_budget.py
 M tests/test_summary_service.py
?? docs/architecture/dashboard-current.md
?? docs/plans/MASTER-PLAN.md
?? docs/plans/P0-reconciliation-report.md
?? docs/plans/dashboard-ux-refinement.md
```

27 M + 4 ?? (vs 37 iniciales). Desaparecen 10 files de dominio: `src/metrics_engine.py`, `src/analysis_data.py`, `src/training_service.py`, `static/js/editor.js`, `templates/exercise_detail.html`, `templates/session_editor.html`, `tests/test_analysis_data.py`, `tests/test_training_service.py`, `tests/test_metrics_engine.py`, `tests/test_coverage_edges.py`. Los 3 mixtos (`src/charts.py`, `app.py`, `tests/test_charts.py`) quedan pero sin hunks de dominio.

Untracked son scaffolding P0/P1. Los dominios separados quedan en `.tmp/P0-pure-contamination.patch` (6 files) y `.tmp/P0-domain-metrics-cohortes.patch` (7 files, 645 líneas). El broad `.tmp/semantic-contamination.patch` (1101 líneas) se conserva como evidencia pre-separación.

## Validaciones post-separación completa

```
uv sync --locked: Resolved 51, Audited 46
ruff check: All checks passed
ruff format --check: 154 files already formatted
mypy app.py src tests: Success 81 files
git diff --check: vacío
pytest --ignore=tests/e2e -q: 682 passed, 1 warning, coverage 92.96% (>90%)
  TOTAL 3559 stmts (vs 3625 con dominio), 200 miss
```

## Límites claros

- **Commit visual Fase 2** (listo): 27 M + 4 ?? arriba. No contiene `posicion_ejercicio`, `cohort`, `cobertura`, `is_failure_set`, `FALLO PARCIAL`, `rm_primera` etc. La comparación visual (clic/Shift/Escape, periodo corto, VAR/Series/Reps/Peso/RIR/RM, orden dinámico) no depende de cohortes.
- **Commit dominio puro** (ya separado): `.tmp/P0-pure-contamination.patch` (6 files, 128 líneas) → `domain: RIR -1 y daily_volume`
- **Commit dominio métricas/cohortes** (ya separado): `.tmp/P0-domain-metrics-cohortes.patch` (7 files, 645 líneas) → `domain: cohortes + posicion + cobertura + weighted timeline`
- **Commit planificación**: `docs/architecture/dashboard-current.md` + `MASTER-PLAN.md` + `dashboard-ux-refinement.md` + `docs/plans/P0-reconciliation-report.md` + estados `PAUSADA/SUPERADO` + `release-checklist.md`

## Cierre P0

P0 puede marcarse **COMPLETADA** en `MASTER-PLAN.md:16`. Siguiente: commit independiente de planificación, luego commit visual Fase 2 (27 files) sin mezclar dominio.

No se hizo commit ni push. `.tmp/` debe conservarse hasta los commits.
