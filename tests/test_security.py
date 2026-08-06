import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.security import CSP, get_csrf_secret, make_csrf_token


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


def test_csp_header_present_and_restrictive(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert csp == CSP
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert "form-action 'self'" in csp


def test_csp_allows_required_cdn_sources(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
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
    assert r.headers["content-security-policy"] == CSP


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
    assert not any(name in HANDLER_ATTRS for name in parser.attributes), "no event-handler attributes allowed"
    assert "img" not in parser.elements, "payload must not create an <img> element"
    for m in re.finditer(r"<script([^>]*)>(.*?)</script>", text, re.S):
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
        data={"fecha": "2099-01-01", "ejercicio": [PAYLOAD], "kg": ["80"], "reps": ["8"], "rir": ["1"]},
    )
    assert r.status_code == 200
    r = authed_client.get("/select")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)
    r = authed_client.get("/")
    assert r.status_code == 200
    _assert_inert_fragment(r.text)
