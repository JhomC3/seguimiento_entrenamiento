# Panel de Alimentación Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Añadir un panel independiente `/alimentacion` para consultar y editar el diario nutricional, importando las hojas públicas `diario` y `alimentos` de Google Sheets sin alterar el panel de entrenamiento.

**Architecture:** Se conservará la arquitectura actual: migración SQLite versionada, parser separado por responsabilidad dentro de `src/parser.py`, servicios de dominio, mutaciones con backup/undo, handlers FastAPI delgados y fragmentos Jinja intercambiados por htmx. El diario almacenará una instantánea de los nutrientes calculados por entrada; el catálogo por 100 g será la fuente de cálculo para nuevas modificaciones, pero las filas importadas conservarán exactamente los valores entregados por la hoja.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, SQLite, pandas, requests, HTML/CSS, módulos ES, pytest/Playwright, ruff, mypy y `uv`.

---

## Evaluación final y decisiones cerradas

### Fuente de datos

- Spreadsheet: `1-qKcqrZRrINdT4Sdw_ItYvn2DtchNvj0Ehb-Nzafxrg`.
- Hoja `diario`: gid `368323682`.
- Hoja `alimentos`: gid `1540384299`.
- La exportación CSV es de solo valores; no expone el texto de las fórmulas de Google Sheets. El contrato de cálculo del panel se basa en el comportamiento observado y se cubre con tests.

### Contrato real del diario

- La fila 1 del CSV (índice 1) contiene los encabezados de los bloques diarios.
- Cada fecha inicia un bloque; el bloque termina justo antes de la siguiente fecha.
- La fecha y el alimento ocupan la misma columna del bloque en sus respectivas filas: el encabezado tiene la fecha y las filas de datos tienen el alimento.
- La cantidad está en la columna siguiente y se expresa como `N g`.
- Las filas 0, 2, 3 y 4 son porcentajes, objetivos y totales; no se importan como alimentos.
- Las filas desde la 5 se inspeccionan de forma defensiva: solo se acepta una fila con alimento no vacío y cantidad positiva en gramos.
- Hay 283 bloques y dos bloques con la misma fecha (`8/8/2026`). Se conservan ambos y sus entradas se concatenan en orden.
- El orden de nutrientes no es uniforme: 16 bloques usan `Carbohidratos, Fibra, Proteína, Grasa` y 267 usan `Carbohidratos, Proteína, Grasa, Fibra`. El parser debe mapear por la etiqueta de cada bloque, nunca por posición fija.

### Contrato de cálculo

- El catálogo `alimentos` contiene valores por 100 g.
- Cada nutriente se calcula independientemente como:

  `ROUND_HALF_UP(valor_catalogo_por_100g * cantidad_g / 100)`

- Se aplica el redondeo a cada nutriente antes de sumar el total diario. No se calcula kcal desde macros: los datos verifican que `4*carbohidratos + 4*proteína + 9*grasa` no reproduce las kcal de la hoja.
- Python no usará `round()` porque su empate usa bankers rounding. Se usará `Decimal` con `ROUND_HALF_UP`, equivalente al comportamiento `ROUND` esperado para cantidades no negativas.
- Al guardar desde el panel, el servidor buscará el alimento en el catálogo y recalculará autoritariamente los nueve nutrientes. El formulario no enviará nutrientes editables ni permitirá alimentos fuera del catálogo; para un alimento nuevo primero se usará el formulario de alta del catálogo.
- La importación conservará los nutrientes que vienen en `diario`, sin recalcularlos, para no alterar los valores históricos de la hoja.
- Los totales diarios se calculan sumando las columnas almacenadas. No se importan las filas de resumen del CSV.

### Decisiones de alcance

**Incluido:**

- Página separada `/alimentacion` con enlace desde entrenamiento.
- Navegación por fecha con `<input type="date">` y anterior/siguiente.
- Editor de alimentos y gramos.
- Previsualización de kcal, macros y micros calculados.
- Alta manual de alimentos del catálogo.
- Guardar, eliminar y deshacer por fecha.
- Importación repetible desde las dos hojas.
- Exportación CSV del diario.
- Un flujo e2e mínimo de abrir, editar, guardar y recargar.

**Fuera de alcance de la primera versión:**

- Lista de historial de fechas recientes.
- Gráficas nutricionales.
- Objetivos, porcentajes y barras de progreso del spreadsheet.
- Planificadores o plantillas de comidas.
- Autenticación de usuarios.
- Unidades distintas de gramos.
- Alimentos libres no presentes en el catálogo.

### Decisión de esquema

No se añadirá una FK desde el diario hacia `alimentos`. El diario guardará el nombre y los nueve nutrientes de cada entrada como snapshot. Esto permite conservar el histórico si el catálogo cambia y refleja la forma en que el entrenamiento guarda los valores de una serie. La validación de nuevas ediciones sí exigirá que el nombre exista en el catálogo.

Cada entrada tendrá `orden` explícito. No se usará el `id` autoincremental para representar la posición visual del alimento.

