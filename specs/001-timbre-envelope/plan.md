# Plan 001 — Envolvente común de timbres

1. `SessionTone`: nueva `swellFor(phase, pos)` con las constantes de AIRE;
   GLIDE multiplica su ganancia activa por `swell·2`; CUENCO multiplica su
   salida activa por `swell·2`; `airSample` intacto.
2. Tests: envolvente crece/decrece en GLIDE y CUENCO; reescribir el test de
   decaimiento de cuenco (el inhala ya no decae monótono); resto intacto.
3. Puertas Android + APK 0.4.21 + oído del usuario.
