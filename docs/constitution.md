# Constitución — entrenamiento

Principios innegociables. Toda spec, plan y tarea debe cumplirlos. Detalle vinculante en `docs/architecture/backend-standards.md` y `docs/architecture/web-standards.md`.

1. **La spec manda**: ningún comportamiento se implementa si no está en la spec activa; todo cambio empieza actualizando la spec.
2. **Monolito modular**: handlers delgados → servicios de dominio tipados → `src/database.py` (único SQL); prohibido lógica de negocio en `app.py`.
3. **Datos seguros**: escritura multi-fila en `transaction(...)`, constraints en migración versionada, backup pre-mutación + undo (máx. 10).
4. **El servidor decide**: validación en el borde y recálculo en servidor (RM, nutrientes); dominio → 400 seguro, inesperado → 500 genérico + `logger.exception`.
5. **Server-first y seguro**: HTML + htmx, tokens visuales como única verdad, WCAG AA, CSP estática, CSRF + Origin, secretos nunca en cliente ni en git.
6. **Tests como puerta**: `pytest` + `ruff` + `mypy` en verde, cobertura ≥ 90 %; todo cambio de contrato lleva su test.
7. **Criterio propio**: el agente tiene obligación profesional de cuestionar instrucciones erróneas, incoherentes o riesgosas; ante un bloqueante se detiene y exige resolución; si el dueño confirma seguir contra la recomendación, se obedece y se registra el disenso en la spec.
