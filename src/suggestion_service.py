"""Rutina sugerida del día: split activo + historial real (rueda sin saltos).

Reglas (decisión de producto):
- Manda el split: las filas sugeridas son los items del día en orden,
  duplicados incluidos (Press x3 → 3 filas). El historial solo pone valores,
  posicionalmente por ejercicio (serie 1 → última serie 1, sin importar si
  ese día el ejercicio era el 2º o 3º en orden global).
- Si el split pide más series de las hechas la última vez, se replica la
  última serie conocida; si hay más historial, se trunca. Sin historial,
  en blanco.
- El descanso nunca se hereda: la sugerencia trae kg/reps/rir (y
  velocidad/dificultad en HIIT) pero descanso_seg siempre vacío; los
  cronómetros arrancan de cero en cada entreno nuevo.
- La rueda avanza por cobertura de series (>= 2/3 de las series
  programadas): hizo espalda/pecho/tríceps pero faltó bíceps (3/4) → avanza;
  1/2 no avanza; 1/1 exige hacerlo. Descansar un día de descanso avanza;
  entrenar en descanso avanza sin crear deuda.
- No se saltan entrenos, solo se corren los días: si pedía pierna e hiciste
  torso, pierna sigue pendiente.
- Los pesos son siempre del propio ejercicio por su nombre real (pullover
  nunca hereda de jalón).
- Deuda más vieja que LOOKBACK_DAYS se asume saldada (empezar de cero).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from src.database import (
    get_active_split_id,
    get_last_exercise_series,
    get_sets_by_fecha,
    get_split,
)
from src.models import SPLIT_DAYS
from src.training_service import (
    DIA_MAP,
    fecha_display,
    fecha_to_db,
    parse_form_date,
)

LOOKBACK_DAYS = 120

# Cobertura mínima de series para dar un slot por cumplido (2/3):
# n=1→1, n=2→2, n=3→2, n=4→3, n=5→4, n=6→4.
MIN_COVERAGE_RATIO = 2 / 3


@dataclass(frozen=True)
class SuggestedSet:
    ejercicio: str
    kg: float | None = None
    reps: float | None = None
    rir: float | None = None
    descanso_seg: float | None = None
    fuente_fecha: str | None = None
    velocidad_kmh: float | None = None
    dificultad: float | None = None


@dataclass(frozen=True)
class Suggestion:
    """tipo: rutina (con sets) | descanso (aviso) | nada (sin propuesta)."""

    tipo: str
    fecha: str
    split_id: int | None = None
    slot_dia: str | None = None
    ejercicios: list[str] = field(default_factory=list)
    sets: list[SuggestedSet] = field(default_factory=list)
    explicacion: str = ""
    pendiente_desde: str | None = None


def _slot_series(items: list[dict], dia: str) -> list[str]:
    """Series del día del split en orden, duplicados incluidos (1 item = 1 serie)."""
    out: list[str] = []
    for it in items:
        if it.get("dia") != dia:
            continue
        name = str(it.get("ejercicio") or "").strip()
        if not name:
            continue
        out.append(name)
    return out


def _coverage_ratio(slot_series: list[str], rows: list[dict]) -> float:
    """Series del slot cubiertas / programadas (por ejercicio, tope por conteo).

    Un ejercicio cuenta hasta su nº programado: slot Press x3 + Curl x1 con
    Press x1 + Curl x1 entrenados → (1+1)/4 = 0.5. Sin series programadas → 1.0.
    """
    if not slot_series:
        return 1.0
    if not rows:
        return 0.0
    prescribed: dict[str, int] = {}
    for name in slot_series:
        prescribed[name.lower()] = prescribed.get(name.lower(), 0) + 1
    trained: dict[str, int] = {}
    for r in rows:
        t = str(r.get("ejercicio") or "").strip().lower()
        if t:
            trained[t] = trained.get(t, 0) + 1
    matched = sum(min(prescribed[k], trained.get(k, 0)) for k in prescribed)
    return matched / len(slot_series)


def _slot_covered(slot_series: list[str], rows: list[dict]) -> bool:
    """El slot se da por cumplido si cubre la mayoría de sus series."""
    if not slot_series:
        return True
    if not rows:
        return False
    return _coverage_ratio(slot_series, rows) >= MIN_COVERAGE_RATIO


def _split_start(db_path: str, split_id: int) -> date:
    """El plan empieza cuando se crea (created_at) o hace LOOKBACK_DAYS."""
    from src.database import get_split

    try:
        created = (get_split(db_path, split_id) or {}).get("created_at", "")
        start = date.fromisoformat(str(created)[:10])
    except (TypeError, ValueError):
        start = date.today() - timedelta(days=LOOKBACK_DAYS)
    return start


def _has_any_data(db_path: str, fecha_db: str) -> bool:
    from src.database import get_daily_data_dates

    return any(f < fecha_db for f in get_daily_data_dates(db_path, "entrenamiento"))


def resolve_suggestion(db_path: str, fecha_iso: str) -> Suggestion:
    """Calcula la rutina sugerida de un día (sin escribir nada)."""
    fecha = parse_form_date(fecha_iso)
    fecha_db = fecha_to_db(fecha)
    if get_sets_by_fecha(db_path, fecha_db):
        return Suggestion(
            tipo="nada",
            fecha=fecha_db,
            explicacion="El día ya tiene entrenamiento guardado.",
        )
    split_id = get_active_split_id(db_path)
    if split_id is None:
        return _repeat_fallback(db_path, fecha_db)
    split = get_split(db_path, split_id)
    if split is None:
        return _repeat_fallback(db_path, fecha_db)
    items = split["items"]
    by_day = {dia: _slot_series(items, dia) for dia in SPLIT_DAYS}
    if not any(by_day.values()):
        return Suggestion(
            tipo="nada",
            fecha=fecha_db,
            split_id=split_id,
            explicacion="El split activo no tiene días con ejercicios.",
        )
    # Ancla: el plan empieza cuando se crea (created_at) o hace LOOKBACK_DAYS.
    # Simulación con doble regla: entrenar el día de calendario al día
    # re-sincroniza la rueda; si no, manda la rotación (la deuda congela).
    # Si NADA pisa el split en ventana, no se sigue y se repite el día.
    if not _has_any_data(db_path, fecha_db):
        # Sin historial: no hay deuda posible, manda el calendario.
        return _calendar_due(db_path, fecha_db, fecha, split_id, by_day)
    start_limit = fecha - timedelta(days=LOOKBACK_DAYS)
    start = max(_split_start(db_path, split_id), start_limit)
    pointer = list(SPLIT_DAYS).index(DIA_MAP[start.weekday()])
    freezes: list[tuple[str, str]] = []
    matched_ever = False
    overlap_ever = False
    all_slot_ex = set()
    for ex in by_day.values():
        for e in ex:
            all_slot_ex.add(e.lower())
    day = start
    while day < fecha:
        day_db = fecha_to_db(day)
        rows = get_sets_by_fecha(db_path, day_db)
        if rows and any(str(r.get("ejercicio") or "").strip().lower() in all_slot_ex for r in rows):
            overlap_ever = True
        wdia = DIA_MAP[day.weekday()]
        if by_day[wdia] and rows and _slot_covered(by_day[wdia], rows):
            # Al día con el calendario: la rueda se re-sincroniza.
            pointer = (list(SPLIT_DAYS).index(wdia) + 1) % 7
            matched_ever = True
            day += timedelta(days=1)
            continue
        slot = SPLIT_DAYS[pointer]
        slot_ex = by_day[slot]
        if not slot_ex:
            pointer = (pointer + 1) % 7  # descanso observado: avanza
        elif rows and _slot_covered(slot_ex, rows):
            pointer = (pointer + 1) % 7
            matched_ever = True
        else:
            # Vacío o sin cubrir: la deuda sigue (no avanza).
            freezes.append((day_db, slot))
        day += timedelta(days=1)
    if not matched_ever and not overlap_ever and _has_any_data(db_path, fecha_db):
        # Nada de lo entrenado pisa el split: no se sigue; repetir último día.
        return _repeat_fallback(db_path, fecha_db)
    due = SPLIT_DAYS[pointer]
    due_freezes = [f for f, s in freezes if s == due]
    pendiente_desde = max(due_freezes) if due_freezes else None
    return _build_due(db_path, fecha_db, split_id, due, by_day, pendiente_desde)


def _calendar_due(
    db_path: str, fecha_db: str, fecha, split_id: int, by_day: dict[str, list[str]]
) -> Suggestion:
    """Sin historial: manda el día de calendario (primera vez / vuelta tras meses)."""
    due = DIA_MAP[fecha.weekday()]
    return _build_due(db_path, fecha_db, split_id, due, by_day, pendiente_desde=None)


def _build_due(
    db_path: str,
    fecha_db: str,
    split_id: int,
    due: str,
    by_day: dict[str, list[str]],
    pendiente_desde: str | None,
) -> Suggestion:
    due_series = by_day[due]
    if not due_series:
        explicacion = "Según tu split hoy es descanso."
        if pendiente_desde is not None:
            explicacion += " (Venías recuperando un entreno pendiente.)"
        return Suggestion(
            tipo="descanso",
            fecha=fecha_db,
            split_id=split_id,
            slot_dia=due,
            explicacion=explicacion,
            pendiente_desde=pendiente_desde,
        )
    due_ex = _slot_exercises_from_series(due_series)
    # Historial por ejercicio una sola vez; asignación posicional que conserva
    # el orden exacto del split (también intercalados Press/Curl/Press).
    hist_by_ex: dict[str, dict] = {}
    for name in due_series:
        key = name.lower()
        if key not in hist_by_ex:
            hist_by_ex[key] = get_last_exercise_series(db_path, name, before_fecha=fecha_db)
    counters: dict[str, int] = {}
    sets: list[SuggestedSet] = []
    for name in due_series:
        key = name.lower()
        payload = hist_by_ex[key]
        hist = payload["series"]
        fuente = payload["fuente_fecha"]
        counters[key] = counters.get(key, 0) + 1
        idx = counters[key] - 1
        if not hist:
            sets.append(SuggestedSet(ejercicio=name))
        else:
            r = hist[idx] if idx < len(hist) else hist[-1]
            sets.append(
                SuggestedSet(
                    ejercicio=name,
                    kg=r.get("kg"),
                    reps=r.get("reps"),
                    rir=r.get("rir"),
                    descanso_seg=None,
                    fuente_fecha=fuente,
                    velocidad_kmh=r.get("velocidad_kmh"),
                    dificultad=r.get("dificultad"),
                )
            )
    if pendiente_desde is not None:
        explicacion = (
            f"Te tocaba {due.lower()} del {fecha_display(pendiente_desde)} y no se hizo: "
            f"hoy toca {due.lower()}."
        )
    else:
        explicacion = f"Según tu split hoy es {due.lower()}."
    return Suggestion(
        tipo="rutina",
        fecha=fecha_db,
        split_id=split_id,
        slot_dia=due,
        ejercicios=due_ex,
        sets=sets,
        explicacion=explicacion,
        pendiente_desde=pendiente_desde,
    )


def _slot_exercises_from_series(series: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in series:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out


def _repeat_fallback(db_path: str, fecha_db: str) -> Suggestion:
    """Sin split activo: copia 1:1 del último día con datos (tal cual se hizo).

    Los ejercicios se mantienen como se entrenaron (pullover sigue pullover);
    los valores son los de ese día por construcción.
    """
    from src.database import get_daily_data_dates

    with_data = sorted(get_daily_data_dates(db_path, "entrenamiento"))
    prev = [f for f in with_data if f < fecha_db]
    if not prev:
        return Suggestion(
            tipo="nada",
            fecha=fecha_db,
            explicacion="Sin split activo ni historial: elige ejercicios o aplica una plantilla.",
        )
    source = prev[-1]
    rows = get_sets_by_fecha(db_path, source)
    ejercicios: list[str] = []
    seen: set[str] = set()
    for r in rows:
        name = str(r.get("ejercicio") or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            ejercicios.append(name)
    return Suggestion(
        tipo="rutina",
        fecha=fecha_db,
        slot_dia=None,
        ejercicios=ejercicios,
        sets=[
            SuggestedSet(
                ejercicio=str(r.get("ejercicio") or "").strip(),
                kg=r.get("kg"),
                reps=r.get("reps"),
                rir=r.get("rir"),
                descanso_seg=None,
                fuente_fecha=source,
                velocidad_kmh=r.get("velocidad_kmh"),
                dificultad=r.get("dificultad"),
            )
            for r in rows
        ],
        explicacion=f"Sin split activo: repito tu último día ({fecha_display(source)}).",
    )
