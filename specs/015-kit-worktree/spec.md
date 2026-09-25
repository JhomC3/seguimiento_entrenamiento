# Spec 015 — Regla worktree-por-tarea al kit

Constitución: `docs/constitution.md` (principio 1).

## Contexto y objetivo

La regla "una tarea = una rama = un worktree" vive solo en `entrenamiento`.
Portarla al kit en lenguaje neutro al stack, con justificación y alcance.

## Usuarios

Cualquier agente en cualquier proyecto bajo `Proyectos/`.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA añadirá a `SDD_BOOTSTRAP.md` la sección de aislamiento (worktree por tarea dentro del proyecto, entorno/datos/secretos/puertos aislados, prohibido compartir directorio), con ejemplos de `entrenamiento` en bloque EJEMPLO.
- RF-2: EL SISTEMA añadirá a `templates/AGENTS.md` el bloque git/worktrees + cláusula de alcance (código/conducta en paralelo sí; fix trivial de docs directo con revisión).
- RF-3: Cada regla llevará su porqué en una línea.
- RF-4: Cero jerga de stack en la norma (ni `uv`, ni puertos concretos, ni rutas de ejemplo fuera de EJEMPLO).
- RF-5: Kit v0.7.0 + commit.

## Fuera de alcance

Cambios en `entrenamiento`. Instalación en otros repos.

## Criterios de finalización

- Checklist RF-1..RF-4 revisada + kit commiteado.

## Dudas abiertas

- Ninguna.