## Criterios de aceptación

- La nueva rama se crea desde `main` y no incluye cambios ajenos.
- `parse_diario` importa correctamente ambos órdenes de columnas y nunca intercambia fibra, proteína o grasa.
- `parse_diario` descarta filas de resumen y placeholders sin cantidad.
- La importación crea las tablas `alimentos` y `diario_alimentacion`, conserva filas manuales y reemplaza solo filas con `origen='google'`.
- Una entrada de 120 g de Avena basada en el catálogo produce, entre otros valores, 467 kcal, 82 g de carbohidratos, 12 g de fibra, 20 g de proteína, 8 g de grasa, 5 mg de hierro y 65 mg de calcio.
- Guardar una fecha reemplaza deliberadamente todas las filas actuales de esa fecha por el nuevo snapshot manual calculado y mantiene el orden enviado; la importación, en cambio, reemplaza únicamente filas con `origen='google'`.
- El undo restaura filas, orden, nutrientes y origen de la fecha afectada.
- Ninguna acción de alimentación deshace accidentalmente una acción de entrenamiento.
- Las rutas de alimentación usan CSRF, SQL parametrizado y targets OOB allow-listed.
- No se agrega historial, gráfica ni cálculo Atwater.
- Pasan `uv run pytest`, `uv run ruff format --check .`, `uv run ruff check .` y `uv run mypy app.py src tests`.

## Guardrails de implementación

1. Trabajar en `feature/nutrition-dashboard`, creada desde `main`.
2. No ejecutar `git reset`, `git checkout --`, `git restore` ni borrar cambios ajenos.
3. TDD por tarea: test estrecho primero, implementación mínima después.
4. Ejecutar siempre los comandos con `uv run`.
5. Los temporales de pruebas viven en `.tmp/` dentro del proyecto y se eliminan al terminar.
6. No guardar CSV descargados, bases SQLite de verificación ni backups en git.
7. SQL parametrizado exclusivamente con `?`.
8. No usar handlers inline; las interacciones nuevas usan `data-action`, delegación y módulos ES.
9. Mantener intactos los targets y nombres de formulario del entrenamiento.
10. Un commit lógico por tarea; nunca mezclar la base `data/gym.db` con commits de código.

# Phase 0 — Rama y baseline

### Task 0.1: Crear la rama desde `main`

**Files:**
- Modify: ninguno.
- Test: ninguno.

**Step 1: Verificar el árbol.**

Run:

```bash
git status --short
git branch --show-current
```

Expected: árbol limpio o, si no lo está, detenerse y conservar los cambios ajenos antes de cambiar de rama. No hacer stash, reset ni restore sin autorización.

**Step 2: Crear la rama solicitada.**

Run:

```bash
git switch main
git switch -c feature/nutrition-dashboard
```

Expected: rama activa `feature/nutrition-dashboard`, basada en `main`.

**Step 3: Ejecutar baseline.**

Run:

```bash
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
```

Expected: todas las comprobaciones pasan antes de introducir cambios.

**Step 4: Commit.**

No se crea commit para la rama vacía. El primer commit será el de la configuración y parser.

# Phase 1 — Configuración, descarga y parser

### Task 1.1: Añadir configuración de las dos hojas

**Files:**
- Modify: `config.py`.
- Test: `tests/test_fetcher.py`.

**Step 1: Escribir tests que fallen.**

Cubrir:

- `NUTRITION_SHEET_ID` contiene `1-qKcqrZRrINdT4Sdw_ItYvn2DtchNvj0Ehb-Nzafxrg`.
- `NUTRITION_GIDS` contiene exactamente `diario=368323682` y `alimentos=1540384299`.
- `get_csv_url(gid, sheet_id=...)` construye la URL `export?format=csv&gid=...` con el spreadsheet solicitado.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_fetcher.py -k nutrition -v
```

Expected: FAIL porque las constantes y el parámetro de spreadsheet todavía no existen.

**Step 3: Implementar lo mínimo.**

- Mantener `SHEET_ID`, `GIDS` y las llamadas actuales de entrenamiento funcionando sin cambios de comportamiento.
- Generalizar `get_csv_url` con `sheet_id: str = SHEET_ID` para conservar compatibilidad de las llamadas existentes.
- Añadir `NUTRITION_SHEET_ID` y `NUTRITION_GIDS`.

**Step 4: Adaptar el fetcher.**

Modificar `fetch_sheet_csv` para aceptar un mapa y spreadsheet opcionales, por ejemplo:

```python
def fetch_sheet_csv(
    sheet_name: str,
    *,
    gids: Mapping[str, str] = GIDS,
    sheet_id: str = SHEET_ID,
) -> str:
```

El comportamiento de entrenamiento debe seguir siendo `fetch_sheet_csv("ejercicios")`. Alimentación usará explícitamente `NUTRITION_GIDS` y `NUTRITION_SHEET_ID`.

**Step 5: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_fetcher.py -v
```

