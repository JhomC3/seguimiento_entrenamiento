---
description: Interview (max 6 questions, one by one) and generate the EARS spec, no code
---

NO escribas código. Vamos a redactar la especificación de: $ARGUMENTS.

1. Hazme preguntas de UNA EN UNA (espera cada respuesta, máx. 6 en total)
   sobre casos límite, comportamiento ante errores y qué queda fuera del alcance.
2. Si una respuesta contradice la constitución o es técnicamente inviable,
   señálalo en el momento (bloqueante/advertencia) en vez de asumirlo.
3. Con mis respuestas, genera `specs/NNN-<nombre>/spec.md`: contexto y objetivo,
   usuarios, historias de usuario, RF numerados con criterios de aceptación en
   notación EARS en español, no-funcionales, casos límite, fuera de alcance,
   criterios de finalización, sección de disenso y dudas `[NECESITA ACLARACIÓN]`.
4. Solo el QUÉ y el POR QUÉ. Nada de stack, arquitectura ni archivos: eso va en el plan.
