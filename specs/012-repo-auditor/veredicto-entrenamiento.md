# Veredicto repo-auditor contra entrenamiento (validación spec 012, 2026-09-25)

| Hallazgo | Gravedad | Acción |
|---|---|---|
| `AGENTS.md` 125 líneas, sin inventarios | sano | nada |
| `docs/plans/` con 8 planes narrativos sin estado (MASTER-PLAN.md, etc.) | advertencia | marcar `CONGELADO` en cabecera en su sitio (spec futura; `archive/` ya existe como precedente) |
| Sin `adr/`; decisiones en `docs/architecture/` + specs | nota | patrón aceptable a este tamaño; crear `adr/` solo cuando una decisión trascienda specs |
| Sin `CLAUDE.md` | nota | solo relevante si se usa Claude Code; opencode no lo requiere |
| Sin dirs duplicados, plantillas rivales ni backlogs | sano | nada |
| `chat_completo_*.md` sin trackear (checkout principal) | nota para el dueño | decidir: borrar o mover fuera del repo |

Deuda registrada, nada escondido. Cero bloqueantes: apto para SDD (ya lo usa).
