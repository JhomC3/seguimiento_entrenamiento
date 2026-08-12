# Gym Tracker Análisis — Plan de Implementación

> **Para Claude:** REQUIRED SUB-SKILL: Usar superpowers:executing-plans para implementar este plan tarea por tarea.

**Goal:** Convertir el dashboard en un instrumento de análisis a ancho completo (gráfica de paneles apilados con capas activables, panel "¿qué pasó el día", registro diario en modal) eliminando el panel lateral.

**Architecture:** Una sola pantalla de análisis (`GET /`) + modal de registro (reuso de fragments existentes). Capas de datos diarias agregadas desde `training_sets`, `diario_alimentacion`, `parametros_diarios` y `health_records` (JSON1 de SQLite). Gráfica con `plotly.make_subplots(shared_xaxes)`. Píldoras estilo artificialanalysis.ai (patrón segmentado deslizante) para nivel/capas/tabs.

**Tech Stack:** FastAPI + htmx + Jinja2, pandas, plotly, SQLite (JSON1), pytest, Playwright (e2e), ruff, mypy.

**Estándares del proyecto (obligatorios, AGENTS.md §6):**
- Tipado estricto en todas las firmas de `src/` y `app.py`.
- Sin `except:` genéricos: capturar excepciones específicas. Patrón aceptado: helpers de lectura DB en `app.py` con `try/except Exception` devolviendo valores seguros.
- SQL siempre parametrizado (`?`).
- Migraciones versionadas en `src/migrations/vNNN_*.py` con `VERSION`, `NAME`, `SCHEMA_SQL` y registro en `src/migrations/runner.py`.
- TDD: test que falla → implementación mínima → test que pasa → commit.
- Commits frecuentes y pequeños (un paso por commit).
- Sandbox: `uv run` siempre; nada se ejecuta fuera del proyecto.
- Gates de calidad por tarea: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app.py src tests`.

**Semántica de registro acordada:**
- `reps` = repeticiones limpias + crédito parcial de la última rep fallida (decimales: 4.5 = 4 limpias + 1 a medias). Esquema ya `REAL`.
- `rir` = 0 → fallo (el crédito parcial ya va en reps); positivo → reserva; **negativo (≥ −5)** → repeticiones forzadas (ya completadas, sin doble crédito).
- `fallo = (rir <= 0) o (reps no entero)` → señal de análisis "sets al fallo".
- `descanso_seg` → columna nueva opcional por set (migración v011).

---

## Fase 0 — Datos

### Task 1: Migración v011 — `descanso_seg`

**Files:**
- Create: `src/migrations/v011_descanso_seg.py`
- Modify: `src/migrations/runner.py`
- Test: `tests/test_database.py` (migraciones se prueban via integración existente; añadir aserción de columna)

**Step 1: Escribir la migración**

```python
"""v011 — descanso_seg: segundos de descanso opcionales por serie."""

VERSION = 11
NAME = "descanso_seg"

