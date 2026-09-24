# SDD_BOOTSTRAP — Protocolo portable de instalación SDD

Para que cualquier agente instale Spec-Driven Development desde cero en
cualquier proyecto, nuevo o ya iniciado. Origen: `mouredev/hello-sdd`.
Plantillas en `templates/`, prompts en `prompts.md`, entrevista en
`skills/spec-generator/SKILL.md`.

## 0. Deber de criterio propio (obligatorio, permanente)

El agente tiene criterio técnico propio y **obligación profesional de usarlo**.
No obedece a ciegas: ante una instrucción errónea, incoherente o riesgosa, se
detiene y la cuestiona con argumentos. Reparto:

- El dueño decide el **problema** (qué duele, para quién, qué vale).
- El agente decide el **juicio técnico** (cómo, con qué, qué riesgos, qué es incoherente).

### Condiciones de parada (bloqueante: no se avanza hasta resolver)

- Contradicción con la constitución del repo.
- Petición técnicamente inviable con el stack actual.
- Riesgo de pérdida de datos sin backup/undo.
- Inseguridad (secretos, auth, validación ausente).

### Niveles

- **Bloqueante**: se detiene, exige resolución. Sin código hasta entonces.
- **Advertencia**: viable pero subóptimo o riesgoso. Se propone alternativa con trade-offs; se sigue solo con confirmación explícita.
- **Sugerencia**: mejora pragmática. Se propone, se sigue con la opción del dueño si la prefiere.

### Disenso documentado

Si el dueño confirma seguir contra la recomendación, el agente obedece pero lo
registra en la spec:

```
> Decisión consciente contra recomendación (fecha): <qué se decidió> /
> Recomendación descartada: <alternativa> / Motivo del dueño: <motivo>
```

El disenso nunca es silencioso.

## 1. Paso 0 — Inventario read-only

Antes de escribir nada: stack real, comandos reales (los del repo, nunca
inventados), tests y gates reales, docs y decisiones existentes. Registrar
hallazgos en notas temporales. Prohibido copiar stacks de otros proyectos.

## 2. Proyecto nuevo vs ya iniciado

- **Nuevo** (sin código): saltar al paso 4 con spec `001-<nombre>`.
- **Ya iniciado**: fijar primero la línea base `specs/000-<nombre>/spec.md`
  que describa la conducta actual observada (EARS), con fuera de alcance =
  "ningún cambio de conducta". Sin refactor en esta fase.

## 3. Constitución

Redactar `docs/constitution.md`: principios cortos y verificables (stack,
spec-manda, separación lógica/interfaz, tests, datos, idioma + criterio
propio). Si el repo ya tiene principios o standards, destilarlos sin
contradecirlos: ante conflicto mandan los existentes y se anota.

## 4. Contexto del agente

Completar `AGENTS.md` por fusión aditiva (nunca borrar ni reordenar): qué es
el proyecto, comandos verificados, estilo, límites y bloque SDD (leer
constitución + spec activa antes de tocar código; cambio vía spec).

## 5. Spec (entrevista, sin código)

Con la skill `spec-generator`: entrevista de máx. 6 preguntas, una por una,
sobre casos límite, errores y alcance. Después generar `spec.md`: contexto,
usuarios, historias, RF numerados en EARS (CUANDO/SI/MIENTRAS + respuesta),
no-funcionales, casos límite, fuera de alcance, finalización y dudas
`[NECESITA ACLARACIÓN]`. Solo el QUÉ y el POR QUÉ.

## 6. Clarificación (QA, sin código)

Revisar la spec como QA profesional: ambigüedades, contradicciones, casos
límite ausentes, conflictos con la constitución. Calificar cada hallazgo
(bloqueante/advertencia/sugerencia). Solo detecta; el dueño resuelve. Los
bloqueantes impiden planificar.

## 7. Plan + tareas (sin código)

`plan.md`: módulos, datos, algoritmo, contrato, decisiones con alternativa
descartada, qué RF cubre cada parte, estrategia de tests. `tasks.md`: tareas
de <30 min en orden de dependencia, cada una con sus RF y `Hecho cuando:`.

## 8. Implementación (una tarea cada vez, tests primero)

Implementar SOLO la tarea Tn: tests primero, ejecutar la suite, marcar Tn y
parar. Prohibido avanzar con tests en rojo o empezar Tn+1 sin cierre de Tn.

## 9. Validación (veredicto explícito)

Recorrer la spec RF por RF: qué test cubre cada uno y su resultado. Si algún
RF no está cubierto o falla, declararlo. Veredicto: ¿spec cumplida? Criterios
de finalización comprobados uno por uno.

## 10. Cambio (siempre vía spec)

Nuevo requisito o corrección: primero actualizar la spec y mostrar su diff;
después el código. Un cambio de conducta sin diff de spec es un defecto.
