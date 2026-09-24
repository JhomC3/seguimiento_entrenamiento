---
description: Cross-check spec, plan and tasks for consistency and coverage before implementing
---

Sin escribir código, verifica la consistencia cruzada de la spec activa:
1. Todo RF tiene al menos una parte del plan que lo cubre (y viceversa: nada del plan sobra sin RF).
2. Toda tarea apunta a sus RF y tiene "Hecho cuando:" verificable.
3. Decisiones del plan con alternativa descartada; nada contradice la constitución.
4. Casos límite y fuera de alcance de la spec aparecen en plan o tareas, o se declara por qué no.
Veredicto: APTO (implementar) / APTO CON RESERVAS (lista) / BLOQUEADO (lista + qué falta).
