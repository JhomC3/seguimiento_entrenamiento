import re
from html.parser import HTMLParser

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import app as appmod
from src.security import get_csrf_secret, make_csrf_token


def _run(coro):
    """Ejecuta una corrutina en un event loop de un hilo propio (sin asyncio.run()).

    Los tests e2e (Playwright sync) dejan un event loop en marcha en el hilo
    principal, y en CPython ningún loop puede correr mientras haya otro en el
    mismo hilo (ni asyncio.run() ni run_until_complete): estos tests deben
    funcionar en cualquier orden de ejecución de pytest.
    """
    import asyncio
    import threading

    outcome = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            outcome["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 - propagar también CancelledError
            outcome["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


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
    from src.security import CSP

    assert csp == CSP
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert "form-action 'self'" in csp


def test_csp_has_no_inline_script_escape_hatch(client):
    script_src = _script_src(_csp_of(client.get("/")))
    assert "'unsafe-inline'" not in script_src
    assert "'nonce-" not in script_src


def test_csp_allows_required_cdn_sources(client):
    r = client.get("/")
    csp = _csp_of(r)
    for src in (
        "https://unpkg.com",
        "https://cdn.jsdelivr.net",
        "https://cdn.plot.ly",
    ):
        assert src in csp
    assert "cdn.tailwindcss.com" not in csp


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
    from src.security import CSP

    assert _csp_of(r) == CSP


def test_chart_fragment_has_no_executable_script(authed_client):
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
    body = r.text
    assert 'id="analysis-chart-data" type="application/json"' in body
    assert '<div id="analysis-chart-plot"' in body
    # Ningún script de la página es inline ejecutable: o es externo (src=) o es de datos.
    for m in re.finditer(r"<script[^>]*>", body):
        tag = m.group(0)
        assert "src=" in tag or 'type="application/json"' in tag, tag


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


@pytest.mark.parametrize(
    ("origin", "host_header"),
    [
        ("http://127.0.0.1:8000", "127.0.0.1:8000"),
        ("http://localhost:8000", "localhost:8000"),
        ("http://192.168.1.6:8000", "192.168.1.6:8000"),
        ("http://[::1]:8000", "[::1]:8000"),
        ("http://localhost", "localhost"),
    ],
)
def test_same_origin_matches_host_header_with_wildcard_bind(origin, host_header):
    """El Origin se valida contra el Host header real del cliente, no contra la
    dirección de bind del socket (uvicorn: scope['server'] == ('0.0.0.0', 8000))."""
    from src.security import _same_origin

    assert _same_origin(origin, "http", host_header, ("0.0.0.0", 8000))


def test_same_origin_rejects_mismatch_and_null():
    from src.security import _same_origin

    assert not _same_origin("https://evil.example", "http", "127.0.0.1:8000", ("0.0.0.0", 8000))
    assert not _same_origin("null", "http", "127.0.0.1:8000", ("0.0.0.0", 8000))


def test_same_origin_falls_back_to_scope_server_without_host_header():
    """Sin Host header (HTTP/1.0) se conserva el comportamiento previo."""
    from src.security import _same_origin

    assert _same_origin("http://0.0.0.0:8000", "http", None, ("0.0.0.0", 8000))
    assert _same_origin("http://127.0.0.1:8000", "http", None, ("127.0.0.1", 8000))
    assert not _same_origin("http://evil.example", "http", None, ("127.0.0.1", 8000))
    assert not _same_origin("http://127.0.0.1:8000", "http", None, None)


def test_middleware_accepts_origin_matching_host_with_wildcard_bind():
    """Reproduce el escenario uvicorn --host 0.0.0.0 + acceso por 127.0.0.1:
    Origin == Host header pasa aunque scope['server'] sea la dirección de bind."""

    from src.security import CSRFProtectionMiddleware, get_csrf_secret, make_csrf_token

    called = []

    async def inner_app(scope, receive, send):
        called.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run_scope(scope) -> int:
        status = {}

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        middleware = CSRFProtectionMiddleware(inner_app)
        await middleware(scope, receive, send)
        return status.get("code", 0)

    base = {
        "type": "http",
        "method": "POST",
        "path": "/entrenamiento/session/save",
        "raw_path": b"/entrenamiento/session/save",
        "query_string": b"",
        "scheme": "http",
        "server": ("0.0.0.0", 8000),
        "client": ("127.0.0.1", 1234),
    }
    token = make_csrf_token(get_csrf_secret())
    ok_headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"origin", b"http://127.0.0.1:8000"),
        (b"x-csrf-token", token.encode()),
    ]
    assert _run(run_scope({**base, "headers": ok_headers})) == 200
    assert called == ["/entrenamiento/session/save"]

    evil_headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"origin", b"https://evil.example"),
        (b"x-csrf-token", token.encode()),
    ]
    assert _run(run_scope({**base, "headers": evil_headers})) == 403
    assert called == ["/entrenamiento/session/save"]

    no_token_headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"origin", b"http://127.0.0.1:8000"),
    ]
    assert _run(run_scope({**base, "headers": no_token_headers})) == 403
    assert called == ["/entrenamiento/session/save"]


