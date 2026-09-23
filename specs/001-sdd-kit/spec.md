# Spec 001 — Kit SDD portable + deber de criterio propio

Constitución: `docs/constitution.md` (principio 1: todo cambio empieza en la spec).

## Contexto y objetivo

El usuario no tiene formación técnica y puede pedir instrucciones erróneas o
incoherentes. El SDD instalado en la spec 000 no otorga al agente criterio
propio ni existe como molde reutilizable para otros proyectos. Esta spec crea
ambas cosas: un kit portable que cualquier agente puede seguir en cualquier
repo, y la obligación profesional de cuestionar en lugar de obedecer a ciegas.

## Usuarios

- El dueño (no técnico) que crea proyectos y pide funcionalidades.
- Cualquier agente que instancie SDD en un repo nuevo o ya iniciado.

## Historias de usuario

- H1: Como dueño quiero que el agente me contradiga con argumentos cuando pida algo erróneo, para no construir sobre errores míos.
- H2: Como dueño quiero un paso a paso portable que cualquier agente siga para instalar SDD desde cero en cualquier proyecto.
- H3: Como agente quiero plantillas y prompts fijos para no improvisar el proceso en cada repo.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO el usuario pida un comportamiento nuevo, EL SISTEMA (agente) hará primero la entrevista (máx. 6 preguntas, una por una, sobre límites, errores y alcance) y NO escribirá código hasta tener la spec aprobada.
- RF-2: SI la instrucción contradice la constitución, es técnicamente inviable, arriesga pérdida de datos o introduce inseguridad, ENTONCES EL SISTEMA se detendrá (bloqueante) y exigirá una resolución antes de planificar.
- RF-3: SI la instrucción es subóptima pero viable, ENTONCES EL SISTEMA la calificará como advertencia o sugerencia, propondrá una alternativa con sus trade-offs y solo seguirá con confirmación explícita.
- RF-4: CUANDO el usuario confirme seguir contra la recomendación, EL SISTEMA lo registrará en la spec como "decisión consciente contra recomendación" y obedecerá; el disenso nunca será silencioso.
- RF-5: EL SISTEMA proveerá un kit portable bajo `docs/sdd/` con protocolo bootstrap (proyecto nuevo vs ya iniciado), plantillas (constitución, AGENTS, spec, plan, tareas), prompts por fase y skill de entrevista, sin referencias a ningún stack concreto.
- RF-6: EL SISTEMA añadirá a `docs/constitution.md` el principio de criterio propio y extenderá `AGENTS.md` §9 con deber, condiciones de parada, niveles y formato de disenso, sin reordenar ni borrar nada existente.
- RF-7: EL SISTEMA mantendrá los gates en verde (`pytest --ignore=tests/e2e`, `ruff format --check`, `ruff check`, `mypy`) al cerrar.

## Requisitos no funcionales

- Todo dentro del árbol del proyecto (máxima sandbox); el kit se vendoriza por copia, nunca por lectura/escritura fuera del repo.
- Documentación y mensajes en español; plantillas sin secretos ni datos reales.

## Casos límite

- Usuario que insiste tras advertencia → RF-4 (se obedece con registro, no se bloquea para siempre).
- Proyecto nuevo sin código → bootstrap salta la retro-spec y empieza en spec 001.
- Proyecto ya iniciado → bootstrap fija primero la línea base 000 antes de cualquier cambio.
- Conflicto entre plantillas del kit y reglas existentes del repo → mandan las reglas existentes y se anota.

## Fuera de alcance

- Instalar el kit en otros repos (cada uno tendrá su propia spec de bootstrap).
- Automatizar la "detección de incoherencias" más allá del juicio del agente + entrevista + clarificación QA.

## Criterios de finalización

- Kit completo bajo `docs/sdd/` + constitución con principio 7 + §9 extendido.
- Gates RF-7 en verde en el worktree.

## Dudas abiertas

- Ninguna.
