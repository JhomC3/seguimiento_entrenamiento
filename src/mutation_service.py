"""Mutation use cases: snapshot/backup/write/undo-return as one application operation.

Routes must not coordinate backup, snapshots or the undo journal directly. A
failure anywhere in a use case propagates (domain errors or unexpected
persistence errors), the undo entry is only pushed after a successful write,
and the journal entry is only popped after a successful restore.

The undo journal lives in SQLite (v013, table undo_entries): it survives
restarts, is bounded to the newest 10 entries, and each insert/trim runs in
one transaction. Only the server-owned `before`-side snapshot is stored: the
restore path never reads the `after` side.
"""

import json
import logging

from src.database import (
    backup_db,
    delete_parametros_diarios,
    delete_plantilla,
    delete_session_by_fecha,
    get_diario_by_fecha,
    get_parametros_diarios,
    get_sets_by_fecha,
    reorder_plantillas,
    restore_diario_rows,
    restore_entrenos,
    restore_splits,
    save_parametros_diarios,
    snapshot_entrenos,
    snapshot_splits,
)
from src.db_connection import read_connection, transaction
from src.models import Session, SplitInput, Template, TemplateInput
from src.nutrition_service import delete_diary, save_diary
from src.split_service import delete_split as _delete_split
from src.split_service import save_split
from src.template_service import edit_template, save_template
from src.training_service import fecha_to_db, parse_form_date, restore_session_rows, save_session

logger = logging.getLogger("mutations")

MAX_UNDO_ENTRIES = 10


def _journal(db_path: str, kind: str, snapshot: dict) -> None:
    """Inserta una entrada y recorta a las MAX_UNDO_ENTRIES más recientes,
    todo en la misma transacción."""
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO undo_entries (kind, snapshot) VALUES (?, ?)",
            (kind, json.dumps(snapshot)),
        )
        conn.execute(
            """DELETE FROM undo_entries WHERE id NOT IN (
                   SELECT id FROM undo_entries ORDER BY id DESC LIMIT ?
               )""",
            (MAX_UNDO_ENTRIES,),
        )


def _pop_top(db_path: str) -> dict | None:
    """Lee y elimina la entrada más nueva. El pop es posterior al restore:
    si el restore falla, la entrada permanece."""
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id, kind, snapshot FROM undo_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM undo_entries WHERE id = ?", (row[0],))
        return {"kind": row[1], "snapshot": json.loads(row[2])}


def clear_undo_stack(db_path: str | None = None) -> None:
    """Vacía el journal (soporte de tests; sin path no hace nada)."""
    if db_path is None:
        return
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM undo_entries")


def undo_stack_size(db_path: str) -> int:
    with read_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM undo_entries").fetchone()
    return int(row[0]) if row else 0


def _push_sesion(db_path: str, fecha_iso: str, before: list[dict]) -> None:
    _journal(db_path, "sesion", {"fecha_iso": fecha_iso, "before": before})


def _push_alimentacion(
    db_path: str,
    fecha_iso: str,
    before: list[dict],
    *,
    params_before: dict | None = None,
    params_tracked: bool = False,
) -> None:
    _journal(
        db_path,
        "alimentacion",
        {
            "fecha_iso": fecha_iso,
            "before": before,
            "params_before": params_before,
            "params_tracked": params_tracked,
        },
    )


def _push_entrenos(db_path: str, before: list) -> None:
    _journal(db_path, "entrenos", {"before": _rows_to_dicts(before)})


def _rows_to_dicts(rows: list) -> list:
    """Convierte filas sqlite3.Row a dicts planos para serializar en el journal."""
    return [[dict(r) for r in group] for group in rows]


def backup_or_raise(db_path: str) -> None:
    """Backup before destructive writes; a failed backup blocks the write.

    A claimed backup that did not occur is worse than a visible error.
    """
    try:
        backup_db(db_path)
    except Exception:
        logger.exception("No se pudo crear el backup antes de una mutación")
        raise


def delete_session(db_path: str, fecha_iso: str) -> None:
    fecha_db = fecha_to_db(parse_form_date(fecha_iso))
    before = get_sets_by_fecha(db_path, fecha_db)
    backup_or_raise(db_path)
    delete_session_by_fecha(db_path, fecha_db)
    _push_sesion(db_path, fecha_iso, before)


def save_session_with_undo_snapshot(db_path: str, fecha_iso: str, sets) -> Session:
    backup_or_raise(db_path)
    fecha_db = fecha_to_db(parse_form_date(fecha_iso))
    before = get_sets_by_fecha(db_path, fecha_db)
    result = save_session(db_path, fecha_iso, sets)
    _push_sesion(db_path, fecha_iso, before)
    return result


