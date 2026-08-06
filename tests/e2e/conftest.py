import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.database import init_db, insert_exercise

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_MODULE = "app:app"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            last_error = e
            time.sleep(0.1)
    raise RuntimeError(f"Servidor no respondió en {timeout}s: {last_error}")


@pytest.fixture()
def server(tmp_path):
    db_path = tmp_path / "gym.db"
    init_db(str(db_path))
    insert_exercise(str(db_path), "Press", "Pectoral", "EMPUJE")

    port = _free_port()
    env = dict(os.environ)
    env["GYM_DB_PATH"] = str(db_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", APP_MODULE, "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url + "/")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture()
def page(browser, server):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