Expected: PASS, incluyendo los tests existentes del fetcher.

**Step 6: Commit.**

```bash
git add config.py src/fetcher.py tests/test_fetcher.py
git commit -m "feat: configure nutrition spreadsheet sources"
```

### Task 1.2: Parsear el catálogo `alimentos`

**Files:**
- Modify: `src/parser.py`.
- Test: `tests/test_parser.py`.

**Step 1: Escribir el test que falla.**

Usar un CSV pequeño con encabezado real y decimales entre comillas:

```csv
Alimento,Categoría,cantidad,Calorías (kcal),Carbohidratos (g),Fibra (g),Proteína (g),Grasa (g),Hierro (mg),Calcio (mg),Vitamina C (mg),Vitamina A
Avena,Cereal,100,389,68,"10,0",17,"6,9","4,2",54,0,0
```

Verificar que `parse_alimentos`:

- devuelve una fila con nombre y categoría recortados;
- convierte `"10,0"`, `"6,9"` y `"4,2"` a `float`;
- conserva los nueve nutrientes por 100 g;
- no incluye la columna de cantidad como nutriente;
- rechaza o reporta claramente una fila cuyo `cantidad` no sea 100 g.

**Step 2: Verificar que falla.**

Run:

```bash
uv run pytest tests/test_parser.py -k alimentos -v
```

Expected: FAIL porque `parse_alimentos` todavía no existe.

**Step 3: Implementar `parse_alimentos`.**

Usar nombres internos estables:

```text
nombre, categoria, kcal, carbohidratos, fibra, proteina,
grasa, hierro, calcio, vitamina_c, vitamina_a
```

Reglas:

- encabezados recortados;
- categoría conservada como texto recortado, sin title-case destructivo;
- números parseados con el helper decimal existente;
- cantidad de base validada como 100;
- filas completamente vacías descartadas;
- nutrientes faltantes generan error de parseo, no ceros silenciosos.

**Step 4: Verificar que pasa.**

Run:

```bash
uv run pytest tests/test_parser.py -k alimentos -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/parser.py tests/test_parser.py
git commit -m "feat: parse nutrition food catalog"
```

### Task 1.3: Parsear `diario` por etiquetas de bloque

**Files:**
- Modify: `src/parser.py`.
- Test: `tests/test_parser.py`.

**Step 1: Escribir el fixture y tests que fallan.**

Crear un CSV mínimo con:

- una columna inicial vacía;
- dos bloques, uno con el orden `Fibra, Proteína, Grasa`;
- otro con `Proteína, Grasa, Fibra`;
- una fila de porcentajes, una de objetivo y una de totales;
- dos filas de alimentos;
- una cantidad vacía `" g"` que debe descartarse;
- dos bloques con la misma fecha para comprobar que `orden` continúa.

Verificar que `parse_diario` devuelve:

```text
fecha, orden, alimento, cantidad_g, kcal, carbohidratos, fibra,
proteina, grasa, hierro, calcio, vitamina_c, vitamina_a
```

y que los valores de fibra, proteína y grasa son correctos en ambos órdenes.

**Step 2: Verificar que falla.**

Run:

```bash
uv run pytest tests/test_parser.py -k diario -v
```

Expected: FAIL porque no existe el parser nutricional.

**Step 3: Implementar el algoritmo.**

1. Leer CSV sin asumir que el primer registro es el encabezado.
2. Encontrar la fila que contiene fechas con regex `d/m/yyyy` y etiquetas `Cantidad`/`Calorías`.
3. Encontrar todas las posiciones de fecha de esa fila.
4. Para cada bloque, construir un mapa `nombre_normalizado -> índice` desde sus etiquetas.
5. Exigir las etiquetas de cantidad y los nueve nutrientes; si faltan, fallar con fecha y posición del bloque.
6. Leer el alimento en la posición de inicio del bloque, la cantidad en la etiqueta `Cantidad` y cada nutriente en la posición de su etiqueta.
7. Convertir la fecha a ISO con el helper existente.
8. Aceptar solo cantidades positivas con unidad `g`; saltar placeholders y filas de resumen.
9. Asignar `orden` por fecha empezando en 1 y avanzando en el orden de recorrido de bloques y filas.
10. No recalcular nutrientes durante la importación.

Las etiquetas deben normalizarse solo para comparar (`strip`, eliminar el texto entre paréntesis y normalizar acentos), pero los valores se deben conservar sin alterar.

**Step 4: Verificar que pasa y comprobar el caso real.**

Run:

```bash
uv run pytest tests/test_parser.py -k diario -v
```

Expected: PASS; el test debe demostrar explícitamente que no hay intercambio de fibra/proteína/grasa.

**Step 5: Commit.**

```bash
git add src/parser.py tests/test_parser.py
git commit -m "feat: parse daily nutrition blocks by header labels"
```

# Phase 2 — Esquema y persistencia

### Task 2.1: Crear la migración `v007_nutrition`