def save_template_with_undo_snapshot(db_path: str, template: TemplateInput) -> Template:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    result = save_template(db_path, template)
    _push_entrenos(db_path, before)
    return result


def edit_template_with_undo_snapshot(
    db_path: str, plantilla_id: int, template: TemplateInput
) -> Template:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    result = edit_template(db_path, plantilla_id, template)
    _push_entrenos(db_path, before)
    return result


def delete_template_with_undo_snapshot(db_path: str, plantilla_id: int) -> None:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    delete_plantilla(db_path, plantilla_id)
    _push_entrenos(db_path, before)


def reorder_templates_with_undo_snapshot(db_path: str, ordered_ids: list[int]) -> None:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    reorder_plantillas(db_path, ordered_ids)
    _push_entrenos(db_path, before)


def save_split_with_undo_snapshot(db_path: str, split_id: int | None, split_input: SplitInput):
    before = snapshot_splits(db_path)
    backup_or_raise(db_path)
    result = save_split(db_path, split_input, split_id)
    _journal(db_path, "splits", {"before": _rows_to_dicts(before)})
    return result


def delete_split_with_undo_snapshot(db_path: str, split_id: int) -> None:
    before = snapshot_splits(db_path)
    backup_or_raise(db_path)
    _delete_split(db_path, split_id)
    _journal(db_path, "splits", {"before": _rows_to_dicts(before)})


def save_diary_with_undo_snapshot(
    db_path: str, fecha_iso: str, entries, parametros: dict | None = None
) -> None:
    before = get_diario_by_fecha(db_path, fecha_iso)
    params_before = get_parametros_diarios(db_path, fecha_iso)
    backup_or_raise(db_path)
    save_diary(db_path, fecha_iso, entries)
    if parametros:
        save_parametros_diarios(db_path, fecha_iso, parametros)
    _push_alimentacion(
        db_path,
        fecha_iso,
        before,
        params_before=params_before,
        params_tracked=bool(parametros),
    )


def delete_diary_with_undo_snapshot(db_path: str, fecha_iso: str) -> None:
    before = get_diario_by_fecha(db_path, fecha_iso)
    backup_or_raise(db_path)
    delete_diary(db_path, fecha_iso)
    _push_alimentacion(db_path, fecha_iso, before)


def undo_last_action(db_path: str, fecha: str) -> dict:
    """Restore the last action. The journal entry is only popped after a
    successful restore (pop y restore no comparten transacción a propósito:
    un fallo del restore conserva la entrada)."""
    entry = _peek_top(db_path)
    if entry is None:
        return {"kind": "empty"}
    backup_or_raise(db_path)
    entry = {"kind": entry["kind"], **entry["snapshot"]}
    if entry["kind"] == "sesion":
        fecha_iso = entry["fecha_iso"]
        restore_session_rows(db_path, fecha_iso, entry["before"])
        restored = get_sets_by_fecha(db_path, fecha_to_db(parse_form_date(fecha_iso)))
        has_data = (
            "1"
            if any(
                str(r.get("ejercicio") or "").strip()
                or any(str(r.get(k) or "").strip() for k in ("kg", "reps", "rir"))
                for r in restored
            )
            else "0"
        )
        _pop_top(db_path)
        return {"kind": "sesion", "fecha_iso": fecha_iso, "has_data": has_data}
    if entry["kind"] == "alimentacion":
        fecha_iso = entry["fecha_iso"]
        restore_diario_rows(db_path, fecha_iso, entry["before"])
        if entry.get("params_tracked"):
            if entry.get("params_before") is None:
                delete_parametros_diarios(db_path, fecha_iso)
            else:
                save_parametros_diarios(db_path, fecha_iso, entry["params_before"])
        restored = get_diario_by_fecha(db_path, fecha_iso)
        has_data = "1" if restored else "0"
        _pop_top(db_path)
        return {"kind": "alimentacion", "fecha_iso": fecha_iso, "has_data": has_data}
    if entry["kind"] == "splits":
        restore_splits(db_path, entry["before"])
        _pop_top(db_path)
        return {"kind": "splits"}
    restore_entrenos(db_path, entry["before"])
    _pop_top(db_path)
    return {"kind": "entrenos"}


def _peek_top(db_path: str) -> dict | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT kind, snapshot FROM undo_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return {"kind": row[0], "snapshot": json.loads(row[1])}
