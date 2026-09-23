# Spec 003 — Pantalla respiración: popup editor + etiquetas (v5)

## Contexto y objetivo

El dueño corrigió la 0.4.28: etiquetas más apagadas que los números (al
revés), barra al lado del glifo en vez de debajo (mockup), rueda inline que
mueve el dial (prohibido por regla propia) y transición inhalar↔exhalar
áspera. Esta v5: etiquetas al mismo brillo, barra debajo del glifo, rueda en
popup con blur y fundidos de borde más largos. Sin cambios de tiempos,
persistencia, servidor ni contrato.

## Usuarios / actores

Dueño único, en el móvil, pestaña Respirar.

## Historias de usuario

- H1: Como dueño quiero etiquetas y números al mismo brillo, jerarquía solo
  por tamaño/peso.
- H2: Como dueño quiero la barra debajo del glifo, como el mockup.
- H3: Como dueño quiero la rueda en popup con blur, sin que el dial se mueva.
- H4: Como dueño quiero el cambio inhalar↔exhalar suave, sin corte seco.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA mostrará etiquetas y valores de la barra en `neutral_100`
  (etiquetas 13sp bold, valores 19sp normal; abierta: `burgundy_400`), con
  aire (padding generoso, sin apeñuscar).
- RF-2: EL SISTEMA mostrará el glifo arriba a la izquierda y la barra a
  ancho completo debajo. Columna Tiempo rotulada `Min` (valor `10`/`Libre`).
- RF-3: CUANDO el usuario toque una columna en reposo, EL SISTEMA abrirá un
  popup sin tarjeta ni título (ruedas grandes ×1.25 flotando sobre glass:
  doble blur + desaturado + dim fuerte (el fondo es casi negro: el blur solo
  texturiza); décimas en dígitos pelados; fila ✕ izquierda, ✓ derecha, en
  texto con la misma instancia de fuente); misma validación (duración `0:00`
  = Libre con toast, sin botón Libre).
  El dial no se moverá. Tocar fuera o ✕ cierra; ✓ aplica.
- RF-4: MIENTRAS haya sesión, las columnas NO expandirán (vigente).
- RF-5: EL SISTEMA usará fundidos de borde de 400 ms (antes 250 ms) en los
  buffers de fase; duraciones exactas, REST y envolventes intactos.
- RF-6: 5 columnas con formatos fijos, panel Sonido + Plantillas (fondo
  negro puro, acordeones independientes; Sonido = 3 timbres directos sin
  diálogo, con sonido siempre y vibración nunca; cabeceras 18sp bold
  `neutral_100`, opciones 15sp `neutral_300`), cero saltos en estados, glass
  de revisión (resumen corto; Descartar|Guardar idénticos en horizontal),
  keep-screen, gesto global, glifo. Sin resp/rpm.

## Requisitos no funcionales

- El popup comparte velo/estilo con la revisión (un solo lenguaje glass).

## Casos límite

- Popup abierto + inicio de sesión: se cierra (como el inline).
- Pre-API 31: velo dim (vigente).

## Decisiones conscientes (deber de criterio)

- D1/D5/D6–D8 (v2–v4, vigentes).
- D9: popup en vez de inline (orden explícita del dueño; la inline fue mala
  decisión técnica mía contra la regla de cero saltos).
- D10: fundidos 400 ms (una variable; el oído del dueño decide; tiempos
  exactos intactos).
- D11: `Min` + dígitos pelados + popup sin tarjeta/título + botones mismo
  color apilados (Listo abajo) + blur total (órdenes explícitas del dueño).
- D12: ✕/✓ en texto con la MISMA instancia de typeface (misma fuente
  garantizada; fila y tamaños intactos) + panel negro puro (fuera de tokens
  a propósito) + acordeones independientes + Ajustes solo-timbre con sonido
  siempre y vibración nunca.
- D13: acordeón Sonido con timbres directos (diálogo eliminado por inútil) +
  títulos 18sp bold `neutral_100` sobre opciones 15sp `neutral_300`.
- D14: botón Libre eliminado (nunca pedido); `0:00` = Libre con toast.
- D15: revisión Descartar|Guardar idénticos en horizontal.