def test_middleware_logs_rejection_reason(caplog):
    """El rechazo CSRF se registra en el log del servidor con la causa (origin/token)."""
    import logging

    from src.security import CSRFProtectionMiddleware

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run_scope(scope) -> int:
        status = {}

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        await CSRFProtectionMiddleware(inner_app)(scope, receive, send)
        return status.get("code", 0)

    base = {
        "type": "http",
        "method": "POST",
        "path": "/alimentacion/save",
        "raw_path": b"/alimentacion/save",
        "query_string": b"",
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 1234),
    }
    with caplog.at_level(logging.WARNING, logger="security"):
        assert (
            _run(
                run_scope(
                    {
                        **base,
                        "headers": [
                            (b"host", b"127.0.0.1:8000"),
                            (b"origin", b"https://evil.example"),
                            (b"x-csrf-token", b"x"),
                        ],
                    }
                )
            )
            == 403
        )
        _run(
            run_scope(
                {
                    **base,
                    "headers": [
                        (b"host", b"127.0.0.1:8000"),
                        (b"origin", b"http://127.0.0.1:8000"),
                    ],
                }
            )
        )
    origin_line = [r for r in caplog.records if "CSRF reject (origin)" in r.message]
    token_line = [r for r in caplog.records if "CSRF reject (token)" in r.message]
    assert origin_line and "https://evil.example" in origin_line[0].message
    assert token_line and "present=False" in token_line[0].message


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


def test_csrf_window_configurable(monkeypatch):
    import importlib

    monkeypatch.setenv("GYM_CSRF_WINDOW_HOURS", "1")
    import src.security as sec

    importlib.reload(sec)
    try:
        assert sec.CSRF_WINDOW_SECONDS == 3600
    finally:
        monkeypatch.delenv("GYM_CSRF_WINDOW_HOURS", raising=False)
        importlib.reload(sec)
        assert sec.CSRF_WINDOW_SECONDS == 24 * 7 * 3600


def test_csrf_token_fuera_de_ventana(monkeypatch):
    import src.security as sec
    from src.security import valid_csrf_token

    monkeypatch.setattr(sec.time, "time", lambda: 1_000_000)
    token = make_csrf_token(get_csrf_secret())
    monkeypatch.setattr(sec.time, "time", lambda: 1_000_000 + sec.CSRF_WINDOW_SECONDS + 1)
    assert not valid_csrf_token(token, get_csrf_secret())


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
    # El payload aparece escapado: como HTML (&lt;img) o como JSON (\u003cimg).
    assert ("&lt;img" in text) or ("\\u003cimg" in text), (
        "payload must be present in escaped text form"
    )
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
    # El payload es recuperable escapado: como nodo de texto contiguo, como
    # valor de atributo (datalist) o dentro del JSON inerte (#app-config);
    # nunca como HTML crudo.
    escaped_attr = PAYLOAD.replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
    escaped_json = PAYLOAD.replace("<", "\\u003c").replace(">", "\\u003e").replace("'", "\\u0027")
    assert (PAYLOAD in joined) or (escaped_attr in text) or (escaped_json in text), (
        "payload must be recoverable in escaped form"
    )


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
    r = authed_client.get("/analisis/chart?nivel=ejercicio&rango=8")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)
    # En el datalist el payload viaja escapado como valor de atributo.
    assert 'value="x&#39;);alert(1)//&lt;img src=x onerror=alert(2)&gt;"' in r.text
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


def test_json_for_inline_escapes_hostile_values():
    """_json_for_inline debe neutralizar </script> sin romper el round-trip."""
    import json

    from src.dashboard_service import _json_for_inline

    hostile = '{"name": "x</script><script>alert(1)</script>y", "apost": "it\'s"}'
    escaped = _json_for_inline(hostile)
    assert "<script>" not in escaped and "</script>" not in escaped
    assert json.loads(escaped) == {"name": "x</script><script>alert(1)</script>y", "apost": "it's"}


def test_chart_fragment_never_contains_raw_script_terminator():
    """Tripwire: la figura viaja como JSON escapado dentro de un script de datos.

    El fragmento no puede contener scripts ejecutables ni </script> crudo en el
    JSON: el nombre hostil del ejercicio no puede cerrar el elemento."
    """
    import json
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
        html = chart_html(db, "exercise", hostile, f"Rendimiento – {hostile}")
        assert 'class="text-[11px] text-neutral-500 flex-none">Ciclo 1<' in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html  # título escapado en el h3
        assert "<script>alert(1)</script>" not in html  # nunca crudo en el documento
        # El único <script> es el de datos; su contenido no cierra el elemento.
        for m in re.finditer(r"<script[^>]*>", html):
            assert 'type="application/json"' in m.group(0)
        data = re.search(
            r'<script id="unified-chart-data" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert data, "el fragmento debe incluir la figura JSON"
        assert "<" not in data.group(1) and ">" not in data.group(1)
        fig = json.loads(data.group(1))
        assert fig["data"]  # la figura es parseable e íntegra
    finally:
        import os

        os.unlink(db)


SYNC_PATH = "/sync/health-connect"


def test_sync_path_bypasses_csrf_exactly(client):
    """El endpoint API con credencial propia no debe caer bajo el CSRF htmx.

    En esta fase la ruta aún no existe: un 404/503 demuestra que el middleware
    CSRF no lo bloqueó (403). El contrato de credencial propia se prueba en
    Task 3.3.
    """
    r = client.post(SYNC_PATH, json={})
    assert r.status_code != 403


def test_sync_prefix_paths_still_csrf_protected(client):
    """El bypass es por igualdad exacta de ruta, nunca por prefijo."""
    r = client.post("/sync/other", json={})
    assert r.status_code == 403


def test_other_mutations_still_require_csrf(client):
    """El resto de rutas mutantes del dashboard conservan el CSRF intacto."""
    r = client.post("/entrenamiento/session/save", data={})
    assert r.status_code == 403
