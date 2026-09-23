# Plan técnico — Spec 003 v2

Plan formal: `/Users/jhomc/.opencode/plan/breathing-ui-dial-v2.md`.

## Estructura de módulos

- `DrawerGlyphView.kt` (nuevo) → glifo de dos líneas + `ChevronView` (RF-4/5).
- `BreathingActivity.kt` → TOP 2 líneas fijas (RF-1/2/3), overlay revisión con
  velo (RF-6), insets nav (RF-7), acordeón (RF-5), INVISIBLE sin GONE (RF-2).
- `DiaryTheme.kt` → solo si falta estilo de cabecera (preferir existentes).

## Modelo de datos

Sin cambios (prefs y planillas intactas).

## Algoritmo / contrato

- `patternLines(): Pair<String,String>` = (`4 · 0 · 6 · 0`, `10:00`/`Libre`);
  se refresca solo al editar/aplicar (nunca por tick) → RF-2.
- Acordeón: cabecera con título+resumen+chevron; un abierto (RF-5).
- Atrás cierra panel antes que pantalla (carry-over 0.4.24).

## Decisiones técnicas

- Overlay en `FrameLayout` con `GONE` (no desplaza: apilado) porque la regla
  INVISIBLE aplica al flujo lineal; alternativa descartada: reservar sitio.
- `ViewCompat.setOnApplyWindowInsetsListener` porque `fitsSystemWindows` solo
  no llega a vistas programáticas; alternativa descartada: margen fijo.
- `DrawerLayout` existente porque ya está verificado en el APK; alternativa
  descartada: panel propio.

## Estrategia de tests

- `BreathingActivityTest`: TOP dos líneas fijas e idéntico en Running;
  glifo existe/invisible en marcha; overlay no mueve al dial; etiqueta nunca
  vacía; acordeón expande/colapsa y resúmenes actualizan; sin resp/rpm.
- Gesto animado y matriz de dispositivo (gestos/3 botones, fuente grande) en
  APK con el dueño (T6).
- Comandos: Gradle desde `android/` con `JAVA_HOME=/opt/homebrew/opt/openjdk@21
  GRADLE_USER_HOME=$W/.gradle ANDROID_HOME=$W/android/sdk`
  (`:app:testDebugUnitTest :app:jacocoTestReport :app:assembleDebug`).
