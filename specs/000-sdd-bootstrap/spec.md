# Spec 000 — Línea base SDD de entrenamiento

Kit: instanciación local (sin dependencia externa). Constitución: `docs/constitution.md`.

## Contexto y objetivo

Fijar el comportamiento actual del dashboard como línea base inmutable para
instalar el flujo SDD. No introduce ni cambia conducta: solo la describe para
que cualquier cambio futuro empiece actualizando una spec.

## Usuarios

Un único usuario local (personal, loopback por defecto + sync LAN desde la app
Android HealthSync). Sin multi-usuario ni cuentas.

## Historias de usuario

- H1: Como usuario quiero registrar y revisar mi entrenamiento diario para ver mi progresión.
- H2: Como usuario quiero registrar mi alimentación diaria para verla contra mis objetivos.
- H3: Como usuario quiero sincronizar mis datos de salud desde Android para conservarlos localmente.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO el usuario abra `GET /`, EL SISTEMA mostrará la cascada de niveles y la gráfica unificada según `docs/architecture/current-ui-contract.md` vigente.
- RF-2: CUANDO el usuario guarde o elimine la sesión del día (`POST /entrenamiento/session/save`, `POST /entrenamiento/session/eliminar`), EL SISTEMA validará en el borde, recalculará en servidor, hará backup pre-mutación y registrará undo (salida: fragmentos OOB del contrato).
- RF-3: CUANDO el usuario guarde o elimine el diario (`POST /alimentacion/save`, `POST /alimentacion/eliminar`), EL SISTEMA recalculará los nutrientes contra el catálogo con `ROUND_HALF_UP` y nunca confiará en macros del cliente.
- RF-4: MIENTRAS existan plantillas o splits, EL SISTEMA los gestionará con reemplazo idempotente, validación en servidor y undo donde el contrato lo exija.
- RF-5: CUANDO la app Android envíe `POST /sync/health-connect` con `X-Sync-Token` válido, EL SISTEMA hará upsert condicionado por revisión con acuse individual según `docs/architecture/health-sync-contract.md`; SI el token falta o es inválido, ENTONCES EL SISTEMA responderá 503/401 sin persistir.
- RF-6: EL SISTEMA aplicará en el arranque las migraciones pendientes de `src/migrations/` de forma transaccional con backup previo, y nunca cambiará el esquema fuera de una migración versionada.
- RF-7: SI una petición remota con el gate LAN activo (`GYM_LAN_SYNC_ONLY=1`) no está en la allow-list exacta de `src/network_access.py`, ENTONCES EL SISTEMA la rechazará con 403/429 antes de parsear el body.
- RF-8: EL SISTEMA mantendrá los gates de calidad: `pytest` + `ruff format --check` + `ruff check` + `mypy` en verde y cobertura de ramas ≥ 90 %.

## Requisitos no funcionales

- Arranque único `./scripts/start_server.sh`; `LIFESTYLE_DB_PATH` (`GYM_DB_PATH` alias); secretos gitignored en `data/`.
- Server-first + htmx, CSP estática, CSRF + Origin en mutaciones, SQL parametrizado.
- Mensajes al usuario en español, seguros y accionables.

## Casos límite ya cubiertos (por el sistema actual)

- Doble guardado del mismo día → reemplazo idempotente, sin duplicar.
- Archivo/DB corrupta o migración pendiente → backup previo, nunca sobrescritura silenciosa.
- Lote de sync excesivo o revisión obsoleta → rechazo/acuse sin persistir lo inválido.
- Payload hostil (XSS, arrays desalineados, NaN/Inf) → 400 seguro + log servidor.

## Fuera de alcance

Cualquier cambio de conducta, refactor, renombre de rutas, nuevo endpoint o
nuevo cálculo. Todo eso requiere una spec `NNN` posterior.

## Criterios de finalización

- `docs/constitution.md` creado y `AGENTS.md` fusionado con bloque SDD.
- Esta spec + `plan.md` + `tasks.md` existen bajo `specs/000-sdd-bootstrap/`.
- `pytest --ignore=tests/e2e` + `ruff` + `mypy` en verde en el worktree.

## Dudas abiertas

- Ninguna para la línea base. Las dudas de futuras specs irán en su propia spec marcadas como `[NECESITA ACLARACIÓN]`.
