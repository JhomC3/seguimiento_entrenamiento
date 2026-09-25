# Spec 016 — README de proyecto vivo

Constitución: `docs/constitution.md` (principio 1).

## Contexto y objetivo

`entrenamiento` no tiene puerta de entrada para humanos. Crear `README.md`
que apunte sin copiar, y exigirlo en todo proyecto vía kit.

## Usuarios

El dueño y cualquier humano/agente que descubra el proyecto.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá `README.md` (~40 líneas): qué es, arranque en 3 pasos, mapa a `docs/`, estado como punteros + fecha de verificación. Prohibidas enumeraciones volátiles.
- RF-2: EL SISTEMA enmendará el kit en protocolo §4 (README exigido en todo proyecto nuevo) y §10 (toda spec que cambie arranque/stack/mapa lo actualiza).
- RF-3: EL SISTEMA ampliará la checklist mensual del kit con revisar el README.
- RF-4: Kit v0.8.0 + commit. Gates verdes.

## Fuera de alcance

Reescribir `docs/`. README del kit (intacto salvo checklist).

## Criterios de finalización

- README + enmiendas + checklist revisada en sesión fresca + commits.

## Dudas abiertas

- Ninguna.
