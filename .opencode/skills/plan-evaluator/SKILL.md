---
name: plan-evaluator
description: Evaluate a technical plan against its spec and constitution with a verdict
---

## Qué hago
Evalúo planes técnicos contra su spec y constitución antes de implementar.

## Cuándo usarme
Úsame cuando pidan: evaluar/revisar un plan, ¿este plan está bien?, ¿qué le falta al plan?

## Checklist
- Todo RF tiene cobertura en el plan (y nada sobra sin RF).
- Decisiones con alternativa descartada; nada contradice la constitución.
- Alcance, riesgos y estrategia de tests explícitos; tareas <30 min con "Hecho cuando:".
- Sin código prematuro ni stacks inventados (comandos del repo, no genéricos).

## Veredicto
APROBADO / APROBADO CON RESERVAS (lista) / BLOQUEADO (lista + qué falta).
