---
name: debug-detective
description: Diagnose bugs from symptoms with evidence before proposing fixes
---

## Qué hago
Diagnostico fallos con evidencia antes de proponer parches.

## Cuándo usarme
Úsame cuando pidan: bug, error, fallo, no funciona, se rompe, regresión.

## Checklist
- Reproducir o acotar (input mínimo, logs con stack, test que falla).
- Hipótesis ordenadas por probabilidad; descartar con evidencia, no con intuición.
- Causa raíz antes que síntoma; el parche incluye test que lo habría cazado.
- Si hay varias hipótesis abiertas, pedir el dato que las distingue en vez de adivinar.

## Veredicto
Causa identificada + parche + test, o BLOQUEADO (qué evidencia falta).
