# Forense: sesiones de 2026-09-03 y 2026-09-05 — pérdida por undo y recuperación

> Fecha: 2026-09-03 · Rama: `feat/dashboard-ui-ux`
> Estado: **pendiente de decisión del usuario** — no se ha restaurado nada.

## 1. Síntoma

El usuario reportó que los guardados desde `/diario` no eran confiables y que
parecía haberse perdido entrenamiento. La investigación demostró que el guardado
**funciona** (verificado por HTTP + navegador + SQLite en el informe del fix de
guardado), y que la pérdida fue causada por **3 ejecuciones de undo (Ctrl+Z)**.

## 2. Evidencia

| Backup (`data/backups/`) | Filas `training_sets` | `undo_entries` max id | Sesiones 09-03/09-05 |
|---|---|---|---|
| `lifestyle-20260903-153310.db` | 1323 | 157 | ✅ presentes (25 filas) |
| `lifestyle-20260903-153313.db` | 1311 | 156 | ❌ 09-05 borrada |
| `lifestyle-20260903-153315.db` | 1298 | 155 | ❌ 09-03 y 09-05 borradas |
| `data/lifestyle.db` (actual) | 1298 | 154 | ❌ |

- Las entradas de undo 156 y 157 eran sesiones **nuevas** (`"before": []`) de
  `2026-09-03` y `2026-09-05`, guardadas el 09-02 22:55–22:56 (origen manual).
- `undo_last_action` hace backup **antes** de restaurar: por eso existen los 3
  backups del 09-03 15:33:10/13/15, cada uno con una entrada de undo menos.
- Las filas perdidas (25) tienen `origen='manual'` y existen íntegras en
  `data/backups/lifestyle-20260903-153310.db`.

## 3. Procedimiento de recuperación seguro (NO EJECUTADO)

La restauración es mínimamente invasiva: inserta solo las 25 filas manuales de
`training_sets` de las fechas 2026-09-03 y 2026-09-05, sin tocar el resto.

```bash
# 1) Backup adicional de seguridad del estado actual
sqlite3 data/lifestyle.db ".backup 'data/backups/lifestyle-pre-restore-0903-0905-$(date +%Y%m%d-%H%M%S).db'"

# 2) Reconstruir las filas perdidas desde el backup 153310 (solo esas fechas)
sqlite3 data/lifestyle.db "
ATTACH DATABASE 'data/backups/lifestyle-20260903-153310.db' AS src;
INSERT OR IGNORE INTO training_sets
  (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, descanso_seg, origen)
SELECT semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, descanso_seg, origen
FROM src.training_sets
WHERE fecha IN ('2026-09-03', '2026-09-05') AND origen = 'manual';
DETACH DATABASE src;
"

# 3) Verificación
sqlite3 data/lifestyle.db "
SELECT fecha, COUNT(*) FROM training_sets
WHERE fecha IN ('2026-09-03', '2026-09-05') GROUP BY fecha;
"
# Esperado: 2026-09-03 -> 13, 2026-09-05 -> 12
```

### Validación del esquema

El backup 153310 comparte el mismo esquema y migraciones (v1–v15) que la base
actual; `training_sets` no cambió de columnas entre ambos. La migración v014
(índice `(fecha, set_orden)`) no altera columnas.

### Nota sobre undo

Tras la restauración no se crea entrada de undo para el restore (operación
administrativa, no una mutación de la app). Si se quisiera que Ctrl+Z pudiera
deshacerla, insertar manualmente una entrada `kind='sesion'` con el `before`
vacío sería lo simétrico, pero no es necesario.

## 4. Conclusión operativa

- No se sobrescribió ni reemplazó `data/lifestyle.db`.
- La base consultada y la escrita son la misma (`config.DB_PATH`, logging del
  path absoluto en el arranque).
- Los backups automáticos (pre-mutación y pre-migración) funcionaron como
  diseño: la evidencia de la pérdida y la fuente de la recuperación viven en
  `data/backups/`.