**Files:**
- Create: `src/migrations/v007_nutrition.py`.
- Modify: `src/migrations/runner.py`.
- Test: `tests/test_database.py`.

**Step 1: Escribir el test que falla.**

En una base temporal, ejecutar `init_db` y verificar:

- versión actual 7;
- tablas `alimentos` y `diario_alimentacion`;
- índice compuesto por fecha y orden;
- columnas `origen` con default `google`;
- ningún cambio en `ejercicios`, `training_sets`, `plantillas` o `plantilla_sets`.

**Step 2: Verificar que falla.**

Run:

```bash
uv run pytest tests/test_database.py -k nutrition -v
```

Expected: FAIL porque la migración no existe.

**Step 3: Implementar el esquema mínimo.**

`alimentos`:

```sql
CREATE TABLE IF NOT EXISTS alimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    categoria TEXT NOT NULL DEFAULT '',
    kcal REAL NOT NULL,
    carbohidratos REAL NOT NULL,
    fibra REAL NOT NULL,
    proteina REAL NOT NULL,
    grasa REAL NOT NULL,
    hierro REAL NOT NULL,
    calcio REAL NOT NULL,
    vitamina_c REAL NOT NULL,
    vitamina_a REAL NOT NULL,
    origen TEXT NOT NULL DEFAULT 'google'
);
```

`diario_alimentacion`:

```sql
CREATE TABLE IF NOT EXISTS diario_alimentacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    orden INTEGER NOT NULL,
    alimento TEXT NOT NULL,
    cantidad_g REAL NOT NULL,
    kcal REAL NOT NULL,
    carbohidratos REAL NOT NULL,
    fibra REAL NOT NULL,
    proteina REAL NOT NULL,
    grasa REAL NOT NULL,
    hierro REAL NOT NULL,
    calcio REAL NOT NULL,
    vitamina_c REAL NOT NULL,
    vitamina_a REAL NOT NULL,
    origen TEXT NOT NULL DEFAULT 'google'
);
CREATE INDEX IF NOT EXISTS idx_diario_alimentacion_fecha_orden
    ON diario_alimentacion(fecha, orden);
```

No añadir FK a `alimentos`; el nombre y los nutrientes son el snapshot de la entrada.

Registrar `v007_nutrition` al final de `MIGRATIONS` y añadir ambas tablas a `_DOMAIN_TABLES` para que una migración futura cree backup.

**Step 4: Verificar que pasa.**

Run:

```bash
uv run pytest tests/test_database.py -k nutrition -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/migrations/v007_nutrition.py src/migrations/runner.py tests/test_database.py
git commit -m "feat: add nutrition database schema"
```

### Task 2.2: Añadir operaciones SQLite del catálogo y diario

**Files:**
- Modify: `src/database.py`.
- Test: `tests/test_database.py`.

**Step 1: Escribir tests que fallen.**

Cubrir:

- insertar y leer catálogo ordenado por nombre;
- localizar un alimento de forma case-insensitive y devolver su nombre canónico;
- reemplazar las entradas de una fecha respetando `orden`;
- obtener fechas distintas ordenadas ISO;
- borrar solo las entradas de una fecha;
- snapshot y restore conservando `id`, `orden`, nutrientes y `origen`;
- consultas parametrizadas con nombres que contienen comillas.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_database.py -k "alimento or diario or nutrition" -v
```

Expected: FAIL porque no existen las operaciones nuevas.

**Step 3: Implementar las funciones.**

Añadir funciones con firmas tipadas, como mínimo:

```python
get_alimentos_catalog(db_path: str) -> list[dict]
find_alimento(db_path: str, nombre: str) -> dict | None
get_diario_by_fecha(db_path: str, fecha: str) -> list[dict]
get_diario_dates(db_path: str) -> list[str]
replace_diario_by_fecha(db_path: str, fecha: str, rows: list[dict]) -> None
delete_diario_by_fecha(db_path: str, fecha: str) -> int
restore_diario_rows(db_path: str, fecha: str, rows: list[dict]) -> None
```

`replace_diario_by_fecha` debe borrar las filas de la fecha y volver a insertar con `orden` 1..N en una única transacción. `restore_diario_rows` debe poder insertar el snapshot completo necesario para undo.

**Step 4: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_database.py -k "alimento or diario or nutrition" -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat: persist nutrition catalog and diary rows"
```

# Phase 3 — Dominio, cálculo y mutaciones

### Task 3.1: Añadir modelos y cálculo nutricional

**Files:**
- Modify: `src/models.py`.
- Create: `src/nutrition_service.py`.
- Test: `tests/test_models.py`.
- Test: `tests/test_nutrition_service.py`.

**Step 1: Escribir tests que fallen.**

Cubrir:

- `NutritionEntryInput(alimento, cantidad_g)` tipado;
- `AlimentoInput` con nombre, categoría y nueve valores base;
- 120 g de Avena produce 467 kcal, 82 carbohidratos, 12 fibra, 20 proteína, 8 grasa, 5 hierro y 65 calcio;
- cada nutriente se redondea independientemente con half-up;
- un valor exacto `2.5` redondea a 3, no a 2;
- kcal se toma del catálogo y no se deriva de macros;
- cantidad cero, negativa, vacía o no numérica genera `ValidationError`;
- alimento desconocido genera `NotFoundError` o `ValidationError` de dominio;
- filas completamente vacías del formulario se omiten;
- filas parcialmente rellenadas fallan;
- una edición devuelve los nombres canónicos del catálogo.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_nutrition_service.py tests/test_models.py -v
```

Expected: FAIL porque los modelos y servicio no existen.

**Step 3: Implementar el cálculo autoritativo.**

En `src/nutrition_service.py`:

```python
from decimal import Decimal, ROUND_HALF_UP


def _sheet_round(value: float | str) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_nutrients(food: dict, cantidad_g: float) -> dict[str, float]:
    factor = Decimal(str(cantidad_g)) / Decimal("100")
    return {field: _sheet_round(Decimal(str(food[field])) * factor) for field in NUTRIENT_FIELDS}
```

Validar antes que `cantidad_g > 0`. `NUTRIENT_FIELDS` debe contener exactamente `kcal`, `carbohidratos`, `fibra`, `proteina`, `grasa`, `hierro`, `calcio`, `vitamina_c` y `vitamina_a`.

Implementar también:

```python
entries_from_form(
    alimentos: list[str], cantidades: list[str]
) -> list[NutritionEntryInput]
save_diary(db_path: str, fecha_iso: str, entries: list[NutritionEntryInput]) -> None
delete_diary(db_path: str, fecha_iso: str) -> None
create_alimento(db_path: str, alimento: AlimentoInput) -> None
diary_totals(rows: list[dict]) -> dict[str, float]
```

`save_diary` debe buscar cada alimento, calcular los nueve valores y delegar la escritura transaccional a `database.py`. No debe aceptar nutrientes enviados por el cliente como fuente de verdad.

**Step 4: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_nutrition_service.py tests/test_models.py -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/models.py src/nutrition_service.py tests/test_models.py tests/test_nutrition_service.py
git commit -m "feat: calculate nutrition entries from catalog"
```

### Task 3.2: Integrar undo para alimentación

**Files:**
- Modify: `src/mutation_service.py`.
- Modify: `src/database.py` si falta alguna operación de snapshot.
- Test: Create `tests/test_mutation_service.py`.

**Step 1: Escribir tests que fallen.**

Cubrir:

- guardar una fecha crea una entrada de undo `kind="alimentacion"`;
- borrar una fecha crea una entrada de undo;
- undo restaura la fecha y el orden original;
- undo restaura origen y nutrientes importados;
- un undo de alimentación no restaura plantillas ni sesiones;
- un fallo de backup impide escribir y no añade la entrada a la pila;
- la pila conserva el límite de 10 acciones actual.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_mutation_service.py -v
```

Expected: FAIL porque no existe el tipo de mutación nutricional.

**Step 3: Implementar los casos de uso.**

Añadir:

```python
save_diary_with_undo_snapshot(db_path: str, fecha_iso: str, entries) -> None
delete_diary_with_undo_snapshot(db_path: str, fecha_iso: str) -> None
```

Seguir el orden existente: backup, snapshot `before`, escritura, snapshot `after`, push solo después de éxito.

Extender `undo_last_action` con la rama `alimentacion`. El resultado debe incluir `fecha_iso` y `has_data` para que el handler pueda actualizar el editor y el indicador de fecha correctos.

Extender el helper OOB de undo con un atributo `data-kind` solo si es necesario; conservar exactamente el comportamiento actual de entrenamiento por defecto.

**Step 4: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_mutation_service.py tests/test_training_service.py -v
```

Expected: PASS en nutrición y entrenamiento.

**Step 5: Commit.**

```bash
git add src/mutation_service.py src/database.py tests/test_mutation_service.py
git commit -m "feat: add nutrition save delete and undo mutations"
```

# Phase 4 — Importación de Google Sheets

### Task 4.1: Crear el importador idempotente de alimentación

**Files:**
- Create: `scripts/import_nutrition.py`.
- Test: Create `tests/test_import_nutrition.py`.

**Step 1: Escribir tests que fallen.**

Mockear `fetch_sheet_csv` para devolver fixtures locales y usar `GYM_DB_PATH` apuntando a una base temporal. Verificar:

- se importan catálogo y diario;
- una segunda ejecución no duplica filas Google;
- filas manuales de ambas tablas sobreviven;
- un alimento manual con el mismo nombre no es sobreescrito por el catálogo Google;
- un fallo de descarga o parser no borra datos;
- se crea backup antes del reemplazo destructivo;
- el resumen final informa cantidades y origen.

**Step 2: Verificar que falla.**

Run:

```bash
uv run pytest tests/test_import_nutrition.py -v
```

Expected: FAIL porque el script no existe.

**Step 3: Implementar el flujo.**