SCHEMA_SQL = """
ALTER TABLE training_sets ADD COLUMN descanso_seg REAL;
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
```

**Step 2: Registrarla en el runner**

En `src/migrations/runner.py` (líneas 16-17 y 28-29): añadir `v011_descanso_seg` al import y a `MIGRATIONS` (después de `v010_health_connect`).

**Step 3: Test de integración** (añadir a `tests/test_integration.py` o verificar que el runner aplica v011 sobre una BD temporal y `PRAGMA table_info(training_sets)` contiene `descanso_seg`).

**Step 4: Ejecutar**

```bash
uv run pytest tests/test_integration.py -v
uv run ruff check src/migrations/v011_descanso_seg.py
uv run mypy app.py src tests
```

**Step 5: Commit**

```bash
git add src/migrations/v011_descanso_seg.py src/migrations/runner.py tests/
git commit -m "feat: v011 migration adds descanso_seg to training_sets"
```

---

### Task 2: Migración v012 — `cardio_annotations`

**Files:**
- Create: `src/migrations/v012_cardio_annotations.py`
- Modify: `src/migrations/runner.py`

**Step 1: Escribir la migración**

```python
"""v012 — cardio_annotations: anotaciones manuales (velocidad/inclinación)
sobre sesiones EXERCISE_SESSION espejadas de Health Connect."""

VERSION = 12
NAME = "cardio_annotations"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cardio_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hc_id TEXT NOT NULL UNIQUE REFERENCES health_records(hc_id) ON DELETE CASCADE,
    velocidad_kmh REAL,
    inclinacion_pct REAL,
    notas TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
```

**Step 2:** Registrarla en `runner.py` (v012) y añadir `cardio_annotations` a `_DOMAIN_TABLES`.

**Step 3-5:** Igual que Task 1 (test de tabla + FK, gates, commit).

---

### Task 3: Validación — RIR negativo y reps decimales

**Files:**
- Modify: `src/training_service.py:59-73` (`_validate_number`), `:121` (RIR)
- Test: `tests/test_training_service.py`

**Step 1: Test que falla**

```python
def test_validate_rir_accepts_negative_down_to_min():
    sets = sets_from_form(
        ejercicios=["Press Banca"], kgs=["80"], reps=["5.5"], rirs=["-2"]
    )
    assert sets[0].rir == -2.0


def test_validate_rir_rejects_below_min():
    with pytest.raises(ValidationError):
        sets_from_form(["Press Banca"], ["80"], ["5"], ["-6"])
```

**Step 2:** Verificar que falla (hoy `num < 0` lanza ValidationError).

**Step 3: Implementar**

```python
RIR_MIN = -5.0


def _validate_number(
    value, field: str, *, allow_zero: bool = False, min_value: float = 0.0
) -> float:
    if value is None or str(value).strip() == "":
        raise ValidationError(f"El campo {field} es obligatorio.")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    if (
        math.isnan(num)
        or num in (float("inf"), float("-inf"))
        or num < min_value
        or (num == 0 and not allow_zero)
    ):
        raise ValidationError(f"El campo {field} debe ser ≥ {min_value}.")
    return num
```

y en `sets_from_form`:

```python
rir = _validate_number(raw.rir, "RIR", allow_zero=True, min_value=RIR_MIN)
```

**Step 4:** Ejecutar `uv run pytest tests/test_training_service.py -v` + gates de calidad.

**Step 5: Commit** `feat: allow negative RIR (forced reps) and decimal reps`

---

### Task 4: `descanso_seg` en modelo y servicios

**Files:**
- Modify: `src/models.py` (`TrainingSetInput`, `TrainingSet`)
- Modify: `src/training_service.py` (`sets_from_form`, insert SQL `:142-169`)
- Modify: `src/database.py` (`get_sets_by_fecha`/`get_session_sets`/`snapshot` selects, insert)
- Modify: `src/template_service.py` (`apply_template_rows` devuelve `descanso_seg=None`)
- Test: `tests/test_training_service.py`, `tests/test_database.py`

**Step 1: Tests que fallan**

```python
def test_sets_from_form_parses_descanso():
    sets = sets_from_form(["Press Banca"], ["80"], ["5"], ["0"], descansos=["90"])
    assert sets[0].descanso_seg == 90.0
```

```python
def test_save_session_persists_descanso(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    save_session(db, "2026-08-12", [TrainingSetInput(ejercicio="Press Banca", kg="80", reps="5", rir="0", descanso_seg="90")])
    rows = get_sets_by_fecha(db, "2026-08-12")
    assert rows[0]["descanso_seg"] == 90.0
```

**Step 2:** Verificar que fallan (columna no existe / modelo no lo conoce).

**Step 3: Implementar**
- `TrainingSetInput.descanso_seg: float | str | None = None`; `TrainingSet.descanso_seg: float | None = None`.
- `sets_from_form(..., descansos: list[str] | None = None)` → `_validate_number` con `allow_zero=True` o `None` si vacío.
- SQL de insert/select de `training_sets` en `training_service.py` y `database.py`: incluir `descanso_seg` (parametrizado, `?`). `mutation_service.py` snapshot/restore: incluir la columna.
- `template_service.apply_template_rows`: `descanso_seg=""` en filas nuevas.

**Step 4:** Tests + gates. **Step 5: Commit** `feat: persist descanso_seg per set`

---

### Task 5: Señal de fallo derivada en `metrics_engine`

**Files:**
- Modify: `src/metrics_engine.py`
- Test: `tests/test_metrics_engine.py`

**Step 1: Test que falla**

```python
def test_is_failure_set():
    assert is_failure_set(5.0, 0.0)        # fallo limpio
    assert is_failure_set(4.5, None)       # rep parcial
    assert is_failure_set(5.0, -1.0)       # forzada
    assert not is_failure_set(5.0, 2.0)    # con reserva
    assert not is_failure_set(5.0, None)   # sin datos
```

**Step 2:** Falla (no existe). **Step 3: Implementar**

```python
def is_failure_set(reps: float, rir: float | None) -> bool:
    """True si la serie llegó al fallo (RIR <= 0) o tuvo rep parcial (reps decimal)."""
    return (rir is not None and rir <= 0) or (reps % 1 != 0)
```

Y extender la agregación diaria de `calculate_pfr_timeline` (líneas 122-134) con `sets_fallo=("set_orden", lambda s: int((is_failure_set(r["reps"], r["rir"]) for r in s).__next__()))` — en su lugar, computar la columna `es_fallo` antes del groupby y usar `sets_fallo=("es_fallo", "sum")`.

**Step 4:** Tests + gates. **Step 5: Commit** `feat: derive failure-set signal in metrics engine`

---

## Fase 1 — Agregación diaria de capas

### Task 6: `src/analysis_data.py` — series diarias de capas

**Files:**
- Create: `src/analysis_data.py`
- Test: `tests/test_analysis_data.py` (con fixture SQLite + inserts directos en `health_records`)

Módulo nuevo, tipado estricto, solo lecturas `read_connection`, SQL parametrizado y JSON1.

**Step 1: Tests que fallan** — para cada capa, insertar filas en BD temporal y asertar la agregación diaria:

| capa | SQL clave (record_type / tabla) |
|---|---|
| `sleep_horas` | `SLEEP_SESSION`: `SUM(end_epoch_ms - start_epoch_ms)/3600000.0` por `date(end/1000,'unixepoch','localtime')` |
| `fc_reposo` | `RESTING_HEART_RATE`: `AVG(json_extract(value_json,'$.bpm'))` |
| `fc_media` | `HEART_RATE_5MIN`: `AVG(json_extract(s.value,'$.bpm'))` vía `json_each(value_json,'$.samples') s` |
| `hrv` | `HEART_RATE_VARIABILITY_RMSSD`: `AVG(json_extract(value_json,'$.rmssd_ms'))` |
| `pasos` | `STEPS`: `SUM(json_extract(value_json,'$.count'))` |
| `cardio_min` | `EXERCISE_SESSION`: `SUM(end_epoch_ms - start_epoch_ms)/60000.0` |
| `peso` | `WEIGHT`: `AVG(json_extract(value_json,'$.kg'))` |
| `kcal` | `diario_alimentacion`: `SUM(kcal)` por `fecha` |
| `volumen` | `training_sets`: `SUM(kg*reps)` por `fecha` |

Todas excluyen `deleted_at IS NOT NULL` (bajas lógicas) y devuelven `pd.DataFrame` con columnas `fecha_dt` (datetime64) y el valor.

Firma única por capa (DRY):

```python
def _daily_agg(db_path: str, sql: str) -> pd.DataFrame: ...

def daily_sleep_hours(db_path: str) -> pd.DataFrame: ...
def daily_resting_hr(db_path: str) -> pd.DataFrame: ...
def daily_avg_hr(db_path: str) -> pd.DataFrame: ...
def daily_hrv(db_path: str) -> pd.DataFrame: ...
def daily_steps(db_path: str) -> pd.DataFrame: ...
def daily_cardio_minutes(db_path: str) -> pd.DataFrame: ...
def daily_weight(db_path: str) -> pd.DataFrame: ...
def daily_kcal(db_path: str) -> pd.DataFrame: ...
def daily_volume(db_path: str) -> pd.DataFrame: ...
```

**Step 2:** Falla (módulo no existe). **Step 3:** Implementar con `read_connection` y `pd.read_sql_query` (patrón de `src/charts.py`). **Step 4:** Tests + gates. **Step 5: Commit** `feat: daily analysis layers from health_records and domain tables`

---

### Task 7: Nivel "Grupo" (categoría) en `metrics_engine`

**Files:**
- Modify: `src/metrics_engine.py` (`calculate_pfr_timeline`)
- Test: `tests/test_metrics_engine.py`

**Step 1: Test que falla** — `calculate_pfr_timeline(db, "category", "Empuje")` devuelve solo sets de ejercicios con `categoria='Empuje'`.

**Step 2:** Falla (filter_type desconocido). **Step 3:** Añadir `e.categoria` al JOIN (línea 76-79) y rama:

```python
elif filter_type == "category" and filter_value:
    df_filtered = df[df["categoria"].str.lower() == filter_value.lower()].copy()
```

**Step 4:** Tests + gates. **Step 5: Commit** `feat: category-level PFR filter`

---

## Fase 2 — Vista y gráfica

### Task 8: `charts.build_analysis_chart` — paneles apilados

**Files:**
- Modify: `src/charts.py`
- Test: `tests/test_charts.py`

**Step 1: Test que falla**

```python
def test_build_analysis_chart_returns_subplots_per_layer(tmp_path):
    fig = build_analysis_chart(str(tmp_path / "x.db"), "systemic", None, ["pfr", "volumen"])
    assert fig is not None
    assert len(fig.data) >= 2
```

**Step 2:** Falla (no existe). **Step 3: Implementar**

```python
LayerTrace = tuple[str, str]  # (layer, nombre visible)

def build_analysis_chart(
    db_path: str,
    nivel: str,
    focus: str | None,
    layers: list[str],
    rango_semanas: int | None = 8,
) -> go.Figure:
    """Paneles apilados con eje X de fechas compartido; un subplot por capa activa."""
    series = load_layer_series(db_path, nivel, focus, layers)  # dict[str, DataFrame(fecha_dt, valor)]
    rows = len(layers)
    if rows == 0:
        return go.Figure()
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        subplot_titles=[TITLES[l] for l in layers],
    )
    for i, layer in enumerate(layers, start=1):
        df = series[layer]
        if df.empty:
            continue
        color = LAYER_COLORS[layer]
        if layer == "volumen":
            fig.add_trace(go.Bar(x=df["fecha_dt"], y=df["valor"], name=TITLES[layer],
                                 marker_color=color, hovertemplate="%{y:.0f} kg<extra></extra>"), row=i, col=1)
        else:
            fig.add_trace(go.Scatter(x=df["fecha_dt"], y=df["valor"], mode="lines+markers",
                                     name=TITLES[layer], line=dict(color=color, width=2),
                                     marker=dict(color=color, size=5), hovertemplate="%{y:.1f}<extra></extra>"), row=i, col=1)
    fig.update_layout(height=120 + 150 * rows, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#a3a3a3"), hovermode="x unified",
                      hoverlabel=dict(bgcolor="#1a1a1a", font=dict(color="white"), bordercolor="#333"),
                      margin=dict(l=50, r=16, t=60, b=30), showlegend=False)
    fig.update_xaxes(showgrid=False, tickfont=dict(color="#a3a3a3", size=9))
    fig.update_yaxes(showgrid=False, zerolinecolor="#333", tickfont=dict(color="#a3a3a3", size=9), title=None)
    return fig
```

Constantes: `TITLES`, `LAYER_COLORS` (paleta del proyecto: `#e56d88` borgoña, `#a3a3a3`, `#7dd3fc`, etc.), y `load_layer_series(db_path, nivel, focus, layers)` que orquesta: PFR (timeline existente según nivel), `analysis_data` para el resto, y mergea a un rango de fechas continuo (patrón de `calculate_pfr_timeline` 136-142).

**Step 4:** Tests + gates. **Step 5: Commit** `feat: stacked shared-x analysis chart`

---

### Task 9: View models + KPIs en `dashboard_service`

**Files:**
- Modify: `src/view_models.py`
- Modify: `src/dashboard_service.py`
- Test: `tests/test_app.py` / `tests/test_integration.py`

**Step 1: Dataclasses en `view_models.py`**

```python
@dataclass
class AnalysisKpis:
    pfr_actual: float | None = None
    pfr_variacion: float | None = None      # % vs baseline
    volumen_semana: float | None = None
    sets_fallo_semana: int = 0
    peso_actual: float | None = None
    sueno_anoche: float | None = None
```

**Step 2: `build_analysis_viewmodel(db_path, nivel, focus, layers, rango)` en `dashboard_service.py`** — devuelve `AnalysisViewModel` (KPI + datos de gráfica serializados vía `_json_for_inline(fig.to_json())`, patrón existente línea 142-156). KPI `sets_fallo_semana`: suma de `sets_fallo` de la última semana desde `calculate_pfr_timeline`; `sueno_anoche`: capa sleep del día anterior.

**Step 3:** Tests de integración (BD temporal con datos mínimos → KPI no-None donde aplique). **Step 4:** Gates. **Step 5: Commit** `feat: analysis view model with KPIs`

---

## Fase 3 — Rutas y shell

### Task 10: Shell de análisis — `index.html` + píldoras

**Files:**
- Rewrite: `templates/index.html`
- Modify: `templates/base.html` (sin cambios estructurales; verificar)
- Create: `static/css/pills.css` (registrarlo en `static/css/app.css`)
- Create: `static/js/segmented-pill.js`, `static/js/layer-toggles.js` (registrar en `app.js`)
- Modify: `templates/partials/app_config.html` + contexto de `read_index` en `app.py:348-387`
- Delete (de index): secciones del sidebar

**Step 1: Estructura del nuevo `index.html`** (resumen, el código completo va en implementación):

```
header: título + píldora nivel [Global|Grupo|Músculo|Ejercicio] (data-action="set-level")
        + contenedor filtros contextuales #analysis-filters (chips grupo/músculo, buscador ejercicio)
        + botón "+ Registrar hoy" (data-action="open-register-modal") + Exportar CSV
#kpi-row: 6 KPIs compactos (PFR, variación, volumen semana, sets fallo, peso, sueño anoche)
#analysis-chart-wrap: contenedor de la gráfica (JSON inerte + div plot)
#day-detail-section: panel "¿Qué pasó" (se llena vía GET /analisis/dia)
#register-modal: overlay full-screen (Task 12)
```

**Step 2: `static/css/pills.css`** — patrón AA adaptado al tema oscuro:

```css
.pills-track { @apply bg-neutral-900 rounded-full flex items-center relative; }
.pills-slider { position: absolute; background: #9b1b30; border-radius: 9999px;
                transition: transform 280ms ease-out, width 280ms ease-out; }
.pill { z-index: 1; padding: .375rem .875rem; font-weight: 700; font-size: .75rem;
        letter-spacing: .15em; text-transform: uppercase; color: #a3a3a3; }
.pill[aria-pressed="true"] { color: #fff; }
```

**Step 3: `segmented-pill.js`** — patrón del proyecto: sin handlers inline, `data-action` + listener delegado en `document`:

```javascript
document.addEventListener("click", (e) => {
  const pill = e.target.closest("[data-action='set-level']");
  if (!pill) return;
  const track = pill.closest(".pills-track");
  const next = pill.closest(".pill");
  track.querySelectorAll(".pill").forEach(p => p.setAttribute("aria-pressed", "false"));
  next.setAttribute("aria-pressed", "true");
  positionSlider(track); // transform/width al pill activo
  htmx.trigger("#analysis-chart-wrap", "levelChanged", { nivel: next.dataset.nivel });
});
```

**Step 4:** `layer-toggles.js` (chips capas, `localStorage gym.layers.v1`, re-render vía `hx-get /analisis/chart`). `app-config` ampliado: `levels`, `layers` (ids + títulos), `categoria_map` (existente), `csrf_token`.

**Step 5: `read_index`** — contexto mínimo para la vista: KPIs, gráfica inicial (layers por defecto: PFR+Volumen+Peso), `navigator_html` NO (la fecha vive en el modal), `register` NO en sidebar.

**Step 6:** Verificación visual `uv run uvicorn app:app --reload` + e2e existentes adaptados (Task 17). **Step 7: Commit** `feat: analysis shell with segmented pills and layer toggles`

---

### Task 11: Rutas `/analisis/chart` y `/analisis/dia`

**Files:**
- Modify: `app.py`
- Create: `templates/day_detail.html`, `templates/partials/oob_analysis_chart.html`
- Modify: `src/dashboard_service.py`

**Step 1: `GET /analisis/chart`**

```python
@app.get("/analisis/chart", response_class=HTMLResponse)
def analisis_chart(
    request: Request,
    nivel: str = Query(default="systemic"),
    focus: str = Query(default=""),
    rango: int = Query(default=8),
):
    """Actualiza gráfica + KPIs según nivel/foco/capas activas (OOB)."""
    vm = build_analysis_viewmodel(DB_PATH, nivel, focus or None, _active_layers(request), rango)
    return HTMLResponse(
        content=chart_oob_wrapper(vm.chart_json)
        + fragment_oob(templates, request, "kpi-row", _kpi_row_html(vm), swap="innerHTML")
    )
```

- `_active_layers(request)`: leer capas del body del form (`layers` multivalor) — las envía el JS.
- `_kpi_row_html(vm)`: partial nuevo `kpi_row.html` (6 celdas con label + valor + estado).

**Step 2: `GET /analisis/dia`**

```python
@app.get("/analisis/dia", response_class=HTMLResponse)
def analisis_dia(request: Request, fecha: str = Query(...), nivel: str = Query("systemic"), focus: str = Query("")):
    vm = build_day_detail(DB_PATH, fecha, nivel, focus or None)  # nuevo en dashboard_service
    return templates.TemplateResponse(request=request, name="day_detail.html", context=vm.context())
```

`build_day_detail` agrupa:
1. **Entrenamiento**: sets del día (vía `get_sets_by_fecha` + `fecha_to_db`), filtrados por nivel; PFR y volumen del día (timeline); contador `sets_fallo` (Task 5).
2. **Nutrición**: `diary_totals` + `objetivos_diarios` (ya existen en `nutrition_service`) + peso del día (`parametros_diarios`).
3. **Recuperación**: sueño noche anterior (capa sleep fecha previa), FC media del día, HRV del día, cardio: `EXERCISE_SESSION` del día + `cardio_annotations` (join).

**Step 3:** Tests de integración (rutas responden 200 con fragmento; día sin datos → estado vacío seguro, sin 500). **Step 4:** Gates + verificación visual. **Step 5: Commit** `feat: analysis chart and day-detail routes`

---

### Task 12: Modal de registro

**Files:**
- Modify: `templates/index.html` (overlay `#register-modal`)
- Create: `static/js/register-modal.js` (registrar en `app.js`)
- Modify: `app.py` — `GET /registrar/editor` (navigator + ambos editores para la fecha)

**Step 1: Endpoint**

```python
@app.get("/registrar/editor", response_class=HTMLResponse)
def registrar_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(
        content=_navigator_html(request, fecha)
        + _nutrition_editor_html(request, fecha)
        + _editor_html(request, fecha)
    )
```

**Step 2: Overlay en index.html** — patrón del modal de confirmación existente, pero `fixed inset-0 z-50 overflow-y-auto bg-black/80`:

```
#register-modal (hidden):
  header: píldora tabs [Alimentación|Entrenamiento] + título fecha + botón cerrar
  #register-nav  → date_navigator.html (fragmento del endpoint)
  #register-nutrition  → nutrition editor (oculto según tab)
  #register-session    → session editor (oculto según tab)
```

Los `data-actions` existentes de editor/nutrition/navigator funcionan igual (los targets `#session-editor-wrap`, `#nutrition-editor-wrap` ahora viven solo dentro del modal). Verificar que `htmx-lifecycle.js` reinicializa los módulos tras el swap del modal (los listeners delegados ya lo cubren; el dirty-check de `state.js` usa `#session-editor` — que ahora es el contenedor del modal).

**Step 3:** Botón "+ Registrar hoy" → `open-register-modal` → `htmx.ajax('GET', '/registrar/editor?fecha='+iso, '#register-modal-body')` + mostrar overlay.

**Step 4:** Verificación visual + e2e. **Step 5: Commit** `feat: full-screen register modal reusing editor fragments`

---

## Fase 4 — Editor y alta contextual

### Task 13: Editor — columna descanso + badge fallo

**Files:**
- Modify: `templates/session_editor.html` (columna `Descanso (s)` + badge)
- Modify: `app.py` `entrenamiento_session_save` (campo `descanso` list, `Form(default=[])` — retrocompatible)
- Modify: `static/js/editor.js` (filas nuevas con descanso vacío, valor en submit)
- Modify: `templates/exercise_detail.html` + `day_detail.html` (badge FALLO/FORZADA, descanso visible)

**Step 1:** En `session_editor.html:81-119`: cabecera nueva `<th>Desc` + input `<input name="descanso" type="number" step="5" min="0" placeholder="—">`; el input RIR cambia a `min="-5" step="0.5"` y clase condicional `.rir-fallo` cuando valor ≤ 0 (JS pinta el badge).

**Step 2:** `editor.js`: en submit, leer `descanso` de cada fila; al renderizar valores, `rir <= 0` → badge `FALLO` (o `FORZADA` si `< 0`).

**Step 3:** `entrenamiento_session_save` recibe `descanso: list[str] = Form(default=[])` y lo pasa a `sets_from_form` (Task 4 ya soporta el parámetro).

**Step 4:** Tests de integración (guardar con descanso + RIR −2 → fila persiste) + verificación visual. **Step 5: Commit** `feat: session editor rest column and failure badges`

---

### Task 14: Alta contextual — formularios compactos

**Files:**
- Modify: `templates/exercise_create_form.html` (compacto: nombre + grupo)
- Modify: `templates/alimento_create_form.html` (compacto: nombre + categoría + 4 macros, 5 secundarias en `<details>`)
- Modify: `app.py` `alimento_nuevo` (nutrientes secundarios `Form(None)`)
- Modify: `src/nutrition_service.py` `create_alimento` (None → 0.0)
- Create: `static/js/contextual-create.js`
- Test: `tests/test_nutrition_service.py`

**Step 1: Test de servicio que falla** — `create_alimento` con `AlimentoInput` sin nutrientes secundarios no lanza y persiste 0.0 en los faltantes.

**Step 2:** Falla (campos requeridos). **Step 3:** Implementar defaults en servicio + ruta.

**Step 4: UI** — dentro del modal de registro, un enlace discreto "¿No está? Crear" bajo los inputs de búsqueda de ejercicio/alimento → abre mini-modal (reuso del patrón `confirm_modal`) con el formulario compacto; `POST /ejercicio/nuevo` / `POST /alimento/nuevo` OOB refrescan el datalist (`#app-config`).

**Step 5:** Tests + visual. **Step 6: Commit** `feat: contextual create for exercises and foods`

---

## Fase 5 — Cardio

### Task 15: `POST /cardio/annotation` + UI en panel del día

**Files:**
- Create: `src/cardio_service.py`
- Modify: `app.py` (ruta POST + helpers)
- Modify: `templates/day_detail.html` (bloque cardio con form inline por sesión)
- Test: `tests/test_cardio_service.py`

**Step 1: Tests que fallan**

```python
def test_upsert_annotation(tmp_path):
    # insertar health_records EXERCISE_SESSION + anotación → velocidad persiste
def test_rejects_non_exercise_session(tmp_path):
    # hc_id de SLEEP_SESSION → ValidationError
def test_empty_annotation_deletes(tmp_path):
    # upsert con todos los campos vacíos → borra la anotación
```

**Step 2:** Falla. **Step 3: Implementar** — `src/cardio_service.py`, tipado estricto, `transaction`:

```python
@dataclass
class CardioAnnotationInput:
    hc_id: str
    velocidad_kmh: float | None
    inclinacion_pct: float | None
    notas: str

def upsert_cardio_annotation(db_path: str, data: CardioAnnotationInput) -> None:
    """Valida que hc_id exista y sea EXERCISE_SESSION; upsert; vacío = delete."""
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT record_type FROM health_records WHERE hc_id = ? AND deleted_at IS NULL",
            (data.hc_id,),
        ).fetchone()
        if row is None:
            raise ValidationError("Sesión de cardio no encontrada.")
        if row[0] != "EXERCISE_SESSION":
            raise ValidationError("La anotación solo aplica a sesiones de ejercicio.")
        if data.velocidad_kmh is None and data.inclinacion_pct is None and not data.notas.strip():
            conn.execute("DELETE FROM cardio_annotations WHERE hc_id = ?", (data.hc_id,))
            return
        conn.execute(
            """INSERT INTO cardio_annotations (hc_id, velocidad_kmh, inclinacion_pct, notas, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(hc_id) DO UPDATE SET
                 velocidad_kmh = excluded.velocidad_kmh,
                 inclinacion_pct = excluded.inclinacion_pct,
                 notas = excluded.notas,
                 updated_at = excluded.updated_at""",
            (data.hc_id, data.velocidad_kmh, data.inclinacion_pct, data.notas.strip(),
             _now(), _now()),
        )
```

**Step 4: Ruta** — `POST /cardio/annotation` (form `hc_id`, `velocidad_kmh`, `inclinacion_pct`, `notas`), CSRF igual que el resto de mutaciones, respuesta OOB `#day-detail-wrap` (re-render del panel del día).

**Step 5: UI en `day_detail.html`** — por cada sesión `EXERCISE_SESSION` del día: título + duración + form inline (velocidad, inclinación, notas) precargado con la anotación existente.

**Step 6:** Tests + gates. **Step 7: Commit** `feat: cardio annotations on health-connect sessions`

---

### Task 16: Correlación día siguiente

**Files:**
- Modify: `static/js/chart-interaction.js` (o nuevo `day-correlation.js`)
- Modify: `src/charts.py` (opcional: rect vertical)

**Step 1:** Al hacer clic en un día con cardio o con sets al fallo (dato del día en `day_detail`), añadir en la gráfica una **banda vertical** sobre el día siguiente (traza `add_vrect` client-side sobre el JSON ya renderizado, sin re-fetch).

**Step 2:** Tooltip/hint en el panel del día: "Cardio/Fallo hoy → ver rendimiento de mañana".

**Step 3:** Verificación visual + e2e mínimo (clic → vrect presente en DOM). **Step 4: Commit** `feat: highlight next-day performance after cardio/failure days`

---

## Fase 6 — Limpieza y contrato

### Task 17: Retirar vistas muertas

**Files:**
- Modify: `app.py` — eliminar rutas `/select`, `/grupo/reset`, `/ejercicio`, `/sesiones`; conservar `/exportar/csv`, `/exportar/health-connect.csv`, `/undo`, `/plantillas*`, `/alimentacion*`, `/sync/health-connect`, `/fecha/editor`, `/alimentacion/editor`
- Delete: `templates/session_history.html`, `templates/exercise_list.html`, `templates/exercise_create_form.html` (si se reemplaza por el compacto de Task 14), `static/js/dashboard-filters.js` (si queda sin uso)
- Modify: `src/dashboard_service.py` — retirar `get_recent_sessions`, `build_date_navigator` de la vista principal (la navegación vive en el modal), mantener `chart_pfr_timeline` (lo usa `analysis_data`)
- Modify: `tests/test_app.py`, `tests/test_integration.py`, `tests/e2e/` — actualizar a las nuevas rutas

**Step 1:** Verificar que ningún template/JS referencia las rutas retiradas (`rg "select|grupo/reset|sesiones" templates static/js`).

**Step 2:** Eliminar con tests actualizados en el mismo commit. **Step 3:** Suite completa + gates. **Step 4: Commit** `refactor: remove dead sidebar-era routes and templates`

---

### Task 18: Contrato UI v2 + e2e + cierre

**Files:**
- Modify: `docs/architecture/current-ui-contract.md` (v2: IDs nuevos, data-actions nuevos, tabla de rutas, targets OOB; sección "migración v1→v2")
- Modify: `tests/e2e/test_dashboard_flow.py`, `tests/e2e/test_nutrition_flow.py`
- Create: `tests/e2e/test_analysis_flow.py`

**Step 1:** Documentar contrato v2: `set-level`, `toggle-layer`, `open-register-modal`, `goto-day` (clic en gráfica → `GET /analisis/dia`), `cardio-annotation-save`; IDs `#analysis-chart-wrap`, `#kpi-row`, `#day-detail-section`, `#register-modal`, `.pills-track`, `.pills-slider`.

**Step 2:** e2e nuevos:
1. Píldora de nivel cambia foco y re-renderiza gráfica.
2. Toggle de capa persiste en localStorage y actualiza la gráfica.
3. Modal registrar abre con la fecha de hoy; guardar sesión → aviso.
4. Clic en día → panel "¿Qué pasó" con los 3 bloques.
5. Anotación cardio: guardar velocidad → reaparece precargada.
6. Serie con RIR 0 → badge FALLO en el editor.

**Step 3:** Ejecutar todo:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
```

**Step 4:** `scripts/verify_editor.py` — actualizar si referencia IDs viejos. **Step 5: Commit** `docs: UI contract v2 for analysis dashboard` + commits de e2e por archivo si aplica.

---

## Orden de ejecución y checkpoints

| Hito | Tasks | Criterio de validación |
|---|---|---|
| Datos | 1-5 | `uv run pytest` verde; migraciones aplican sobre copia de `data/lifestyle.db` |
| Capas | 6-7 | Test de agregación con BD temporal |
| Gráfica | 8-9 | `build_analysis_chart` renderiza paneles; KPIs correctos |
| Shell | 10-11 | Home con píldoras + gráfica + panel día (validación visual) |
| Registro | 12-14 | Modal funcional de punta a punta |
| Cardio | 15-16 | Anotación persiste; correlación visible |
| Cierre | 17-18 | Sin rutas muertas; contrato v2; suite + e2e verdes |

## Riesgos

- `current-ui-contract.md` congelado (93 tests): la migración v1→v2 se hace en este mismo trabajo; cada tarea mantiene la suite verde.
- Volumen de `health_records` (FC 5-min): capas usan agregaciones SQL con índices existentes `(record_type, start_epoch_ms)` — no cargar filas crudas a pandas.
- El modal reutiliza fragments: el dirty-check de `state.js` y los targets OOB deben apuntar a los nuevos contenedores del modal (validado en Task 12).
