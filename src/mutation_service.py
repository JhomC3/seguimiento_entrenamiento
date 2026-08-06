"""Mutation use cases: snapshot/backup/write/undo-return as one application operation.

Routes must not coordinate backup, snapshots or the undo stack directly. A
failure anywhere in a use case propagates (domain errors or unexpected
persistence errors), the undo entry is only pushed after a successful write,
and the undo stack is only popped after a successful restore.
"""

import logging
from collections import deque

from src.database import (
    backup_db,
    delete_plantilla,
    delete_session_by_fecha,
    get_sets_by_fecha,
    reorder_plantillas,
    restore_entrenos,
    snapshot_entrenos,
)
from src.models import Session, Template, TemplateInput
from src.template_service import edit_template, save_template
from src.training_service import fecha_to_db, parse_form_date, save_session

logger = logging.getLogger("mutations")

UNDO_STACK: deque = deque(maxlen=10)


def clear_undo_stack() -> None:
    UNDO_STACK.clear()


def undo_stack_size() -> int:
    return len(UNDO_STACK)


def _push_sesion(fecha_iso: str, before: list[dict], after: list[dict]) -> None:
    UNDO_STACK.append({"kind": "sesion", "fecha_iso": fecha_iso, "before": before, "after": after})


def _push_entrenos(before: list, after: list) -> None:
    UNDO_STACK.append({"kind": "entrenos", "before": before, "after": after})


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
    _push_sesion(fecha_iso, before, [])


def save_session_with_undo_snapshot(db_path: str, fecha_iso: str, sets) -> Session:
    backup_or_raise(db_path)
    fecha_db = fecha_to_db(parse_form_date(fecha_iso))
    before = get_sets_by_fecha(db_path, fecha_db)
    result = save_session(db_path, fecha_iso, sets)
    after = get_sets_by_fecha(db_path, fecha_db)
    _push_sesion(fecha_iso, before, after)
    return result


def save_template_with_undo_snapshot(db_path: str, template: TemplateInput) -> Template:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    result = save_template(db_path, template)
    _push_entrenos(before, snapshot_entrenos(db_path))
    return result


def edit_template_with_undo_snapshot(
    db_path: str, plantilla_id: int, template: TemplateInput
) -> Template:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    result = edit_template(db_path, plantilla_id, template)
    _push_entrenos(before, snapshot_entrenos(db_path))
    return result


def delete_template_with_undo_snapshot(db_path: str, plantilla_id: int) -> None:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    delete_plantilla(db_path, plantilla_id)
    _push_entrenos(before, snapshot_entrenos(db_path))


def reorder_templates_with_undo_snapshot(db_path: str, ordered_ids: list[int]) -> None:
    before = snapshot_entrenos(db_path)
    backup_or_raise(db_path)
    reorder_plantillas(db_path, ordered_ids)
    _push_entrenos(before, snapshot_entrenos(db_path))


def undo_last_action(db_path: str, fecha: str) -> dict:
    """Restore the last action. The stack is only popped after a successful restore."""
    if not UNDO_STACK:
        return {"kind": "empty"}
    entry = UNDO_STACK[-1]
    backup_or_raise(db_path)
    if entry["kind"] == "sesion":
        fecha_iso = entry["fecha_iso"]
        save_session(db_path, fecha_iso, entry["before"])
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
        UNDO_STACK.pop()
        return {"kind": "sesion", "fecha_iso": fecha_iso, "has_data": has_data}
    restore_entrenos(db_path, entry["before"])
    UNDO_STACK.pop()
    return {"kind": "entrenos"}
