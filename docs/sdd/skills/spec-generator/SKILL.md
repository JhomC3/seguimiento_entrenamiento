# Skill: spec-generator

Guía la entrevista de requisitos y genera la spec siguiendo la plantilla
(`templates/spec.md`). Vale para proyecto nuevo o funcionalidad nueva.

## Reglas de la entrevista

1. NO escribir código en ningún momento de esta fase.
2. Preguntas de UNA EN UNA (esperar cada respuesta), máx. 6 en total.
3. Preguntar por: casos límite, comportamiento ante errores, qué queda fuera del alcance.
4. Si una respuesta contradice la constitución o es técnicamente inviable, señalarlo en el momento (bloqueante/advertencia) en vez de asumirlo.
5. Solo el QUÉ y el POR QUÉ. Nada de stack, arquitectura ni archivos: eso va en el plan.

## Tras la entrevista

Generar `specs/NNN-<nombre>/spec.md` con: contexto, usuarios, historias,
RF numerados en EARS en español, no-funcionales, casos límite, fuera de
alcance, criterios de finalización, sección de disenso y dudas abiertas
`[NECESITA ACLARACIÓN]`.