1. Descargar `alimentos` y `diario` antes de tocar la base.
2. Parsear ambos y abortar si cualquiera queda vacío o inválido.
3. Ejecutar `init_db`.
4. Ejecutar `backup_db` antes de borrar filas.
5. En una transacción:
   - borrar `diario_alimentacion WHERE origen = 'google'`;
   - borrar `alimentos WHERE origen = 'google'`;
   - insertar catálogo con `origen='google'`, usando `INSERT OR IGNORE` para no desplazar alimentos manuales;
   - insertar diario con `origen='google'` y el `orden` generado por el parser.
6. Imprimir conteos por origen.

No reutilizar `scripts/import_google_sheets.py` para no mezclar contratos de entrenamiento y alimentación; ambos scripts compartirán solo helpers de configuración/fetcher/parser.

**Step 4: Verificar que pasa.**

Run:

```bash
uv run pytest tests/test_import_nutrition.py -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add scripts/import_nutrition.py tests/test_import_nutrition.py
git commit -m "feat: import nutrition sheets transactionally"
```

# Phase 5 — View models, dashboard y rutas HTTP

### Task 5.1: Construir el view model y servicio de editor

**Files:**
- Modify: `src/view_models.py`.
- Modify: `src/dashboard_service.py`.
- Test: Create `tests/test_nutrition_dashboard.py`.

**Step 1: Escribir tests que fallen.**

Cubrir:

- construir editor para una fecha ISO con filas y totales;
- construir editor vacío para una fecha sin datos;
- fechas del navegador ordenadas ISO y seleccionada correctamente;
- fechas futuras editables;
- los valores del view model contienen solo datos de presentación, sin conexiones SQLite.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_nutrition_dashboard.py -v
```

Expected: FAIL porque no existe el view model/servicio.

**Step 3: Implementar.**

Añadir `NutritionEditorViewModel` con:

```text
fecha_iso, fecha_display, rows, totals, catalog,
has_data, error, success
```

Añadir un `NutritionDateNavigatorViewModel` pequeño con `selected_iso`, `previous_iso`, `next_iso` y `today_iso`, y funciones en `dashboard_service.py`:

```python
build_nutrition_editor(db_path: str, fecha_iso: str, ...) -> NutritionEditorViewModel
build_nutrition_date_navigator(db_path: str, fecha_iso: str) -> NutritionDateNavigatorViewModel
```

El navegador debe ser solo fecha actual, anterior, siguiente y date input; no reutilizar la semántica de semana/ciclo del entrenamiento.

**Step 4: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_nutrition_dashboard.py -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/view_models.py src/dashboard_service.py tests/test_nutrition_dashboard.py
git commit -m "feat: build nutrition editor view models"
```

### Task 5.2: Añadir targets OOB y handlers FastAPI

**Files:**
- Modify: `src/response_fragments.py`.
- Modify: `app.py`.
- Test: `tests/test_app.py`.

**Step 1: Escribir tests que fallen.**

Cubrir con `TestClient` y una base temporal:

- `GET /alimentacion` devuelve HTML con editor y navegador;
- `GET /alimentacion/editor?fecha=...` devuelve la fecha solicitada;
- `POST /alimentacion/save` guarda una fila y devuelve `hx-swap-oob` para editor/navegador;
- `POST /alimentacion/eliminar` elimina solo la fecha solicitada;
- `POST /alimento/nuevo` crea un alimento manual y devuelve aviso/formulario OOB;
- `GET /alimentacion/exportar/csv` devuelve encabezados y filas ordenadas por fecha/orden;
- POST sin CSRF sigue rechazado;
- errores de dominio devuelven aviso seguro y no traceback HTML;
- `POST /undo` actualiza el editor nutricional cuando la última acción es alimentación.

**Step 2: Verificar que fallan.**

Run:

```bash
uv run pytest tests/test_app.py -k alimentacion -v
```

Expected: FAIL porque las rutas y targets no existen.

**Step 3: Implementar allow-lists.**

En `src/response_fragments.py`:

- añadir `nutrition-editor-wrap` y `nutrition-date-navigator` a `OOB_FRAGMENT_TARGETS`;
- reutilizar `notice-container`, `editor-notice`, `save-outcome` y `undo-result` cuando no haya colisión;
- mantener todos los targets del entrenamiento;
- no interpolar ids proporcionados por el cliente.

**Step 4: Implementar helpers y rutas delgadas.**

En `app.py` añadir:

```python
GET  /alimentacion
GET  /alimentacion/editor?fecha=...
POST /alimentacion/save
POST /alimentacion/eliminar
POST /alimento/nuevo
GET  /alimentacion/exportar/csv
```

Reglas de los handlers:

- parsear request/formulario;
- delegar validación y escritura a `nutrition_service`/`mutation_service`;
- construir HTML mediante helpers Jinja;
- traducir errores con `translate_error`;
- devolver fragmentos OOB server-owned.

`POST /alimentacion/save` recibirá solo `fecha`, `alimento[]` y `cantidad[]`. No confiará en kcal/macros enviados desde navegador.

