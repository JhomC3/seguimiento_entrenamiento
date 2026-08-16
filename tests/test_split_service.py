"""Tests del dominio de splits (validación, upsert, métricas autoritativas)."""

import pytest

from src.database import get_split, init_db, insert_exercise
from src.models import (
    SPLIT_DAYS,
    ConflictError,
    NotFoundError,
    SplitInput,
    SplitItem,
    SplitItemInput,
    ValidationError,
)
from src.split_service import (
    compute_split_metrics,
    delete_split,
    get_split_board,
    save_split,
    split_items_from_form,
)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "gym.db")
    init_db(path)
    insert_exercise(path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(path, "Curl", "Biceps", "TIRON")
    insert_exercise(path, "Sentadilla", "Cuadriceps", "PIERNA")
    return path


def _item(dia="LUNES", item_type="ejercicio", ejercicio="Press"):
    return SplitItemInput(dia=dia, item_type=item_type, ejercicio=ejercicio)


def test_save_split_crea(db):
    result = save_split(
        db,
        SplitInput(nombre="Push Pull Legs", items=[_item(), _item(dia="MARTES", ejercicio="Curl")]),
    )
    assert result.id > 0
    assert result.updated is False
    split = get_split(db, result.id)
    assert split["nombre"] == "Push Pull Legs"
    assert len(split["items"]) == 2


def test_rechaza_nombre_vacio(db):
    with pytest.raises(ValidationError):
        save_split(db, SplitInput(nombre="   ", items=[_item()]))


def test_rechaza_sin_items(db):
    with pytest.raises(ValidationError):
        save_split(db, SplitInput(nombre="Vacio", items=[]))


def test_nombre_duplicado_actualiza(db):
    save_split(db, SplitInput(nombre="Push Pull Legs", items=[_item()]))
    result = save_split(
        db,
        SplitInput(nombre="push pull legs", items=[_item(dia="MARTES", ejercicio="Curl")]),
    )
    assert result.updated is True
    splits = get_split(db, result.id)
    assert splits["nombre"] == "push pull legs"
    assert len(splits["items"]) == 1
    assert splits["items"][0]["dia"] == "MARTES"


def test_nombre_duplicado_con_split_id_ajeno_conflicto(db):
    save_split(db, SplitInput(nombre="Split A", items=[_item()]))
    b = save_split(db, SplitInput(nombre="Split B", items=[_item()]))
    with pytest.raises(ConflictError):
        save_split(db, SplitInput(nombre="Split A", items=[_item()]), split_id=b.id)


def test_editar_renombra_split(db):
    a = save_split(db, SplitInput(nombre="Split A", items=[_item()]))
    result = save_split(
        db,
        SplitInput(nombre="Split A v2", items=[_item(dia="VIERNES", ejercicio="Curl")]),
        split_id=a.id,
    )
    assert result.updated is True
    assert result.nombre == "Split A v2"


def test_ejercicio_repetido_mismo_dia_se_conserva(db):
    result = save_split(
        db,
        SplitInput(
            nombre="Volumen",
            items=[_item(ejercicio="Curl"), _item(ejercicio="Curl"), _item(ejercicio="Curl")],
        ),
    )
    split = get_split(db, result.id)
    curls = [i for i in split["items"] if i["ejercicio"] == "Curl"]
    assert len(curls) == 3
    assert [i["orden"] for i in curls] == [1, 2, 3]


def test_guarda_hiit(db):
    result = save_split(
        db, SplitInput(nombre="Con cardio", items=[_item(item_type="hiit", ejercicio="HIIT")])
    )
    split = get_split(db, result.id)
    assert split["items"][0]["item_type"] == "hiit"
    assert split["items"][0]["grupo_muscular"] == "HIIT"


def test_rechaza_hiit_mal_nombrado(db):
    with pytest.raises(ValidationError):
        save_split(db, SplitInput(nombre="X", items=[_item(item_type="hiit", ejercicio="Cardio")]))


def test_rechaza_ejercicio_inexistente(db):
    with pytest.raises(ValidationError):
        save_split(db, SplitInput(nombre="X", items=[_item(ejercicio="No Existe")]))


def test_rechaza_dia_invalido(db):
    with pytest.raises(ValidationError):
        save_split(db, SplitInput(nombre="X", items=[_item(dia="LUNESSS")]))


def test_conserva_orden_por_dia(db):
    result = save_split(
        db,
        SplitInput(
            nombre="Orden",
            items=[
                _item(dia="LUNES", ejercicio="Press"),
                _item(dia="LUNES", ejercicio="Curl"),
                _item(dia="MARTES", ejercicio="Sentadilla"),
                _item(dia="MARTES", ejercicio="Press"),
            ],
        ),
    )
    split = get_split(db, result.id)
    lunes = [i["orden"] for i in split["items"] if i["dia"] == "LUNES"]
    martes = [i["orden"] for i in split["items"] if i["dia"] == "MARTES"]
    assert lunes == [1, 2]
    assert martes == [1, 2]


def _persisted(items, start=1):
    groups = {"Press": "Pectoral", "Curl": "Biceps", "Sentadilla": "Cuadriceps"}
    return [
        SplitItem(
            id=start + i,
            dia=it.dia,
            orden=i + 1,
            item_type=it.item_type,
            ejercicio=it.ejercicio,
            grupo_muscular="HIIT"
            if it.item_type == "hiit"
            else groups.get(it.ejercicio, "Pectoral"),
        )
        for i, it in enumerate(items)
    ]


def test_metricas_por_dia(db):
    items = [
        _item(dia="LUNES", ejercicio="Press"),
        _item(dia="LUNES", ejercicio="Press"),
        _item(dia="LUNES", item_type="hiit", ejercicio="HIIT"),
        _item(dia="MARTES", ejercicio="Curl"),
    ]
    metrics = compute_split_metrics(_persisted(items))
    assert metrics.total_series == 4
    assert len(metrics.days) == 7
    lunes = next(d for d in metrics.days if d.dia == "LUNES")
    assert lunes.series == 3
    assert lunes.by_exercise == {"Press": 2, "HIIT": 1}
    assert lunes.by_group == {"Pectoral": 2, "HIIT": 1}
    domingo = next(d for d in metrics.days if d.dia == "DOMINGO")
    assert domingo.series == 0
    assert domingo.by_group == {}


def test_metricas_por_grupo_y_ejercicio(db):
    items = [
        _item(dia="LUNES", ejercicio="Press"),
        _item(dia="LUNES", ejercicio="Curl"),
        _item(dia="MARTES", ejercicio="Press"),
    ]
    metrics = compute_split_metrics(_persisted(items))
    assert metrics.by_exercise == {"Press": 2, "Curl": 1}
    assert metrics.by_group == {"Pectoral": 2, "Biceps": 1}


def test_metricas_incluye_dias_vacios(db):
    metrics = compute_split_metrics(_persisted([_item(dia="VIERNES", ejercicio="Press")]))
    assert [d.dia for d in metrics.days] == list(SPLIT_DAYS)
    assert sum(d.series for d in metrics.days) == 1


def test_metricas_vacias(db):
    metrics = compute_split_metrics([])
    assert metrics.total_series == 0
    assert metrics.by_exercise == {}
    assert metrics.by_group == {}
    assert len(metrics.days) == 7
    assert all(d.series == 0 for d in metrics.days)


def test_eliminar_split(db):
    result = save_split(db, SplitInput(nombre="A", items=[_item()]))
    delete_split(db, result.id)
    assert get_split(db, result.id) is None
    with pytest.raises(NotFoundError):
        delete_split(db, result.id)


def test_get_split_board_metrics(db):
    result = save_split(
        db,
        SplitInput(
            nombre="Board", items=[_item(), _item(dia="MARTES", item_type="hiit", ejercicio="HIIT")]
        ),
    )
    board = get_split_board(db, result.id)
    assert board["split"].nombre == "Board"
    assert board["metrics"].total_series == 2


def test_get_split_board_no_existe(db):
    with pytest.raises(NotFoundError):
        get_split_board(db, 999)


def test_split_items_from_form_alinea(db):
    items = split_items_from_form(["LUNES", "MARTES"], ["ejercicio", "hiit"], ["Press", "HIIT"])
    assert len(items) == 2
    assert items[1].item_type == "hiit"
    with pytest.raises(ValidationError):
        split_items_from_form(["LUNES"], ["ejercicio", "hiit"], ["Press", "HIIT"])
