# Plan técnico — Spec 011 (solo kit + esta spec)

## `sdd-kit/README.md` (RF-1, RF-2)

Puerta de entrada + sección de actualización (versiones, revisión mensual).
Puntero único al protocolo; cero duplicación de contenido.

## Comando `/skills` (RF-3)

Añade paso 0: comparar `VERSION` del kit contra `sdd-lock.json` del proyecto
e informar "kit X disponible, instalado Y" antes del re-escaneo.

## Versión (RF-4)

Kit v0.5.0 + `sdd-lock.json` regenerado + commit en repo del kit.
