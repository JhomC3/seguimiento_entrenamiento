# Manual operativo: diario de alimentación → Health Connect

> La publicación es automática y silenciosa: no hay botones ni avisos de
> comida. Este manual fija el procedimiento que garantiza coherencia entre el
> diario del servidor y Health Connect (y por tanto Google Fit).

## Regla de oro

**Un día, una superficie, un guardado.** Cada fecha se edita en un solo sitio
(web **o** móvil) hasta sincronizar. Web + móvil sobre el mismo día sin
sincronizar en medio = la última escritura gana y la otra se pierde (diseño
del diario, fuera del alcance de este sync).

## Flujo diario

1. Registra los alimentos del día con sus cantidades (web o móvil).
2. Guarda y comprueba que quedan guardados.
3. Sincroniza (botón "Sincronizar AHORA" o worker periódico). Fin.
4. Si llevas más de ~10 días sin sincronizar, repite el sync hasta que no
   publique nada nuevo (tope: 10 días por ejecución, recientes primero).

## Editar lo ya ingresado

Edita → guarda → sincroniza. Semántica por fila (ID estable `día+posición`):

- Cambiar cantidad o alimento de una fila → se **actualiza** el mismo registro.
- Borrar una fila → **desaparece** su registro.
- Añadir filas → se **crean** registros nuevos.
- Borrar el día → se borra todo lo de esa fecha.
- Nunca duplica: el re-sync del mismo contenido es no-op.

**No reordenar filas.** El editor del diario no ofrece reordenar (solo
añadir/eliminar); si alguna vez fuera posible: borra y re-añade en su sitio.
Reordenar cruzaría contenidos entre registros (totales intactos, fila a fila
cruzado).

## Casos especiales

- **Sin red al guardar (móvil):** queda en cola y sale solo al recuperar red.
  No reingreses nada "por si acaso".
- **Móvil con pendientes + edición web del mismo día:** sincroniza primero el
  móvil (drena la cola) y después edita en web. El pase del sync salta los días
  con pendientes sin drenar para no publicar un estado que se va a pisar.
- **Deshacer (undo):** trátalo como una edición más y sincroniza después.
- **Reinstalar la app:** solo ante errores de versión de base. Antes sincroniza
  una vez (vacía pendientes); después concede permisos de nuevo y sincroniza:
  todo se republica solo.
- **No borrar registros a mano** en Health Connect Toolbox u otras apps: el
  pase no lo detecta (sin permiso de lectura, a propósito) y la divergencia
  persiste hasta la próxima edición del día.

## Verificación ocasional (Toolbox / Fit)

Compara un día: mismos alimentos, cantidades y energía que la web. Cada
registro conserva la fecha del diario; la hora es una ventana técnica de un
minuto alrededor de las 12:00 local (o el momento actual si todavía no son las
12:00). El tipo de comida es "desconocido", por diseño.

| Síntoma | Causa probable | Acción |
|---|---|---|
| No aparece nada nuevo | Sin permiso WRITE / sin LAN / día sin guardar | En ese orden |
| Aparece lo viejo | Falta sync tras editar | Sincroniza |
| Hora "rara" | La hora es técnica, pero la fecha debe ser correcta | Comprueba la fecha; vuelve a sincronizar si no coincide |
| Duplicados reales | Bug: reportar con fecha y alimentos | No borrar a mano en HC |
