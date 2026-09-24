# Spec 002 — Poda quirúrgica de AGENTS.md

Constitución: `docs/constitution.md` (principio 1: todo cambio empieza en la spec).

## Contexto y objetivo

`AGENTS.md` tiene 291 líneas y duplica documentación autoritativa
(`migrations/`, contratos, standards), lo que genera deriva y diluye las
instrucciones. Podarlo a un mapa denso de punteros + trampas no inferibles,
sin perder cumplimiento.

## Usuarios

Cualquier agente que trabaje en el repo.

## Historias de usuario

- H1: Como agente quiero instrucciones cortas y densas para cumplirlas todas en cada tarea.
- H2: Como dueño quiero cero deriva entre `AGENTS.md` y la documentación autoritativa.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA (`AGENTS.md`) conservará inline íntegros: §0 sandbox, §0.5 worktrees, comandos §2/§8, invariantes de seguridad y §9 SDD.
- RF-2: EL SISTEMA condensará §1 a 1-2 frases y §4 a trampas no inferibles (migraciones como única vía, hueco `v004`, alias `GYM_DB_PATH`, `origen` google/manual).
- RF-3: EL SISTEMA sustituirá el inventario §3 y el inventario de rutas §5 por tablas Área → Leer primero que apunten a los docs autoritativos.
- RF-4: EL SISTEMA reducirá §5.5/§7.5/§6/§7 a esencia + puntero, sin borrar ninguna invariante exigible.
- RF-5: EL SISTEMA incluirá el mapa de equivalencia de secciones antiguas → nuevas en esta spec; las specs 000/001 cerradas NO se reescriben (sus referencias valen al commit de su merge, trazable por git).
- RF-6: EL SISTEMA mantendrá los gates en verde (`pytest --ignore=tests/e2e`, `ruff format --check`, `ruff check`, `mypy`).

## Requisitos no funcionales

- Cero borrado de conocimiento: todo lo podado vive ya en `docs/` o `src/`.
- Resultado estimado: ~150-170 líneas densas (el número exacto lo fija el criterio, no al revés).

## Casos límite

- Trampa que solo vive en `AGENTS.md` y en ningún otro doc → se queda inline, nunca se poda.
- Referencia futura a una sección renumerada → usar el mapa de equivalencia de esta spec.

## Fuera de alcance

- Cambios de conducta, código o contratos. Solo documentación.
- Tocar las specs 000/001 cerradas.

## Criterios de finalización

- `AGENTS.md` podado + gates RF-6 en verde + diff revisado (adiciones/eliminaciones justificadas línea a línea en el commit).

## Mapa de equivalencia (antigua → nueva)

- §0, §0.5, §8, §9 → se conservan ( §9 sin cambios).
- §1 (rol, párrafo) → §1 (2 frases).
- §2 (stack) → §2 (condensado, mismos comandos).
- §3 (inventario por archivo) → §3 (tabla Área → Leer primero).
- §4 (schema completo) → §4 (trampas + puntero a `src/migrations/`).
- §5 (inventario de rutas) → §5 (esencia + tabla de 4 contratos).
- §5.5 / §7.5 → esencia + puntero a sus docs.
- §6 / §7 → esencia + punteros (`src/metrics_engine.py`, `src/parser.py`, `static/design-tokens.json`, `static/css/components.css`).

## Dudas abiertas

- Ninguna.
