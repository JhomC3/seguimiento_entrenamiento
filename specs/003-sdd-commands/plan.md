# Plan técnico — Spec 003 (docs + mudanza, sin código)

## Estructura destino (`/Users/jhomc/Proyectos/sdd-kit/`, RF-2)

```
sdd-kit/
├── VERSION (0.2.0)
├── sdd-lock.json (manifiesto único: versión + SHA-256 por archivo)
├── SDD_BOOTSTRAP.md (movido intacto)
├── prompts.md (reconvertido a índice → commands/, RF-3)
├── templates/ (movidos intactos)
├── skills/spec-generator/SKILL.md (movida intacta; frontmatter OpenCode en spec 004)
└── commands/ (NUEVO, RF-1, formato docs oficiales)
    ├── constitution.md, specify.md, clarify.md, plan.md,
    ├── tasks.md, analyze.md (NUEVO, RF-6), implement.md, cambio.md
```

## Norma (`/Users/jhomc/Proyectos/AGENTS.md`, RF-4)

~15 líneas: orden de arranque (sin constitución/spec → entrevista primero, sin código),
deferencia al `AGENTS.md` del repo, puntero al kit, permiso de lectura `../sdd-kit/`,
regla comando/trampa/puntero anti-rebrote.

## Backfit `entrenamiento` (RF-5)

Borrar `docs/sdd/` excepto stub `README.md` → `../../sdd-kit`; `AGENTS.md` §9:
puntero `docs/sdd/` → `../sdd-kit` (misma frase, cambia la ruta).

## Decisiones

- Sin `model` en comandos/agentes: heredan el de la sesión (el dueño elige modelo/plan).
- `/cambio` nuestro (vía spec + disenso) junto a los 7 de Spec Kit.
- Comandos con `$ARGUMENTS` donde aporte (`/specify`, `/cambio`, `/implement Tn`).

## Estrategia de tests

Sin código: gates RF-7 + frontmatter válido (verificado por script) + punteros existentes + lectura en frío.
