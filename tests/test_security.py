import re
from html.parser import HTMLParser

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import app as appmod
from src.security import get_csrf_secret, make_csrf_token


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from src.database import init_db, insert_exercise

    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    monkeypatch.setattr(appmod, "DB_PATH", db)
    return TestClient(appmod.app)


def test_nosniff_header(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_referrer_policy_header(client):
    r = client.get("/")
    assert r.headers["referrer-policy"] == "same-origin"


def test_frame_options_header(client):
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"


def _csp_of(response) -> str:
    return response.headers["content-security-policy"]


def _script_src(csp: str) -> str:
    return csp.split("script-src")[1].split(";")[0]


def test_csp_header_present_and_restrictive(client):
    r = client.get("/")
    csp = _csp_of(r)
    nonce = _nonce_of(csp)
    from src.security import build_csp

    assert csp == build_csp(nonce)
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert "form-action 'self'" in csp


def _nonce_of(csp: str) -> str:
    import re as _re

    m = _re.search(r"'nonce-([^']+)'", csp)
    assert m, "la CSP debe incluir un nonce"
    return m.group(1)


def test_csp_has_no_unsafe_inline_in_script_src(client):
    script_src = _script_src(_csp_of(client.get("/")))
    assert "'unsafe-inline'" not in script_src
    assert "'nonce-" in script_src


def test_csp_allows_required_cdn_sources(client):
    r = client.get("/")
    csp = _csp_of(r)
    for src in (
        "https://cdn.tailwindcss.com",
        "https://unpkg.com",
        "https://cdn.jsdelivr.net",
        "https://cdn.plot.ly",
    ):
        assert src in csp


def test_headers_on_mutating_route(client):
    r = client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2099-01-01",
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    from src.security import build_csp

    assert _csp_of(r) == build_csp(_nonce_of(_csp_of(r)))


def test_chart_fragment_carries_response_nonce(authed_client):
    authed_client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2099-01-01",
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    r = authed_client.get("/")
    csp_nonce = _nonce_of(_csp_of(r))
    assert f'<script nonce="{csp_nonce}"' in r.text
    assert "'unsafe-inline'" not in _script_src(_csp_of(r))


def test_static_assets_have_headers(client):
    r = client.get("/static/css/app.css")
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.fixture()
def authed_client(client):
    token = make_csrf_token(get_csrf_secret())
    client.headers.update({"X-CSRF-Token": token})
    return client


def test_mutation_without_token_rejected(client):
    r = client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2099-01-01",
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.status_code == 403


def test_mutation_with_wrong_token_rejected(client):
    client.headers.update({"X-CSRF-Token": "bad-token"})
    r = client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 403


def test_mutation_with_valid_token_accepted(authed_client):
    r = authed_client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2099-01-01",
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.status_code == 200
    assert 'data-ok="1"' in r.text


def test_cross_origin_post_rejected_even_with_token(authed_client):
    authed_client.headers.update({"Origin": "https://evil.example"})
    r = authed_client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 403


def test_same_origin_post_accepted(authed_client):
    authed_client.headers.update({"Origin": "http://testserver"})
    r = authed_client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 200
    assert "Entreno guardado" in r.text


def test_get_does_not_require_token(client):
    r = client.get("/")
    assert r.status_code == 200


def test_index_embeds_csrf_token(client):
    r = client.get("/")
    assert "csrf_token" in r.text


def test_csrf_token_validates_within_window():
    secret = get_csrf_secret()
    token = make_csrf_token(secret)
    from src.security import valid_csrf_token

    assert valid_csrf_token(token, secret)
    assert not valid_csrf_token("1.abc", secret)
    assert not valid_csrf_token("", secret)


# ---------------------------------------------------------------------------
# XSS rendering regressions (Task 1)
# ---------------------------------------------------------------------------

PAYLOAD = "x');alert(1)//<img src=x onerror=alert(2)>"

HANDLER_ATTRS = ("onclick", "onchange", "onsubmit", "onerror", "onload", "oninput", "onkeydown")


class _InertChecker(HTMLParser):
    """Collects element names, attribute names and text nodes from a fragment."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.attributes = []
        self.text_nodes = []

    def handle_starttag(self, tag, attrs):
        self.elements.append(tag)
        self.attributes.extend(name for name, _ in attrs)

    def handle_data(self, data):
        self.text_nodes.append(data)


def _assert_inert_fragment(text: str):
    """Hostile names must be inert text: no handlers, no raw payload markup."""
    assert "<img" not in text, "payload <img> must not be raw HTML"
    assert "&lt;img" in text, "payload must be present in escaped text form"
    assert "alert(1)//" in text, "payload must be visible as escaped text"
    parser = _InertChecker()
    parser.feed(text)
    assert not any(name in HANDLER_ATTRS for name in parser.attributes), (
        "no event-handler attributes allowed"
    )
    assert "img" not in parser.elements, "payload must not create an <img> element"
    for m in re.finditer(r"<script([^>]*)>(.*?)</script>", text, re.DOTALL):
        if 'type="application/json"' in m.group(1):
            continue  # data block, never executed
        assert "alert(" not in m.group(2), "payload must not live inside a script element"
    joined = "".join(parser.text_nodes)
    assert PAYLOAD in joined, "payload must be recoverable from the escaped text"


def test_hostile_exercise_notice_is_escaped(authed_client):
    r = authed_client.post(
        "/ejercicio/nuevo",
        data={"ejercicio": PAYLOAD, "grupo_muscular": "Pectoral", "categoria": "EMPUJE"},
    )
    assert r.status_code == 200
    _assert_inert_fragment(r.text)


def test_hostile_template_renders_inert(authed_client):
    r = authed_client.post("/plantilla/guardar", data={"nombre": PAYLOAD, "ejercicio": ["Press"]})
    assert r.status_code == 200
    _assert_inert_fragment(r.text)
    r = authed_client.get("/plantillas")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)


def test_hostile_exercise_in_lists_renders_inert(authed_client):
    authed_client.post(
        "/ejercicio/nuevo",
        data={"ejercicio": PAYLOAD, "grupo_muscular": "Pectoral", "categoria": "EMPUJE"},
    )
    r = authed_client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2099-01-01",
            "ejercicio": [PAYLOAD],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.status_code == 200
    r = authed_client.get("/select")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)
    r = authed_client.get("/")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)


def _minimal_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
        }
    )


def test_oob_notice_renders_hostile_message_escaped():
    from app import templates
    from src.response_fragments import notice_oob

    frag = notice_oob(templates, _minimal_request(), target="editor-notice", message=PAYLOAD)
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in frag
    assert "<img" not in frag
    assert "&lt;img" in frag
    parser = _InertChecker()
    parser.feed(frag)
    assert parser.elements == ["div", "div"]
    assert not any(name in HANDLER_ATTRS for name in parser.attributes)
    assert PAYLOAD in "".join(parser.text_nodes)


def test_oob_notice_rejects_unknown_target():
    from app import templates
    from src.response_fragments import notice_oob

    with pytest.raises(ValueError):
        notice_oob(
            templates, _minimal_request(), target="<img src=x onerror=alert(1)>", message="x"
        )
    with pytest.raises(ValueError):
        notice_oob(templates, _minimal_request(), target="unified-chart", message="x")


def test_app_source_does_not_interpolate_user_fields_into_html():
    """Regression tripwire: user fields must not appear inside f-string HTML in app.py."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "app.py").read_text()
    user_fields = ("ejercicio", "nombre", "error", "message", "msg")
    for line in source.splitlines():
        html_like = "<" in line or ">" in line
        if (
            ("f'" in line or 'f"' in line)
            and any(f"{{{f}}}" in line for f in user_fields)
            and html_like
        ):
            raise AssertionError(
                f"app.py interpola campo de usuario en f-string HTML: {line.strip()}"
            )


def test_edit_template_leak_returns_500_generic(authed_client, monkeypatch):
    """Unexpected persistence errors must never leak their message."""
    import sqlite3

    def _leaky(*args, **kwargs):
        raise sqlite3.OperationalError("SECRET_INTERNAL_DETAIL")

    authed_client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    monkeypatch.setattr("src.mutation_service.edit_template", _leaky)
    r = authed_client.post("/plantilla/editar/1", data={"nombre": "B", "ejercicio": ["Press"]})
    assert r.status_code == 500
    assert "Ocurrió un error inesperado" in r.text
    assert "SECRET_INTERNAL_DETAIL" not in r.text


def test_edit_template_domain_error_keeps_form_with_safe_message(authed_client):
    authed_client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    authed_client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    r = authed_client.post("/plantilla/editar/2", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 200
    assert "Ya existe un entreno llamado" in r.text
    assert 'id="plantilla-edit-rows"' in r.text


def test_chart_fragment_never_contains_raw_script_terminator():
    """Tripwire: plotly must JSON-escape </script> inside chart payloads."""
    import tempfile

    from src.dashboard_service import chart_html
    from src.database import init_db, insert_exercise
    from src.models import TrainingSetInput
    from src.training_service import save_session

    db = tempfile.mktemp(suffix=".db")
    try:
        init_db(db)
        hostile = "x</script><script>alert(1)</script>y"
        insert_exercise(db, hostile, "Pectoral", "EMPUJE")
        save_session(db, "2026-02-10", [TrainingSetInput(ejercicio=hostile, kg=80, reps=8, rir=1)])
        html = chart_html(db, "exercise", hostile, f"Rendimiento – {hostile}", nonce="test-nonce")
        assert 'class="text-[11px] text-neutral-500 flex-none">Ciclo 1<' in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html  # título escapado en el h3
        assert "<script>alert(1)</script>" not in html  # nunca crudo en el documento
        assert '<script nonce="test-nonce"' in html
        body = html.split("<script")[1].split("</script>")[0]
        assert "</script>" not in body
        assert "<script" not in body.split(">", 1)[1]
    finally:
        import os

        os.unlink(db)
