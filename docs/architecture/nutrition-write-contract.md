# Contrato de escritura nutricional en Health Connect

> **Estado:** v2 (2026-09-15). La app Android publica el diario de alimentación
> en Health Connect para que Google Fit / Samsung Health lo lean. Solo escritura;
> la lectura de `NUTRITION` sigue excluida del sync (sin bucle). Publicación
> silenciosa por diseño: sin avisos ni botones (ver manual operativo en
> `docs/operations/nutrition-sync-manual.md`).

## 1. Reglas

- Fuente de verdad: `GET /api/v1/diario` (nutrientes recalculados en servidor).
  Nunca se publica desde borrador, caché prefill ni preview de plantilla.
- 1 registro `NutritionRecord` por alimento (entrada del diario).
- El pase del sync solo publica días con `hasData == true`. Un día vacío o con
  prefill heredado **nunca** se publica (duplicaría el día anterior); en ese
  caso se borran los huérfanos de esa fecha.
- Disparo solo automático: `saveNutrition OK`, `deleteNutrition OK`,
  `undo kind=alimentacion`, `drainOutbox diario SAVE/DELETE OK`,
  reconciliación en `loadNutritionInternal Fresh` (cubre edición web) **y pase
  `NutritionSyncPass` dentro del sync ("Sincronizar AHORA" + worker): publica
  los días con datos aún no publicados. Este último es el que cubre lo guardado
  en la web, ya que la Activity no expone la vista de alimentación.
- Días con escritura móvil pendiente de drenar se saltan ese run: el drenado
  pisa el servidor después y el siguiente sync publica ya reconciliado
  (evita publicar un estado que el drenado va a pisar).
- Silencio total: ningún aviso, toast ni badge de comida en la UI. Los
  contadores viven en `SyncReport` (logs/diagnóstico), no en el resumen visible.

## 2. Mapeo

| Diario | HC | Notas |
|---|---|---|
| `alimento + cantidad_g` | `name = "<alimento> (<g> g)"` ≤100 chars | visible en Fit |
| `kcal` | `energy` (kcal) | omitir si ≤0 o >100k |
| `proteina` | `protein` (g) | 0..100k g |
| `carbohidratos` | `totalCarbohydrate` (g) | idem |
| `grasa` | `totalFat` (g) | idem |
| `fibra` | `dietaryFiber` (g) | idem |
| `calcio mg` | `calcium` (g = mg/1000) | 0..100 g |
| `hierro mg` | `iron` (g = mg/1000) | idem |
| `vitamina_c mg` | `vitaminC` (g = mg/1000) | idem |
| `vitamina_a µg` | `vitaminA` (g = µg/1e6) | puede perderse por precisión; documentado |

Campos fuera de rango o ≤0 se omiten (no tumban la fila). Fila sin ningún
nutriente válido se omite (no se publica vacía).

## 3. Tiempo = fecha del diario

El diario solo trae fecha y la hora exacta del registro carece de significado.
Cada fila usa una ventana de 1 minuto terminada a las 12:00 de su propia fecha,
en la zona local del dispositivo, con `mealType = UNKNOWN` siempre. Si la fecha
es hoy y todavía no son las 12:00, se usa `now` para no crear un registro futuro:

- Nunca futura por construcción (HC rechaza `start` en futuro y el insert es
  transaccional: un slot futuro tumbaría el día entero).
- Sin franjas, sin husos que calcular, sin falsa precisión de ingesta.
- El histórico conserva su día y no se concentra artificialmente en el día del
  sync.
- `TIME_POLICY_VERSION = 2` cambia el hash y eleva las versiones para que el
  siguiente sync reubique los registros creados por la política anterior.

## 4. Idempotencia

- `clientRecordId = gym-diario-<fecha>-<orden>` (estable).
- `clientRecordVersion` incluye la versión temporal y usa un rango superior al
  de la política anterior; así el siguiente sync fuerza la actualización de
  los registros creados con la hora del sync.
- Re-insert = upsert HC; edición = misma ID + versión mayor (sin delete+create).
- Borrado por `clientRecordIds` (solo WRITE, sobre lo propio; sin READ).
- Estado Room `nutrition_publish(fecha, day_hash, client_ids, status, detail)`:
  si `day_hash` publicado == deseado → no-op. Migración Room v11→v12 (la v10
  ya existía con otro significado al integrar: convergencia documentada en
  `NutritionPublish.kt`).

## 5. Permisos

- Manifest: `WRITE_NUTRITION` (sin `READ_NUTRITION`: mínimo privilegio).
- Runtime: `HealthPermission.getWritePermission(NutritionRecord::class)`,
  incluido en el diálogo único de permisos esenciales.
- Sin permiso → estado `PENDING/sin_permiso`, sin crash; reintento en el
  siguiente guardado/load/drenado.

## 6. Límites y errores

- Pase acotado: máx. 10 días por ejecución (recientes primero); el resto sale
  en el siguiente sync. Presupuesto: 1 `fechas` + 1 GET por día (timeouts LAN
  cortos 5s/10s).
- Inserción de una en una (el `insertRecords` HC es transaccional: un registro
  malo tumbaría el día entero si se mandara en lote).
- `SecurityException` (permiso revocado) → estado `PENDING/sin_permiso`, sin
  crash; reintento en el siguiente sync.
- `RemoteException/IO` → estado `ERROR` con detalle no sensible (`insert:<id>`).
- Borrado inexistente se ignora por ID (troceado individual).
- Borrado manual en Health Connect (Toolbox u otra app): el pase **no** lo
  detecta (sin READ por mínimo privilegio): hash publicado == hash servidor →
  no-op → la divergencia persiste hasta la próxima edición del día. No borrar
  a mano (ver manual operativo).

## 7. Fixtures

- `diario 1 alimento` → 1 `NutritionRecord` con energía/macros y `name`.
- `edición cantidad` → misma `clientRecordId`, versión distinta, sin duplicar.
- `borrado día` → `deleteNutritionByClientIds` + Room limpio.
- `sin permiso` → 0 inserts, estado `PENDING`.
