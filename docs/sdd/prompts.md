# Prompts por fase SDD

Usar tal cual, sustituyendo `<...>` por el caso concreto. Regla global: el
agente cuestiona antes de obedecer (ver `SDD_BOOTSTRAP.md` §0).

| Fase | Prompt esencial |
|---|---|
| Constitución | "Proponme la constitución de este proyecto: 7 principios cortos y verificables (incluye el deber de criterio propio) sobre stack, calidad, tests y límites. Máx. 20 líneas. Espera mi aprobación." |
| Spec (entrevista) | "NO escribas código. Hazme preguntas de una en una (máx. 6) sobre casos límite, errores y alcance, y después genera spec.md con RF numerados en EARS, fuera de alcance y criterios de finalización. Solo el QUÉ y el POR QUÉ." |
| Clarificación | "Revisa la spec como un QA profesional y crítico: ambigüedades, contradicciones, casos límite ausentes, conflictos con la constitución. Califica cada hallazgo (bloqueante/advertencia/sugerencia). Solo detecta, no resuelvas." |
| Plan | "Lee constitución y spec. Sin código: genera plan.md con módulos, modelo de datos, decisiones justificadas (con la alternativa descartada) y estrategia de tests. Indica qué RF cubre cada parte." |
| Tareas | "Divide el plan en tareas de <30 min, ordenadas por dependencia, cada una con sus RF y una línea 'Hecho cuando:' verificable. Con checkboxes." |
| Implementación | "Implementa SOLO la tarea Tn. Tests primero. Si detectas una incoherencia con la spec o la constitución, DETENTE y repórtala en vez de implementarla. Ejecuta la suite y muéstrame el resultado. Marca Tn como hecha y PÁRATE." |
| Validación | "Recorre la spec RF por RF: qué test cubre cada uno y su resultado. Si alguno no está cubierto o falla, dilo claramente. Veredicto final: ¿spec cumplida?" |
| Cambio | "Nuevo requisito: <X>. NO toques código: actualiza primero la spec (incluye sección de disenso si va contra tu recomendación) y muéstrame el diff." |
