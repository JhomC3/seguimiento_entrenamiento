# Contrato HTTP del diario de entrenamiento (API v1)

> **Estado:** v1 (2026-09-07). API JSON para la app Android HealthSync: ver y
> editar la sesión del día. Paralela al HTML/htmx del dashboard (que no se
> toca); reutiliza su dominio (`training_service`, `mutation_service`).
> Fuente de verdad para las pruebas cruzadas Python/Kotlin de esta API.

## 1. Reglas generales

- Transporte: misma red que Health Connect (LAN del hogar vía
  `scripts/start_server.sh`; HTTPS en release, HTTP solo en debug LAN).
- Autenticación: header `X-Sync-Token` con el token compartido (`HC_SYNC_TOKEN`
  env o `data/hc_sync_token`). **Es el mismo secreto que
  `POST /sync/health-connect`** (decisión explícita: app personal
  single-owner; si el token filtra, el impacto pasa de "inyectar Health
  Connect" a "reescribir entrenos" — riesgo aceptado y documentado en
  `security-model.md` §2.6). El token viaja cifrado en el dispositivo
  (Android Keystore), nunca en texto plano, nunca en logs.
- Respuestas de error: `400` validación de dominio (`{"detail": ...}` en
  español, seguro), `401` token ausente/incorrecto, `413` cuerpo excesivo,
  `503` endpoint sin credencial configurada, `500` genérico (detalle solo en
  el log del servidor). `400/401/413` son permanentes; red y `5xx` son
  reintentables.
- Versiones: `schema_version: 1` en toda respuesta. La app debe ignorar campos
  desconocidos y rechazar `schema_version` mayor con un mensaje accionable.
  Campos aditivos (p. ej. `meta` en `GET /api/v1/ejercicios`) no suben versión.
- Errores de dominio: `400` validación, `404` inexistente (`NotFoundError`),
  `409` conflicto (`ConflictError`, p. ej. ejercicio duplicado) — los tres
  permanentes; `401/413` como en §1.
- CSRF: `POST`/`DELETE /api/v1/sesion` están exentos del CSRF de formularios
  **por igualdad exacta de ruta** (`CSRF_EXEMPT_PATHS` en `src/security.py`),
  igual que `/sync/health-connect`. Llevan credencial propia.
- Gate LAN (`GYM_LAN_SYNC_ONLY=1`): las 4 rutas de §2 están en la allow-list
  exacta (`ALLOWED_REMOTE_ROUTES` en `src/network_access.py`, método + path);
  el resto remoto sigue 403/429. Rate-limit por peer compartido con el sync
  (`GYM_SYNC_RATE_LIMIT_PER_MINUTE`, default 30/min).

## 2. Endpoints

