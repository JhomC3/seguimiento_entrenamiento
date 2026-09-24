---
name: security-audit
description: Audit for secrets, auth, validation, SSRF and CSRF issues with severity
---

## Qué hago
Soy la FUENTE ÚNICA de la checklist de seguridad del kit (el subagente
`security` me referencia, no me duplica).

## Cuándo usarme
Úsame cuando pidan: auditoría de seguridad, vulnerabilidades, ¿esto es seguro?

## Checklist
- Secretos: nada en código, logs, cliente ni git (tokens, claves, DSNs).
- AuthN/AuthZ: token/credencial comparado en tiempo constante; sin auth = sin exposición a red.
- Validación: tipo/forma/rango/relaciones en servidor; nada calculado solo en cliente.
- SSRF: URLs externas solo constantes, nunca derivadas de input.
- CSRF: mutaciones con token + Origin; exenciones solo por igualdad exacta.
- Inventario: sin rutas muertas ni endpoints sin documentar.

## Veredicto
APROBADO / APROBADO CON RESERVAS (lista) / BLOQUEADO (lista + explotación mínima).
