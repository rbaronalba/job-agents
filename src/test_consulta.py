"""`espontaneas-consulta`: solo lectura, coincidencias en el Excel y errores explícitos.  python -m pytest src/test_consulta.py"""
import json

import pytest

from .testing.entorno import archivos_consulta, sello


@pytest.fixture
def a(tmp_path):
    return archivos_consulta(tmp_path)


def consultar(sandbox, a, *args):
    return sandbox.json("espontaneas-consulta", "--csv", str(a.csv), *args, base=False)


def test_resumen_del_csv_sin_excel(sandbox, a):
    r = consultar(sandbox, a)
    assert r["csv"] == {"ruta": str(a.csv), "filas": 5, "por_estado": {"": 1, "borrador": 1, "enviada": 2, "pendiente": 1},
                        "hoy": {"enviada": 1, "borrador": 1, "total": 2}}
    assert "candidaturas" not in r


def test_empresa_coincide_sin_sufijo_legal_y_en_mayusculas(sandbox, a):
    c = consultar(sandbox, a, "--empresa", "ACME SOFTWARE", "--excel", str(a.xlsx))["candidaturas"]
    assert c["contactada"] is True and c["filas"] == 3
    assert c["coincidencias"][0]["fila"] == 2 and c["coincidencias"][0]["motivo"] == "empresa"
    assert c["coincidencias"][0]["fecha"].startswith("2026-10-01")


def test_dominio_coincide_en_las_notas(sandbox, a):
    c = consultar(sandbox, a, "--dominio", "www.beta.io", "--excel", str(a.xlsx))["candidaturas"]
    assert len(c["coincidencias"]) == 1
    assert c["coincidencias"][0]["fila"] == 3 and c["coincidencias"][0]["motivo"] == "dominio"


def test_sin_coincidencias_no_esta_contactada(sandbox, a):
    c = consultar(sandbox, a, "--empresa", "Gamma", "--dominio", "gamma.com", "--excel", str(a.xlsx))["candidaturas"]
    assert c["contactada"] is False and c["coincidencias"] == []


def test_un_nombre_corto_no_coincide_por_contencion(sandbox, a):
    assert consultar(sandbox, a, "--empresa", "Ac", "--excel", str(a.xlsx))["candidaturas"]["coincidencias"] == []


def test_sin_candidaturas_sync_se_dice_en_vez_de_inventar_un_cero(sandbox, a):
    assert consultar(sandbox, a, "--empresa", "Acme")["candidaturas"] == {"configurado": False}


def test_la_salida_es_estable_y_de_una_sola_linea(sandbox, a):
    args = ("espontaneas-consulta", "--csv", str(a.csv), "--empresa", "Acme", "--excel", str(a.xlsx))
    primera, segunda = sandbox.cli(*args, base=False).stdout, sandbox.cli(*args, base=False).stdout
    assert primera == segunda
    assert primera.count("\n") == 1 and primera.startswith('{"candidaturas":')


def error_de(sandbox, *args):
    r = sandbox.cli("espontaneas-consulta", *args, base=False)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


def test_error_si_no_existe_el_csv(sandbox, a):
    codigo, salida = error_de(sandbox, "--csv", str(a.csv_ausente))
    assert codigo == 2 and salida["ok"] is False and "no existe el CSV" in salida["error"]


def test_error_si_al_csv_le_faltan_columnas(sandbox, a):
    codigo, salida = error_de(sandbox, "--csv", str(a.csv_malo))
    assert codigo == 2 and salida["ok"] is False and "le faltan columnas" in salida["error"]


def test_error_si_no_existe_el_excel(sandbox, a):
    codigo, salida = error_de(sandbox, "--csv", str(a.csv), "--empresa", "x", "--excel", str(a.ausente))
    assert codigo == 2 and salida["ok"] is False and "no existe el Excel" in salida["error"]


def test_error_si_el_excel_esta_roto(sandbox, a):
    codigo, salida = error_de(sandbox, "--csv", str(a.csv), "--empresa", "x", "--excel", str(a.roto))
    assert codigo == 2 and salida["ok"] is False and "no se puede leer" in salida["error"]


def test_error_si_el_excel_no_tiene_la_hoja_candidaturas(sandbox, a):
    codigo, salida = error_de(sandbox, "--csv", str(a.csv), "--empresa", "x", "--excel", str(a.sin_hoja))
    assert codigo == 2 and salida["ok"] is False and "no tiene la hoja Candidaturas" in salida["error"]


def test_un_error_no_lleva_recuentos_ni_contactada(sandbox, a):
    _, salida = error_de(sandbox, "--csv", str(a.csv), "--empresa", "x", "--excel", str(a.roto))
    assert set(salida) == {"ok", "error"}          # un error no es un cero


def test_las_consultas_no_modifican_ningun_archivo(sandbox, a):
    archivos = [a.xlsx, a.csv, a.roto, a.sin_hoja, a.csv_malo]
    antes = sello(archivos)
    consultar(sandbox, a, "--empresa", "Acme", "--excel", str(a.xlsx))
    sandbox.cli("espontaneas-consulta", "--csv", str(a.csv_malo), base=False)
    sandbox.cli("espontaneas-consulta", "--csv", str(a.csv), "--excel", str(a.roto), "--empresa", "x", base=False)
    assert sello(archivos) == antes
