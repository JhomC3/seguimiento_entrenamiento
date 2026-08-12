# Contrato HTTP de sincronización de Health Connect

> **Estado:** v1 definido en Phase 0. Los fixtures JSON de este documento son la
> fuente única de verdad para las pruebas cruzadas Android/Python (Phase 5.1).

## 1. Reglas generales

- Transporte: HTTPS con certificado confiable. HTTP está prohibido en builds release.
- Autenticación: header `X-Sync-Token` con un token único compartido (`HC_SYNC_TOKEN`
  en el servidor). El token viaja cifrado en el dispositivo (Android Keystore),
  nunca en texto plano, nunca en logs.
- Respuestas de error: `400` payload inválido, `401` token ausente/incorrecto,
  `413` lote excesivo, `503` endpoint sin credencial configurada. `400/401/413`
  son permanentes; red y `5xx` son reintentables.
- Idempotencia: cada operación identifica el registro por `hc_id` y `revision`
  (epoch ms de `lastModifiedTime` en Health Connect). El servidor aplica una
  operación solo si su revisión es mayor que la registrada (o no existe).
- Un lote se aplica atómicamente: si una operación es inválida, se rechaza el lote
  completo con `400` (sin escrituras parciales).

## 2. Límites iniciales (v1)

| Límite | Valor |
|---|---|
| `schema_version` | `1` |
| Operaciones máximas por lote | `500` |
| Tamaño máximo del cuerpo | `1 MiB` (413 por encima) |
| Timeout del cliente OkHttp | 30 s connect, 60 s read |

Estos límites solo se ajustan con evidencia de consumo (Phase 5.1).

## 3. Nombres de tipo estables

`record_type` es el `simpleName` de la clase Kotlin del SDK en `UPPER_SNAKE_CASE`
(por ejemplo `STEPS`, `HEART_RATE`, `SLEEP_SESSION`, `EXERCISE_SESSION`, `WEIGHT`).
El catálogo **esencial** (17 tipos desde 2026-08-12) vive en
`android/.../RecordTypes.kt` y se replica en el servidor como allow-list
amplia en `src/health_sync_service.py` (incluye además el agregado interno
`HEART_RATE_5MIN`). Los 22 tipos no esenciales ya no se sincronizan; sus datos
históricos se conservan pero el dispositivo los purga localmente (migración
Room v2→v3).

## 4. Cuerpo de la petición

```json
{
  "schema_version": 1,
  "device_id": "android-4f2a91c0e7",
  "operations": [
    {
      "op": "UPSERT",
      "hc_id": "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c",
      "record_type": "STEPS",
      "revision": 1754678400000,
      "start_epoch_ms": 1754676000000,
      "end_epoch_ms": 1754679600000,
      "data_origin_package": "com.samsung.health",
      "time_zone_offset_minutes": -300,
      "payload_schema_version": 1,
      "value": { "count": 8123 }
    },
    {
      "op": "DELETE",
      "hc_id": "3a9f2c1b-7d4e-4f0a-9b8c-1e2f3a4b5c6d",
      "record_type": "HEART_RATE",
      "revision": 1754679000000
    }
  ]
}
```

Campos obligatorios por operación:

- `UPSERT`: `op`, `hc_id`, `record_type`, `revision`, `start_epoch_ms`,
  `payload_schema_version`, `value` (objeto JSON no nulo).
- `DELETE`: `op`, `hc_id`, `record_type`, `revision`.
- `record_type` debe pertenecer a la allow-list del servidor.
- `revision` y `start_epoch_ms` deben ser enteros ≥ 0; `end_epoch_ms` ≥ `start_epoch_ms` cuando exista.

## 5. Respuesta de acuse individual

```json
{
  "schema_version": 1,
  "received": 2,
  "accepted_count": 2,
  "accepted": [
    { "hc_id": "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c", "revision": 1754678400000 },
    { "hc_id": "3a9f2c1b-7d4e-4f0a-9b8c-1e2f3a4b5c6d", "revision": 1754679000000 }
  ],
  "rejected": []
}
```

El cliente marca como entregadas **exclusivamente** las operaciones incluidas en
`accepted` (por `hc_id` + `revision`). Un `accepted_count` menor que `received`
con `rejected` poblado no es un error de transporte: el cliente descarta las
rechazadas para ese destino.

## 6. Fixtures de referencia (Phase 5.1)

`fixture_upsert`: el cuerpo de §4 con una sola operación `UPSERT` de `STEPS`.
`fixture_delete`: el cuerpo de §4 con una sola operación `DELETE`.
`fixture_update`: un `UPSERT` del mismo `hc_id` con `revision` mayor y `value.count` distinto.
`fixture_ack`: la respuesta de §5 con `accepted` completo y `rejected: []`.
`fixture_rejected`: respuesta con `accepted_count: 0` y una entrada `rejected` con motivo `unknown_record_type`.
`fixture_replay`: el cuerpo de §4 enviado dos veces seguidas (debe producir `accepted` idéntico y 0 escrituras nuevas).

## 7. Evolución

`schema_version` en el cuerpo y `payload_schema_version` por operación permiten
evolucionar sin romper instalaciones viejas. El servidor responde siempre con su
`schema_version`; si el cliente es más nuevo, degrada o rechaza con `400` y un
motivo accionable.

## 8. Requisito del manifest: handler de política de privacidad

El proveedor de Health Connect (versiones 2025+) **solo registra apps que
declaran el handler del intent de política de privacidad**. Sin él, la app NO
aparece en "Permisos de las apps" de Health Connect y el diálogo de permisos se
abre vacío (verificado en dispositivo: Redmi/Android 13, HC v268669; causa
resuelta alineando el manifest con `android/health-samples`).

La app DEBE declarar en su manifest:

```xml
<!-- En la Activity principal -->
<intent-filter>
    <action android:name="androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" />
</intent-filter>
<intent-filter>
    <action android:name="android.intent.action.VIEW_PERMISSION_USAGE" />
    <category android:name="android.intent.category.HEALTH_PERMISSIONS" />
</intent-filter>

<!-- En <queries> -->
<intent>
    <action android:name="androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" />
</intent>
```

Guard de regresión: `ManifestContractTest` falla si se elimina la declaración.
