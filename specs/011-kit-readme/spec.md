# Spec 011 — README del kit + actualización periódica

Constitución: `docs/constitution.md` (principio 1).

## Contexto y objetivo

El kit no tiene puerta de entrada ni mecanismo de actualización periódica.
Crear `README.md` + aviso de versión en `/skills`.

## Usuarios

El dueño y cualquier agente que descubra el kit.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá `sdd-kit/README.md` (~60 líneas): qué es, estructura, instalación en 3 pasos, comandos, versionado, cero-red, puntero al protocolo. Sin duplicar `SDD_BOOTSTRAP.md`.
- RF-2: EL SISTEMA documentará actualización periódica: versiones en `sdd-lock.json`, revisión mensual checklist (AGENTS vigente, specs con veredicto, allowlists al día).
- RF-3: EL SISTEMA añadirá al comando `/skills` el aviso "kit X disponible, instalado Y".
- RF-4: EL SISTEMA versionará kit v0.5.0 con commit.

## Casos límite

- Lector sin contexto previo → README basta para instalar SDD solo.

## Fuera de alcance

Skill repo-auditor (spec 012). Nada en `entrenamiento` salvo esta spec.

## Criterios de finalización

- README + aviso + commit v0.5.0.

## Dudas abiertas

- Ninguna.
