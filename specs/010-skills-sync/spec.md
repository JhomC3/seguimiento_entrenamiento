# Spec 010 — Sincronización de skills con el stack (`/skills` + `--sync`)

Constitución: `docs/constitution.md` (principio 1: todo cambio empieza en la spec).
Numeración: 006–009 reservadas a refactors src; refactors de tests pasan a 011+.

## Contexto y objetivo

El instalador SDD es de un solo disparo; el stack evoluciona (nuevas
librerías) y las skills necesarias aparecen después. Hace falta re-escaneo a
demanda con gatillos, sin instalación silenciosa.

## Usuarios

El dueño y cualquier agente bajo `Proyectos/`.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá el comando `/skills`: re-escanea manifiestos (`pyproject.toml`, `package.json`, `build.gradle*`, `requirements*.txt`), reporta stack detectado vs skills instaladas, instala las del kit faltantes tras aprobación y sugiere `autoskills` para librerías de terceros (decisión del dueño, nunca descarga externa sola).
- RF-2: EL SISTEMA dará a `install.sh` modo `--sync`: compara el destino contra el kit actual, instala piezas faltantes y actualiza `sdd-lock.json` del destino.
- RF-3: EL SISTEMA avisará (sin bloquear) en el hook pre-commit cuando el diff toque un manifiesto de dependencias ("considera /skills").
- RF-4: EL SISTEMA añadirá al protocolo la regla: toda spec que añada dependencia incluye su revisión de skills en `tasks.md`.
- RF-5: Gates en verde.

## Requisitos no funcionales

- Cero red en el instalador; instalación de terceros solo vía `autoskills` explícito del dueño.
- Instalación silenciosa prohibida: proponer → confirmar → instalar.

## Casos límite

- Destino ya sincronizado → `--sync` lo declara y no escribe.
- Proyecto con autoskills → `/skills` no pisa nada de terceros, solo reporta.

## Fuera de alcance

Skills nuevas de rol; refactors 006–009.

## Criterios de finalización

- Comando + `--sync` + hook-hint + regla, probados en scratch y dogfooding, gates verdes.

## Dudas abiertas

- Ninguna.
