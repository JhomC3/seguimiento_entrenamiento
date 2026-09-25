# Spec 014 — Matar docs/plans/ + resto de mudanza

Constitución: `docs/constitution.md` (principio 1).
Numeración: 013 reservada (diferida, fuera de este proyecto).

## Contexto y objetivo

`docs/plans/` son planes narrativos muertos; el archivo es git y la cola
activa son las specs abiertas. Eliminar todo `docs/plans/` y el resto vacío
de la mudanza, reparando los 2 punteros vivos.

## Usuarios

Todo agente del repo (cero planes fantasma que leer).

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA eliminará `docs/plans/` completo (raíz + `archive/`); git guarda la historia.
- RF-2: EL SISTEMA reparará `docs/architecture/dashboard-current.md:7` (apuntaba a MASTER-PLAN): la cola activa vive en `specs/` abiertas.
- RF-3: EL SISTEMA reparará `docs/architecture/backend-standards.md:214` (mencionaba `docs/plans/*`): los planes viven en `specs/NNN/`.
- RF-4: EL SISTEMA eliminará el resto vacío `docs/sdd/templates/AGENTS.md` (0 bytes, sin contenido; el dueño declara no haberlo creado).
- RF-5: EL SISTEMA no tocará specs cerradas (000–012) aunque citen `docs/plans/` (historia).
- RF-6: Gates en verde.

## Casos límite

- Referencia ya rota en doc histórico (`docs/analysis/*`) → se deja (historia, no se reescribe).

## Fuera de alcance

Refactors 006–009. Nuevos planes (prohibidos por regla).

## Criterios de finalización

- `docs/plans/` no existe; los 2 punteros apuntan a `specs/`; resto eliminado; gates verdes.

## Dudas abiertas

- Ninguna.