Actualizar la rama de `/undo` para que `kind="alimentacion"` re-renderice `nutrition-editor-wrap` y `nutrition-date-navigator`, sin tocar `session-editor-wrap`.

**Step 5: Verificar que pasan.**

Run:

```bash
uv run pytest tests/test_app.py -k alimentacion -v
uv run pytest tests/test_app.py -k "entrenamiento or undo" -v
```

Expected: PASS en rutas nuevas y existentes.

**Step 6: Commit.**

```bash
git add src/response_fragments.py app.py tests/test_app.py
git commit -m "feat: add nutrition dashboard routes"
```

# Phase 6 — Plantillas y frontend

### Task 6.1: Crear la página y fragmentos Jinja

**Files:**
- Create: `templates/alimentacion.html`.
- Create: `templates/nutrition_editor.html`.
- Create: `templates/nutrition_date_navigator.html`.
- Create: `templates/alimento_create_form.html`.
- Modify: `templates/index.html`.

**Step 1: Escribir/actualizar tests de render.**

Usar los tests de app para comprobar ids, nombres de campos, texto accesible y targets htmx antes de completar el markup.

**Step 2: Implementar la página mínima.**

`alimentacion.html` debe:

- extender `base.html`;
- mostrar título y enlace de vuelta a `/`;
- mostrar formulario de alta de alimento en una columna lateral pequeña;
- mostrar navegador de fechas;
- mostrar `nutrition-editor-wrap`;
- mostrar `notice-container` y `save-outcome` mediante los partials ya existentes;
- no incluir gráfica ni lista de historial.

`nutrition_editor.html` debe:

- usar `<form id="nutrition-form" hx-post="/alimentacion/save" hx-swap="none">`;
- incluir `fecha` hidden ISO;
- usar `#nutrition-rows` y filas con `name="alimento"` y `name="cantidad"`;
- mostrar kcal, carbohidratos, fibra, proteína, grasa, hierro, calcio, vitamina C y vitamina A como outputs de solo lectura;
- añadir acciones `data-action` para agregar/quitar filas, guardar y eliminar fecha;
- permitir editar cualquier fecha, incluida una futura;
- escapar todos los valores mediante Jinja.

`nutrition_date_navigator.html` debe usar input nativo `type="date"` y controles anterior/siguiente; no crear un calendario custom.

El formulario `alimento_create_form.html` debe pedir nombre, categoría y los nueve valores por 100 g, con `step="0.1"`, validación visible y POST a `/alimento/nuevo`.

En `index.html`, añadir un enlace visible a `/alimentacion` sin alterar el panel ni los ids de entrenamiento.

**Step 3: Verificar render y seguridad.**

Run:

```bash
uv run pytest tests/test_app.py -k alimentacion -v
```

Expected: tests de app PASS; las puertas estáticas se ejecutan en la verificación final.

**Step 4: Commit.**

```bash
git add templates/alimentacion.html templates/nutrition_editor.html templates/nutrition_date_navigator.html templates/alimento_create_form.html templates/index.html
git commit -m "feat: add nutrition dashboard templates"
```

### Task 6.2: Implementar interacción editable sin handlers inline

**Files:**
- Create: `static/js/nutrition-editor.js`.
- Modify: `static/js/app.js`.
- Modify: `static/js/state.js`.
- Modify: `static/js/htmx-lifecycle.js`.
- Test: `tests/e2e/test_nutrition_flow.py`.

**Step 1: Escribir el e2e que falla.**

Crear un test aislado que:

1. abra `/alimentacion` con una base temporal;
2. seleccione o agregue un alimento;
3. cambie cantidad;
4. compruebe la previsualización de kcal;
5. guarde;
6. recargue la fecha;
7. compruebe que la fila y los totales persisten;
8. elimine y compruebe que la fecha queda vacía.

El fixture debe insertar un catálogo pequeño y no depender de Google Sheets ni de la red.

**Step 2: Verificar que falla.**

Run:

```bash
uv run pytest tests/e2e/test_nutrition_flow.py -v
```

Expected: FAIL porque no existe el módulo ni la interacción.

**Step 3: Implementar `nutrition-editor.js`.**

El módulo debe:

- inicializarse de forma idempotente y no hacer nada si no existe `#nutrition-form`;
- usar delegación sobre `document` o el contenedor estable;
- leer el mapa compacto de catálogo desde `#app-config` o un atributo JSON server-owned;
- calcular la previsualización con `Math.floor(value + 0.5)` para valores no negativos, aclarando que el servidor es la fuente autoritativa;
- actualizar outputs al cambiar alimento o cantidad;
- agregar/quitar filas y renumerarlas;
- manejar anterior/siguiente y cambio de fecha con la protección de cambios sin guardar;
- enviar `fecha` al undo global;
- no usar `innerHTML` con valores introducidos por el usuario;
- no añadir handlers inline ni `window.*` bridges.

