# Migración del destino de sync: Mac → host persistente

> La app Android es agnóstica al destino: solo conoce una URL HTTPS + token.
> Este documento describe el procedimiento para mover el backend del Mac a un
> host persistente (VPS/Raspberry Pi/nube) sin reescribir la app.

## Por qué funciona sin cambios en la app

- El `target_id` en Room se deriva de la URL: una URL nueva → `target_id` nuevo
  → **seed automático** del buffer local (un `UPSERT` por registro activo).
  La fuente Health Connect **nunca se relee** en un cambio de destino.
- El buffer del móvil solo cubre lo visto desde la instalación. El histórico
  más antiguo (días previos a la instalación del teléfono) está en la SQLite
  del Mac y se migra por export/import de base, no por la app.

## Procedimiento

1. **Backup consistente de SQLite (Mac)**
   ```bash
   GYM_DB_PATH=data/gym.db uv run python - <<'PY'
   import sqlite3
   conn = sqlite3.connect("data/gym.db")
   conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
   conn.close()
   PY
   cp data/gym.db data/gym.db.before-host-migration
   ```
2. **Despliegue del backend en el host**: FastAPI + `uv` (mismo repo), SQLite en
   volumen persistente, `HC_SYNC_TOKEN` nuevo generado con
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. **TLS**: certificado confiable (Let's Encrypt o CA privada instalada en el
   teléfono). La app rechaza HTTP y certificados no confiables.
4. **Restaurar histórico** (opcional pero recomendado): copiar la `gym.db`
   migrada al host **antes** de la primera conexión del teléfono.
5. **Cambiar el destino en la app**: pantalla principal → nueva URL HTTPS +
   nuevo token → Guardar. La app crea el `target_id` nuevo, siembra el buffer y
   entrega por lotes.
6. **Validación**:
   ```sql
   -- en el host, conteo de activos por tipo
   SELECT record_type, COUNT(*) FROM health_records WHERE deleted_at IS NULL GROUP BY record_type;
   ```
   Comparar con el mismo conteo del Mac pre-migración + los registros nuevos.
7. **Rollback**: volver a la URL del Mac (target antiguo intacto en la tabla
   `sync_targets`); el Mac sigue siendo destino válido.

## Notas

- Migrar el dashboard entero a PostgreSQL es un **proyecto separado**; el
  endpoint `/sync/health-connect` solo necesita una SQLite.
- El Mac puede dejar de ser destino (borrar la URL de la app) o convivir
  (dos destinos activos: el outbox entrega a ambos).
- `HC_SYNC_TOKEN` sin configurar en el host → el endpoint responde 503
  (fallo visible, nunca silencioso).
