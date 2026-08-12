# Migración del destino de sync: Mac → host persistente

> La app Android es agnóstica al destino: solo conoce una URL + token.
> **Desde 2026-08-12** la app **no tiene formulario de configuración**: el destino
> se embebe en el build debug (`BuildConfig.DEFAULT_SYNC_URL` /
> `DEFAULT_SYNC_TOKEN`, token leído de `data/hc_sync_token` en build-time; release
> sin secreto). Migrar el destino = **recompilar e instalar un APK debug** con los
> nuevos valores (ver §5). Este documento describe el procedimiento.

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
   LIFESTYLE_DB_PATH=data/lifestyle.db uv run python - <<'PY'
   import sqlite3
   conn = sqlite3.connect("data/lifestyle.db")
   conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
   conn.close()
   PY
   cp data/lifestyle.db data/lifestyle.db.before-host-migration
   ```
2. **Despliegue del backend en el host**: FastAPI + `uv` (mismo repo), SQLite en
   volumen persistente, `HC_SYNC_TOKEN` nuevo generado con
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. **TLS**: certificado confiable (Let's Encrypt o CA privada instalada en el
   teléfono). La app debug acepta HTTP (solo en dev); release rechaza HTTP.
4. **Restaurar histórico** (opcional pero recomendado): copiar la `lifestyle.db`
   migrada al host **antes** de la primera conexión del teléfono.
5. **Cambiar el destino en la app** (sin formulario, desde 2026-08-12):
   ```bash
   # 1) Generar token nuevo en el host y volcarlo al archivo del repo
   openssl rand -hex 32 > data/hc_sync_token   # el build lo lee en build-time
   # 2) Editar android/app/build.gradle.kts → debug.DEFAULT_SYNC_URL (URL del host)
   # 3) Recompilar e instalar (reemplaza destino y siembra el buffer nuevo)
   export JAVA_HOME=/opt/homebrew/opt/openjdk@21
   export GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk
   cd android && ./gradlew assembleDebug
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   ```
   El `target_id` nuevo se crea al arrancar; el outbox siembra y entrega por lotes.
6. **Validación**:
   ```sql
   -- en el host, conteo de activos por tipo
   SELECT record_type, COUNT(*) FROM health_records WHERE deleted_at IS NULL GROUP BY record_type;
   ```
   Comparar con el mismo conteo del Mac pre-migración + los registros nuevos.
7. **Rollback**: volver a la URL del Mac (recompilar con los valores antiguos;
   el target antiguo sigue intacto en la tabla `sync_targets`).

## Notas

- Migrar el dashboard entero a PostgreSQL es un **proyecto separado**; el
  endpoint `/sync/health-connect` solo necesita una SQLite.
- El Mac puede dejar de ser destino (recompilar con la URL nueva) o convivir
  (dos destinos activos: el outbox entrega a ambos).
- `HC_SYNC_TOKEN` sin configurar en el host → el endpoint responde 503
  (fallo visible, nunca silencioso).
- Para builds release (sin secreto embebido) el destino se configuraría por
  pairing QR/LAN — no implementado; hoy el canal soportado es el APK debug.