Los datos del catálogo enviados al cliente son solo para previsualización. El servidor volverá a calcular todo al guardar.

**Step 4: Integrar bootstrap y undo sin romper entrenamiento.**

- Importar y llamar `initNutritionEditor()` desde `static/js/app.js`.
- Hacer que `currentFecha()` en `state.js` use `#session-form` o `#nutrition-form` de forma defensiva.
- Mantener los listeners específicos de entrenamiento condicionados a sus ids.
- Permitir que Ctrl+Z del `htmx-lifecycle.js` envíe la fecha del formulario nutricional.
- Si el ciclo de vida necesita actuar después de un swap de `nutrition-editor-wrap`, hacerlo mediante un branch explícito o un listener propio del módulo; no ejecutar lógica de sortable/RM sobre el panel nutricional.

**Step 5: Verificar que pasa.**

Run:

```bash
uv run pytest tests/e2e/test_nutrition_flow.py -v
uv run pytest tests/e2e/test_dashboard_flow.py -v
```

Expected: PASS en alimentación y en el flujo existente de entrenamiento.

**Step 6: Commit.**

```bash
git add static/js/nutrition-editor.js static/js/app.js static/js/state.js static/js/htmx-lifecycle.js tests/e2e/test_nutrition_flow.py
git commit -m "feat: add editable nutrition frontend"
```

# Phase 7 — Documentación y datos locales

### Task 7.1: Documentar el contrato nuevo

**Files:**
- Modify: `docs/architecture/current-ui-contract.md`.
- Modify: `docs/operations/local-development.md`.
- Modify: `AGENTS.md` solo en las secciones de modelo/rutas si quedan desactualizadas.

**Step 1: Actualizar arquitectura.**

Documentar:

- `/alimentacion` y sus rutas de mutación;
- ids `nutrition-form`, `nutrition-editor-wrap`, `nutrition-date-navigator`;
- targets OOB allow-listed;
- regla `ROUND_HALF_UP(valor_100g * gramos / 100)`;
- ausencia de FK y snapshot de nutrientes;
- ausencia deliberada de historial, gráficas y objetivos en v1.

**Step 2: Actualizar desarrollo local.**

Documentar:

```bash
uv run python scripts/import_nutrition.py
```

Incluyendo `GYM_DB_PATH`, backup previo, que el spreadsheet debe seguir siendo público y que el importador reemplaza solo origen Google.

**Step 3: Verificar documentación.**

Run:

```bash
git diff --check
```

Expected: sin whitespace errors.

**Step 4: Commit.**

```bash
git add docs/architecture/current-ui-contract.md docs/operations/local-development.md AGENTS.md
git commit -m "docs: document nutrition dashboard contract"
```

### Task 7.2: Ejecutar importación real y verificar base

**Files:**
- Modify: `data/gym.db` local ignorada por git.
- Create: `data/backups/` o backup automático existente.
- Test: ninguno adicional; usar smoke checks.

**Step 1: Ejecutar todos los tests y gates antes de tocar la base real.**

Run:

```bash
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
```

Expected: PASS.

**Step 2: Importar las hojas reales.**

Run:

```bash
GYM_DB_PATH=data/gym.db uv run python scripts/import_nutrition.py
```

Expected:

- migración v007 aplicada una sola vez;
- backup previo creado;
- catálogo y diario importados;
- filas Google reemplazables en futuras ejecuciones;
- datos manuales anteriores preservados.

**Step 3: Verificar conteos y muestras con `.venv`.**

Run:

```bash
GYM_DB_PATH=data/gym.db uv run python - <<'PY'
import sqlite3

conn = sqlite3.connect("data/gym.db")
print(conn.execute("SELECT COUNT(*) FROM alimentos").fetchone()[0])
print(conn.execute("SELECT COUNT(*) FROM diario_alimentacion").fetchone()[0])
print(conn.execute("SELECT fecha, alimento, cantidad_g, kcal, fibra, proteina, grasa FROM diario_alimentacion ORDER BY fecha, orden LIMIT 5").fetchall())
conn.close()
PY
```

Expected: catálogo con los alimentos públicos y diario con las entradas importadas; los primeros registros deben mostrar valores no intercambiados.

**Step 4: Arrancar la app para smoke test manual.**

Run:

```bash
GYM_DB_PATH=data/gym.db uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Comprobar manualmente `/` y `/alimentacion` en desktop y viewport móvil, guardar/eliminar/deshacer y verificar que entrenamiento sigue funcionando.

**Step 5: Commit final de código/documentación.**

No incluir `data/gym.db`, `data/backups`, `.tmp`, `.venv` ni CSV descargados. Ejecutar:

```bash
git status --short
git diff --check
```

Expected: solo archivos de código, tests y documentación intencionalmente modificados.

## Verificación final completa

Run:

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
```

Expected: todas las pruebas y puertas pasan. Si falla un e2e por disponibilidad de Chromium, reportar explícitamente esa limitación y ejecutar igualmente unidad, integración y estáticos.
