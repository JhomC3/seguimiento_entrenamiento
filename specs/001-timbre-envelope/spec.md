# Spec 001 — Envolvente común de timbres (respiración)

## Contexto y objetivo

AIRE gusta y queda congelado. GLIDE suena plano (ganancia fija) y CUENCO
decae siempre igual sin acompañar la fase. Los tres deben respirar igual:
crecer al inhalar, menguar al exhalar, tenue en sostenes. Cada uno mantiene
su sonido (glide = glide de frecuencia + armónico; cuenco = tañidos con
caída y ahogo; aire = ruido rosa). Solo cambia la forma de la envolvente.

## Requisitos funcionales (EARS)

- RF-1: CUANDO el estilo sea GLIDE e INHALE avance de 0 a 1, EL SISTEMA
  aumentará la ganancia con la misma curva de AIRE (`0.15+0.70·pos`,
  normalizada a media 1.0); CUANDO sea EXHALE, la disminuirá (`0.85−0.70·pos`).
- RF-2: CUANDO el estilo sea CUENCO en fase activa, EL SISTEMA multiplicará
  la salida por la misma curva normalizada, sin tocar ataque, caída,
  ahogo ni mezcla de armónicos.
- RF-2b: CUANDO el estilo sea CUENCO e INHALE, EL SISTEMA usará ataque
  lento (45 % de la fase: el tañido florece tarde, cuando la envolvente
  está alta) y ganancia 1.2 para que el pico iguale al de EXHALE
  (ataque rápido 12 %, ganancia 0.5: nace arriba y cae).
- RF-2c (triángulo /\/\): CUANDO el estilo sea CUENCO, EL SISTEMA usará
  caída `tau` = duración completa (sin tope de 2000 ms) para que la
  envolvente —no la caída propia— dibuje el triángulo: INHALE termina
  arriba donde EXHALE empieza, EXHALE termina abajo donde INHALE empieza.
  El silencio REST entre fases se conserva.
- RF-3: EL SISTEMA no modificará `airSample` (AIRE suena byte-idéntico).
- RF-4: EL SISTEMA mantendrá duraciones exactas, REST en ceros exactos,
  fundidos de borde y determinismo por semilla.

## Fuera de alcance

Entrega de audio (`StaticPhasePlayer`), tiempos, persistencia, servidor,
contrato B5. Ningún cambio Python.

## Criterios de finalización

- Tests de envolvente por estilo en verde + oído del usuario por estilo.
- APK 0.4.21. Sin commits sin revisión manual del diff.