| Método | Path | Auth | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/sesion?fecha=YYYY-MM-DD` | `X-Sync-Token` | Lee la sesión del día |
| `POST` | `/api/v1/sesion` | `X-Sync-Token` | Guarda el día (reemplazo total) |
| `DELETE` | `/api/v1/sesion?fecha=YYYY-MM-DD` | `X-Sync-Token` | Elimina el día (idempotente) |
| `GET` | `/api/v1/ejercicios` | `X-Sync-Token` | Catálogo para el editor (+ `meta.categorias`) |
| `GET` | `/api/v1/plantillas` | `X-Sync-Token` | Entrenos con sus ejercicios (B1) |
| `POST` | `/api/v1/plantilla/aplicar` | `X-Sync-Token` | Preview sin escribir (B1) |
| `POST` | `/api/v1/plantilla/guardar` | `X-Sync-Token` | Guarda día como entreno, upsert por nombre (B1) |
| `POST` | `/api/v1/ejercicio` | `X-Sync-Token` | Alta de ejercicio, 409 duplicado (B1) |
| `GET` | `/api/v1/undo/peek` | `X-Sync-Token` | Qué se desharía, sin consumir (B1) |
| `POST` | `/api/v1/undo` | `X-Sync-Token` | Deshace última acción (B1) |
| `GET` | `/api/v1/diario?fecha=` | `X-Sync-Token` | Día nutricional + objetivo + parámetros (B2) |
| `POST` | `/api/v1/diario` | `X-Sync-Token` | Guarda día + parámetros, reemplazo idempotente (B2) |
| `DELETE` | `/api/v1/diario?fecha=` | `X-Sync-Token` | Elimina filas del día, conserva parámetros (B2) |
| `GET` | `/api/v1/alimentos` | `X-Sync-Token` | Catálogo por 100 g + etiquetas (B2) |
| `POST` | `/api/v1/alimento` | `X-Sync-Token` | Alta de alimento, 409 duplicado (B2) |
| `GET` | `/api/v1/plantillas-comida` | `X-Sync-Token` | Plantillas de comida (B2) |
| `POST` | `/api/v1/plantilla-comida/aplicar` | `X-Sync-Token` | Preview recalculado, sin escribir (B2) |
| `POST` | `/api/v1/plantilla-comida/guardar` | `X-Sync-Token` | Guarda día como plantilla, upsert (B2) |
| `GET` | `/api/v1/sugerencia?fecha=` | `X-Sync-Token` | Rutina sugerida sin escribir (rueda) |
| `GET` | `/api/v1/ejercicio/ultimo?ejercicio=&fecha=` | `X-Sync-Token` | Últimas series del ejercicio (autofill) |
| `GET` | `/api/v1/cardio?fecha=` | `X-Sync-Token` | Sesiones del día con anotación (B3) |
| `POST` | `/api/v1/cardio/anotacion` | `X-Sync-Token` | Anota sesión; vacío = borrar (B3) |
| `GET` | `/api/v1/fechas?vista=` | `X-Sync-Token` | Fechas con datos por pestaña (B4) |

### `GET /api/v1/sesion?fecha=`

```json
{
  "schema_version": 1,
  "fecha": "2026-09-07",
  "semana": 19,
  "dia": "LUNES",
  "has_data": true,
  "sets": [
    {
      "set_orden": 1,
      "ejercicio": "Press",
      "kg": 80.0,
      "reps": 8.0,
      "rir": 1.0,
      "descanso_seg": null,
      "rm": 103.9
    }
  ]
}
```

- `fecha` solo ISO `YYYY-MM-DD` (la API no acepta el legado `d/m/yy`).
- `semana`/`dia` derivados en servidor (`calculate_cycle_week`/`day_from_date`).
- `kg`/`reps`/`rir`/`descanso_seg`: número o `null` (tal cual en SQLite).
- `rm`: 1RM estimado recalculado en servidor (`rm_ajustado`, redondeo a 1
  decimal) o `null` sin kg/reps. El cliente solo lo muestra.
- Día vacío: `has_data: false`, `sets: []` (200, no 404: el vacío es un
  estado válido del diario).
- `fecha` ausente o inválida → `400 {"detail": ...}`.

### `POST /api/v1/sesion`

```json
{
  "fecha": "2026-09-07",
  "sets": [
    {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
    {"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2, "descanso_seg": 90}
  ]
}
```

- Reemplazo total del día (`DELETE + INSERT` ordenado, `origen='manual'`,
  `set_orden` 1..N asignado en servidor): el cliente nunca envía `set_orden`,
  `semana`, `dia` ni `origen`.
- Validación = la del editor web (`validate_sets`): ≥1 serie, ejercicio del
  catálogo (case-insensitive), `kg > 0`, `reps > 0` numéricos (sin NaN/Inf),
  `rir ≥ -5.0` (negativo = forzadas), `descanso_seg ≥ 0` opcional. Fallo →
  `400 {"detail": ...}` sin escribir nada.
- Límites: 1–100 series (`MAX_FORM_SETS`), cuerpo ≤ 1 MiB (`413` por encima).
- Efectos: backup pre-mutación + journal de undo (`kind "sesion"`, comparte
  la pila de 10 con la web).
- Respuesta 200: como el GET más `"saved_count": N`.
- Idempotencia: re-`POST` del mismo cuerpo deja el mismo estado (el móvil
  puede reintentar sin miedo a duplicar).

### `DELETE /api/v1/sesion?fecha=`

```json
{"schema_version": 1, "fecha": "2026-09-07", "deleted": true}
```

- Idempotente: día ya vacío → igualmente `200 {"deleted": true}`.
- Efectos: backup + journal (`sesion`).

### `GET /api/v1/ejercicios`

```json
{
  "schema_version": 1,
  "count": 2,
  "ejercicios": [
    {"ejercicio": "Press", "grupo_muscular": "Pectoral", "categoria": "EMPUJE"}
  ],
  "meta": {"categorias": [{"name": "EMPUJE", "muscles": ["Pectoral", "Hombro", "Triceps"]}]}
}
```

- Orden `grupo_muscular, ejercicio` (mismo `get_split_catalog` del board web).
- La pertenencia al catálogo se valida siempre en servidor; la lista es solo
  asistencia al editor (autocompletado), no autorización.
- `meta.categorias` (aditivo): lo que el alta web ofrece en sus selects
  (categorías canónicas + músculos). Sin él no se puede replicar el alta.

## 3. B1: entreno full (plantillas, alta, undo)

### `GET /api/v1/plantillas`

```json
{
  "schema_version": 1,
  "count": 1,
  "plantillas": [
    {"id": 7, "nombre": "Tiron", "clasificacion": "JALON", "ejercicios": ["Remo", "Press"]}
  ]
}
```

Mismo orden que la web (`orden, nombre`). Sin `updated_at` (interno).

### `POST /api/v1/plantilla/aplicar`

```json
{"plantilla_id": 7, "fecha": "2026-09-07"}
```

Preview con la forma de `GET /api/v1/sesion` más `"plantilla_id": 7`: filas
con kg/reps de la última vez por ejercicio (vía `apply_template_rows`, sin
exigir sesión exacta), o vacías (`kg: null`) sin historial. La plantilla
guarda 1 fila por ejercicio; cada ejercicio arrastra todas sus últimas
series posicionales. **No escribe**:
el móvil lo muestra en el editor y el guardado posterior es el
`POST /api/v1/sesion` normal. `plantilla_id` inexistente → `404`;
`fecha` inválida → `400` (se valida primero).

### `POST /api/v1/plantilla/guardar`

```json
{"nombre": "Empuje", "ejercicios": ["Press", "Remo"]}
```

Upsert por nombre como la web (`save_template`: trim, dedup
case-insensitive, clasificación server-side). Respuesta:
`{"schema_version": 1, "plantilla": {id, nombre, clasificacion, ejercicios, updated}}`
(`updated: true` = actualizó el existente). Backup + journal `entrenos`.

### `POST /api/v1/ejercicio`

```json
{"ejercicio": "Sentadilla", "grupo_muscular": "Cuadriceps"}
```

Misma `create_exercise` que la web (`origen='manual'`). La categoría se
deriva del grupo en el servidor (`categoria` se acepta por compatibilidad
pero se ignora). Duplicado case-insensitive → **`409`**; grupo fuera de
`MUSCLE_CATEGORIES` →
`400`. Sin backup/undo, como la web.

### `GET /api/v1/undo/peek` y `POST /api/v1/undo`

```json
// peek: {"schema_version": 1, "kind": "sesion", "fecha_iso": "2026-09-07"}
// undo: {"schema_version": 1, "kind": "sesion", "fecha_iso": "2026-09-07", "has_data": false}
// vacía: {"schema_version": 1, "kind": "empty"}
```

- `kind`: `empty|sesion|entrenos|alimentacion|splits` (los observables desde
  el Diario; `splits` solo si la última acción global fue de splits).
- `POST` acepta cuerpo vacío o `{"fecha": "..."}` (la fecha solo orienta al
  llamante; el undo actúa sobre el top global, como la web). Consume 1
  entrada con backup previo; `has_data` booleano (la web usa `"1"/"0"`).
- El móvil expone botón visible. La web usa `Ctrl+Z` local (R1+R2, sin
  botón ni servidor): solo en modo edición con cambios sin guardar restaura
  el último campo editado; fuera de edición no hace nada y lo guardado nunca
  se altera. `POST /undo` web ya no tiene disparador en la UI (reservado a
  API/móvil).
- El undo de alimentación restaura filas pero no siempre parámetros
  (`params_tracked`): el `kind` no lo distingue; B2 expondrá el detalle.

## 4. B2: nutrición del día (diario, alimentos, plantillas de comida)

### `GET /api/v1/diario?fecha=`

```json
{
  "schema_version": 1,
  "fecha": "2026-09-07",
  "has_data": true,
  "prefilled": false,
  "prefill_source": null,
  "entradas": [
    {"orden": 1, "alimento": "Avena", "cantidad_g": 50.0, "kcal": 195.0, "...": "..."}
  ],
  "consumido": {"kcal": 195.0, "...": "...", "cantidad_g": 50.0},
  "objetivo": {"kcal": 2300.0, "carbohidratos": 297.0, "proteina": 105.0, "grasa": 77.0, "fibra": 38.0, "hierro": 8.0, "calcio": 1000.0, "vitamina_c": 90.0, "vitamina_a": 900.0, "magnesio": 420.0, "zinc": 11.0, "potasio": 3400.0, "sodio": 1500.0, "vitamina_d": 15.0, "vitamina_e": 15.0, "vitamina_k": 120.0, "folato": 400.0, "vitamina_b12": 2.4, "vitamina_b6": 1.3, "yodo": 150.0, "selenio": 55.0},
  "parametros": {"peso_kg": 70.0, "factor_proteina": 1.5, "factor_grasa": 1.1, "kcal_objetivo": 2300.0, "fibra_objetivo": 38.0, "hierro_objetivo": 8.0, "calcio_objetivo": 1000.0, "vitamina_c_objetivo": 90.0, "vitamina_a_objetivo": 900.0, "...": "12 micros DRI v019"}
}
```

- Espejo de `build_nutrition_editor`: día vacío → hereda entradas y
  parámetros del día previo más cercano (`prefilled: true`,
  `prefill_source: "YYYY-MM-DD"`, badge "Datos del…" en el móvil) con
  `has_data: false`; `200`, no `404` (el vacío es estado válido).
- `entradas`: 21 nutrientes tal cual en SQLite + `orden`.
- `consumido`: suma del día (`diary_totals`) + `cantidad_g` total.
- `objetivo`: fórmulas Atwater sobre `parametros` (`prot = peso × factor`,
  `grasa = peso × factor`, `kcal` editable, `carb = (kcal − 4prot − 9grasa)/4`).
- `parametros`: fusión de guardados + defaults web (`70/1.5/1.1/2300` +
  micros DRI hombre adulto `38/8/1000/90/900`).

### `POST /api/v1/diario`

```json
{
  "fecha": "2026-09-07",
  "entradas": [{"alimento": "Avena", "cantidad_g": 50}],
  "peso_kg": 80, "factor_proteina": 2, "factor_grasa": 1, "kcal_objetivo": 2500
}
```

- Reemplazo total idempotente (`save_diary_with_undo_snapshot`): 1–100
  entradas, backup + journal `alimentacion` (comparte la pila de 10).
- Los 21 nutrientes se **recalculan en servidor**
  (`ROUND_HALF_UP(catálogo_100g × g / 100)`); el cliente nunca los envía.
  Alimento inexistente → `404`; cantidad ≤ 0 o fila parcial → `400`;
  día sin entradas válidas → `400` (el vaciado es el `DELETE`; el `POST`
  nunca borra en silencio — divergencia menor y documentada con la web,
  que sí acepta guardar vacío).
- Parámetros opcionales: `peso_kg/factor_proteina/factor_grasa/
  kcal_objetivo` + los 5 objetivos de micros (`fibra_objetivo`,
  `hierro_objetivo`, `calcio_objetivo`, `vitamina_c_objetivo`,
  `vitamina_a_objetivo`, defaults DRI hombre adulto 38/8/1000/90/900).
  Deben ser finitos, `≥ 0`, `peso_kg > 0`; claves
  desconocidas se ignoran. Ausentes → se conservan los previos (UPSERT
  parcial, como la web).
- Respuesta 200: como el `GET` más `"saved_count": N`.

### `DELETE /api/v1/diario?fecha=`

`{"schema_version": 1, "fecha": "...", "deleted": true}`. Idempotente.
Borra filas, **conserva `parametros_diarios`**, con journal
(`alimentacion`, que al deshacer restaura filas pero no parámetros si no
se trackearon — igual que la web).

### `GET /api/v1/alimentos` y `POST /api/v1/alimento`

- Lista: `{schema_version, count, alimentos: [{nombre, categoria + 9}],
  meta: {nutrientes: [{name, label}]}}` (las etiquetas replican el alta web).
- Alta `{nombre, categoria?, 21 nutrientes}` por 100 g, `origen='manual'`;
  duplicado → `409`; nutriente negativo/no-numérico → `400`. Sin
  backup/undo, como la web.

### Plantillas de comida

- `GET /api/v1/plantillas-comida` →
  `{count, plantillas: [{id, nombre, alimentos: [{alimento, cantidad_g}]}]}`.
- `POST /api/v1/plantilla-comida/aplicar {plantilla_id, fecha}` → preview
  `{plantilla_id, fecha, entradas: [...]}` con nutrientes **recalculados
  del catálogo actual** (alimento borrado → ceros, no falla — matiz web
  replicado); inexistente → `404`; **no escribe**.
- `POST /api/v1/plantilla-comida/guardar {nombre, entradas[]}` → upsert por
  nombre `{plantilla: {id, nombre, updated}}`. Sin backup/undo, como la web
  (sus mutaciones van directo a `database`).

## 5. Rueda de rutina sugerida (split + historial, sin saltar entrenos)

`GET /api/v1/sugerencia?fecha=` (solo lectura, sin CSRF por ser `GET`):

```json
{
  "schema_version": 1,
  "fecha": "2026-09-09",
  "tipo": "rutina",
  "explicacion": "Te tocaba martes del 7/9/26 y no se hizo: hoy toca martes.",
  "split_id": 1,
  "slot_dia": "MARTES",
  "pendiente_desde": "2026-09-07",
  "ejercicios": ["Sentadilla"],
  "sets": [
    {"ejercicio": "Sentadilla", "kg": 100.0, "reps": 5.0, "rir": 2.0,
     "descanso_seg": null, "fuente_fecha": "2026-09-02"}
  ]
}
```

- `tipo`: `rutina` (con sets) | `descanso` (aviso, `sets: []`) | `nada`
  (día con datos, o sin split ni historial para proponer).
- Manda el split: las filas son los items del día en orden, duplicados
  incluidos (Press x3 → 3 filas). El historial solo pone valores,
  posicionalmente por ejercicio (serie 1 → última serie 1, sin importar el
  orden global de aquel día); si pide más series de las hechas, se replica
  la última; si hay más historial, se trunca; sin historial → `null`.
- La rueda avanza por cobertura de series (≥ 2/3 de las programadas):
  3/4 avanza, 1/2 no, 1/1 exige hacerlo. Descansar un descanso avanza;
  entrenar en descanso avanza sin crear deuda. Día con datos → `nada`.
- Pesos 1:1 de la última vez de cada ejercicio por su nombre real
  (`fuente_fecha`); sin split activo se repite el
  último día tal cual; sin historial se manda el calendario.
- `fecha` ausente/inválida → `400`. Nunca escribe (el guardado posterior es
  el `POST` normal).

### `GET /api/v1/ejercicio/ultimo?ejercicio=&fecha=`

```json
{
  "schema_version": 1,
  "ejercicio": "Press",
  "fuente_fecha": "2026-09-02",
  "series": [
    {"pos": 1, "kg": 79.0, "reps": 8.0, "rir": 1.5,
     "descanso_seg": null, "velocidad_kmh": null, "dificultad": null},
    {"pos": 2, "kg": 78.0, "reps": 8.0, "rir": 1.5,
     "descanso_seg": 90.0, "velocidad_kmh": null, "dificultad": null}
  ]
}
```

- Misma fuente que la rueda (ordinal por ejercicio). `fecha` opcional excluye
  ese día y posteriores (evita eco del propio día). Sin historial → `series: []`.
- `ejercicio` ausente/desconocido (salvo `HIIT`) o `fecha` inválida → `400`.
  Solo lectura (GET, sin CSRF). Paridad web (`GET /ejercicio/ultimo`) y móvil.

## HIIT: velocidad + dificultad en vez de kg/reps/rir

Serie `HIIT` (nombre exacto, sin importar caja; espejo del tipo especial de
splits): nunca lleva `kg`/`reps`/`rir` (deben ir vacíos, `400` si no) y exige
`velocidad_kmh` (km/h, se redondea a 1 decimal half-up) + `dificultad`
(decimal ≥ 0); `descanso_seg` sigue opcional. Vale sin estar en el catálogo.
Sin RM (métricas y PFR la excluyen por `kg IS NULL`) y sin RIR. Los sets la
llevan en `velocidad_kmh`/`dificultad` (lectura y escritura, plantillas,
sugerencia con `fuente_fecha`).
Separación estricta: una sesión es HIIT pura o fuerza pura, nunca mixta
(`400` si mezcla `HIIT` con otros ejercicios); lo mismo para plantillas
(`POST /api/v1/plantilla/guardar`). En el editor web la columna se rotula
`DIFC` y solo aparece en sesiones HIIT (las de fuerza no muestran
`VEL`/`DIFC`).

## 6. B3: cardio del día (lectura + anotación manual)

### `GET /api/v1/cardio?fecha=`

```json
{
  "schema_version": 1,
  "fecha": "2026-09-07",
  "count": 1,
  "sesiones": [
    {"hc_id": "c1", "titulo": "Cinta", "duracion_min": 30.0,
     "velocidad_kmh": 10.5, "inclinacion_pct": 1.0, "notas": "series"}
  ]
}
```

Espejo de `cardio_day.html`: solo `EXERCISE_SESSION` no borradas cuya fecha
local es el día, con `LEFT JOIN` a su anotación. Día sin sesiones → `count: 0`
(`200`, no `404`).

### `POST /api/v1/cardio/anotacion`

```json
{"hc_id": "c1", "velocidad_kmh": 10.5, "inclinacion_pct": 1.0, "notas": ""}
```

Mismo `upsert_cardio_annotation` que la web: `hc_id` debe existir y ser
`EXERCISE_SESSION` no borrada (`400` si no); todo vacío (`null`/ausente/`""`)
= **borrar** la anotación (respuesta `"deleted": true`). Números finitos
(acepta coma decimal); no numérico → `400`. Sin backup/undo, como la web.
El form web no expone `notas`: la API sí y el móvil lo edita (aditivo).

## 7. Fixtures de referencia

`fixture_empty`: `GET` de un día sin filas → `has_data: false`, `sets: []`.
`fixture_save`: `POST` de 2 series válidas → `saved_count: 2`, `sets[0].rm`
coherente con `rm_ajustado` y `set_orden` 1..2 reasignado.
`fixture_validation`: `POST` con ejercicio inexistente → `400` y 0 filas nuevas.
`fixture_replay`: mismo `POST` dos veces → `saved_count` idéntico y 0 filas nuevas.
`fixture_delete`: `DELETE` tras guardar → `deleted: true`; segundo `DELETE` →
mismo `200` (idempotencia de borrado).
`fixture_template_apply`: `POST` aplicar con historial → preview con kg
heredados y día intacto; sin historial → `kg: null`; id inexistente → `404`.
`fixture_template_save`: `POST` guardar → `updated: false`; repetir nombre →
`updated: true` e igual `id` (upsert, no duplica).
`fixture_exercise_409`: alta duplicada case-insensitive → `409`.
`fixture_undo`: `peek` tras guardar → `kind: sesion`; `POST` undo →
`has_data: false`; segundo `POST` → `kind: empty`.
`fixture_food_recalc`: `POST` 50 g de Avena (389 kcal/100 g) → `kcal: 195`
(half-up servidor) y `consumido` sumado; objetivo con params del `POST`.
`fixture_food_prefill`: día vacío tras día con datos → `prefilled: true` con
`prefill_source` y `has_data: false`.
`fixture_food_404`: alimento inexistente → `404` sin escribir.
`fixture_meal_preview`: aplicar → nutrientes recalculados y día intacto.
`fixture_food_409`: alta duplicada → `409`.
`fixture_suggest_debt`: lunes faltado → martes sugiere `LUNES` con
`pendiente_desde` del lunes y pesos de la última vez.
`fixture_suggest_rest`: tras recuperar, el día de descanso dice `descanso`.
`fixture_suggest_nothing`: día con datos → `tipo: nada`.
`fixture_cardio`: día con sesión → `count: 1` con título y duración; anotar → `deleted: false`; vaciar → `deleted: true`; `hc_id` ajeno → `400`.

## 8. Reglas de edición (divergencia consciente con la web)

- El editor web bloquea en UI los días pasados o con datos (`readonly` salvo
  modo edición); **la API v1 no aplica ese gating**: toda fecha ISO válida es
  editable. El gating web es UX, no seguridad; el dominio (`save_session`)
  siempre aceptó cualquier fecha. La app muestra el aviso de reemplazo antes
  de guardar sobre un día con datos (como el confirm del Diario).

## 9. Concurrencia (last-write-wins en v1)

- Sin `revision` por serie (a diferencia de Health Connect): el `POST`
reemplaza el día completo y **la última escritura gana**. Web + móvil sobre
la misma fecha sin sincronizar = una pisa a la otra; el undo (`POST /undo`
web o `POST /api/v1/undo` móvil) es la red de seguridad. Si el volumen lo
exige, v2 añadirá `updated_at`/409 por conflicto. No inventar campos de
versión por cliente.

## 10. Evolución

`schema_version` en cada respuesta permite evolucionar sin romper APKs viejas.

### B4: fechas + offline unificado

- `GET /api/v1/fechas?vista=entrenamiento|alimentacion|todas` (default
  `entrenamiento`) → `{vista, fechas: [ISO…]}` ordenadas; `400` con otra
  vista. Mismo `get_daily_data_dates` de los puntos del carrusel web.
- Offline móvil (sin cambios de API): caché de nutrición (último payload del
  servidor por fecha; los nutrientes siempre los calcula el servidor) +
  `pending_writes` (una op por dominio+fecha, lo último gana; `SAVE`/`DELETE`
  para `sesion`/`diario`). Drenado oportunista al cargar (como
  `health_outbox`): en orden, el `400/401/404/409/413` descarta, el fallo de
  red conserva el resto; tras entregar se refresca la caché. La UI marca
  `●` en días con datos y avisa de pendientes; los borradores no se pierden.
