"""Tests for scripts/check_file_size.py (fixtures via tmp_path, no repo writes)."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_file_size.py"


def make_tree(root: Path, files: dict[str, int]) -> None:
    for rel, nlines in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n" * nlines, encoding="utf-8")


def run_gate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )


def test_sano_pasa(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/ok.py": 100})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 0


def test_aviso_no_bloquea(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/med.py": 600})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 0
    assert "aviso" in r.stderr


def test_bloqueo_nuevo(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/big.py": 801})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 1
    assert "src/big.py" in r.stderr


def test_allowlist_con_holgura(tmp_path: Path) -> None:
    make_tree(tmp_path, {"app.py": 2800})  # pineado 2748 +5% = 2885
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 0


def test_allowlist_fuera_de_holgura(tmp_path: Path) -> None:
    make_tree(tmp_path, {"app.py": 2900})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 1


def test_fuera_de_allowlist_falla(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/nuevo_gigante.py": 900})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 1


def test_e2e_excluido(tmp_path: Path) -> None:
    make_tree(tmp_path, {"tests/e2e/test_flujo.py": 4000})
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 0


def test_comentarios_y_blancos_no_cuentan(tmp_path: Path) -> None:
    p = tmp_path / "src" / "doc.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# comentario\n\n   \nx = 1\n# otro\n", encoding="utf-8")
    r = run_gate(tmp_path, "--base", "HEAD")
    assert r.returncode == 0
    assert "tamaño OK" in r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
