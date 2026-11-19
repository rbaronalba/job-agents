"""Fixtures compartidas. Solo montan entornos: la lógica de apoyo vive en src/testing/ y los asserts en los tests."""
import os
from pathlib import Path

import pytest

from . import db
from .diario import Diario
from .testing.entorno import CliEnProceso, Sandbox, args_diario


@pytest.fixture
def sandbox(tmp_path):
    """Datos de prueba, perfil con cupos fijos, histórico sintético y `claude` falso, todo en una carpeta temporal."""
    return Sandbox(tmp_path)


@pytest.fixture(scope="module")
def sandbox_del_modulo(tmp_path_factory):
    """Como `sandbox`, pero compartido por todos los tests del módulo (para ejecuciones caras que solo se leen)."""
    return Sandbox(tmp_path_factory.mktemp("modulo"))


@pytest.fixture
def crear_diario(sandbox, monkeypatch):
    """Fábrica de `Diario` en proceso: con el `claude` falso en el PATH y sus carpetas de datos y logs en la temporal."""
    monkeypatch.setenv("PATH", f"{sandbox.falso}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("JOB_AGENTS_PERFIL", str(sandbox.perfil))
    monkeypatch.setenv("FALSO_LLAMADAS", str(sandbox.registro))
    monkeypatch.setattr(db, "DATOS_PRUEBA", sandbox.datos)
    monkeypatch.setattr(db, "LOGS_REAL", sandbox.logs)
    return lambda **kw: Diario(args_diario(sandbox.base, **kw))


@pytest.fixture
def con():
    """Histórico en memoria."""
    return db.conectar(Path(":memory:"))


@pytest.fixture
def carpeta_excel(tmp_path, monkeypatch):
    """El Excel de ofertas se escribe en una carpeta temporal."""
    from . import excel
    monkeypatch.setattr(excel, "CARPETA", tmp_path / "ofertas")
    return tmp_path / "ofertas"


@pytest.fixture
def cli(sandbox, monkeypatch):
    """`src.cli` en proceso sobre la base sintética, con datos, logs, perfil y raíz en la carpeta temporal."""
    return CliEnProceso(monkeypatch, sandbox)


@pytest.fixture
def cli_prueba(sandbox, monkeypatch):
    """Lo mismo, en modo prueba (nunca envía)."""
    return CliEnProceso(monkeypatch, sandbox, prueba=True)
