"""Comandos de src.cli ejecutados en proceso sobre un histórico sintético.  python -m pytest src/test_cli.py"""
import json
from datetime import date

import pytest

from . import cli as modulo, cv, db
from .testing.entorno import (anadir_oferta, cambiar_cv_base, candidaturas_falso, celda_excel, csv_de_envios, csv_ilegible, editar_excel, enviadas,
                              excel_de_resultados, ids_por_estado, preparar_cv, xlsx)


def campos(cli, oid, lista):
    return cli("oferta", oid, "--campos", lista).json()


# --- perfil y modo ---------------------------------------------------------------------------------------------------
def test_sin_perfil_se_dice_como_crearlo(cli, monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_AGENTS_PERFIL", str(tmp_path / "no-existe.yaml"))
    assert "Falta config/profile.yaml" in cli("modo").texto


def test_un_modo_de_envio_invalido_se_rechaza(cli, sandbox):
    sandbox.perfil.write_text(sandbox.perfil.read_text(encoding="utf-8").replace("modo: revision", "modo: inventado"), encoding="utf-8")
    assert cli("modo").codigo != 0 and "Modo de envío no válido" in cli("modo").texto


# --- filtrar ---------------------------------------------------------------------------------------------------------
def test_filtrar_separa_las_nuevas_de_las_ya_vistas(cli):
    entrada = json.dumps([{"empresa": "A", "titulo": "Front Angular"}, {"empresa": "Nueva", "titulo": "Otra"}])
    r = cli("filtrar", "-", entrada=entrada).json()
    assert r["nuevas"] == [{"empresa": "Nueva", "titulo": "Otra"}] and r["saltadas"] == ["A | Front Angular (ya vista)"]


def test_filtrar_acepta_un_solo_objeto_y_un_archivo(cli, tmp_path):
    archivo = tmp_path / "o.json"
    archivo.write_text(json.dumps({"empresa": "Nueva", "titulo": "Otra"}), encoding="utf-8")
    assert cli("filtrar", archivo).json()["nuevas"] == [{"empresa": "Nueva", "titulo": "Otra"}]


def test_filtrar_salta_lo_ya_postulado_por_clave_o_por_id(cli, monkeypatch):
    monkeypatch.setattr(modulo, "ya_postuladas", lambda: ({db.clave("Zeta", "Dev")}, {"li:9"}))
    entrada = json.dumps([{"empresa": "Zeta", "titulo": "Dev"}, {"empresa": "Otra", "titulo": "Y", "ids_externos": ["li:9"]},
                          {"empresa": "Libre", "titulo": "Z"}])
    r = cli("filtrar", "-", entrada=entrada).json()
    assert len(r["nuevas"]) == 1 and r["nuevas"][0]["empresa"] == "Libre"
    assert r["saltadas"] == ["Zeta | Dev (ya postulada (candidaturas.xlsx))", "Otra | Y (ya postulada (candidaturas.xlsx))"]


# --- guardar ---------------------------------------------------------------------------------------------------------
def guardar(cli, **oferta):
    r = cli("guardar", "-", entrada=json.dumps([{"empresa": "Acme", "titulo": "Frontend", "encaje": 80, **oferta}]))
    return r.json()


def test_guardar_una_oferta_nueva(cli):
    r = guardar(cli)
    assert len(r["nuevas"]) == 1 and r["nuevas"][0].endswith("Acme | Frontend (80)") and r["fusionadas"] == []


@pytest.mark.parametrize("oferta, nota", [
    ({"titulo": "Senior Dev"}, "Filtro: puesto Senior"),
    ({"encaje": 40}, "Filtro: encaje 40 < 55"),
    ({"eliminatorios": "presencial"}, "Filtro: eliminatorio: presencial"),
])
def test_el_filtro_de_calidad_descarta_al_guardar(cli, oferta, nota):
    oid = guardar(cli, **oferta)["nuevas"][0].split()[0]
    assert campos(cli, oid, "estado,notas") == {"id": oid, "estado": "descartada", "notas": nota}


def test_una_oferta_con_buen_encaje_queda_nueva(cli):
    oid = guardar(cli)["nuevas"][0].split()[0]
    assert campos(cli, oid, "estado")["estado"] == "nueva"


def test_un_estado_explicito_no_se_descarta(cli):
    oid = guardar(cli, encaje=10, estado="pendiente_revision")["nuevas"][0].split()[0]
    assert campos(cli, oid, "estado")["estado"] == "pendiente_revision"


def test_una_oferta_ya_guardada_se_fusiona_y_conserva_su_estado(cli):
    guardar(cli)
    r = guardar(cli, encaje=10)                        # con encaje bajo no se descarta: solo se filtra al insertar
    assert r["nuevas"] == [] and len(r["fusionadas"]) == 1
    assert campos(cli, r["fusionadas"][0].split()[0], "estado")["estado"] == "nueva"


def test_guardar_ignora_lo_que_no_tiene_empresa_o_titulo(cli):
    r = cli("guardar", "-", entrada=json.dumps([{"titulo": "Sin empresa", "urls": ["https://x"]}]))
    assert r.json() == {"nuevas": [], "fusionadas": []} and "Ignorada" in r.error


# --- depurar ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def con_bajas(sandbox):
    anadir_oferta(sandbox.base, empresa="Baja", titulo="Dev", encaje=10)
    anadir_oferta(sandbox.base, empresa="Senior", titulo="Senior Dev", encaje=90)
    return anadir_oferta(sandbox.base, empresa="BajaCV", titulo="Dev", encaje=5, estado="cv_adaptado")


def test_depurar_simular_lista_sin_cambiar_nada(cli, con_bajas):
    r = cli("depurar", "--simular")
    assert "2 ofertas se descartarían (mínimo 55)" in r.salida and "Baja" in r.salida
    assert cli("huella").codigo == 0 and campos(cli, con_bajas, "estado")["estado"] == "cv_adaptado"


def test_depurar_descarta_las_nuevas_que_no_pasan_el_filtro(cli, sandbox, con_bajas):
    r = cli("depurar")
    assert "2 ofertas descartadas" in r.salida
    assert campos(cli, ids_por_estado(sandbox.base, "descartada")[0], "notas")["notas"].startswith("Filtro: ")
    assert campos(cli, con_bajas, "estado")["estado"] == "cv_adaptado"       # las adaptadas no se tocan


def test_depurar_puede_incluir_las_adaptadas(cli, con_bajas):
    assert "3 ofertas descartadas" in cli("depurar", "--incluir-adaptadas").salida
    assert campos(cli, con_bajas, "estado")["estado"] == "descartada"


# --- listar, oferta y estado -----------------------------------------------------------------------------------------
def test_listar_en_texto_muestra_una_linea_por_oferta(cli):
    r = cli("listar")
    assert "5 ofertas" in r.salida and "A | Front Angular" in r.salida


@pytest.mark.parametrize("filtro, cuantas", [(("--estado", "nueva"), 2), (("--min-encaje", 75), 2), (("--semana", db.semana()), 5),
                                              (("--semana", "2020-W01"), 0)])
def test_listar_filtra(cli, filtro, cuantas):
    assert f"{cuantas} ofertas" in cli("listar", *filtro).salida


def test_oferta_con_requisitos_en_texto_plano_no_falla(cli, sandbox):
    oid = anadir_oferta(sandbox.base, empresa="Vieja", requisitos="texto plano, no JSON")
    assert campos(cli, oid, "requisitos")["requisitos"] == "texto plano, no JSON"


def test_oferta_devuelve_listas_decodificadas(cli, sandbox):
    oid = anadir_oferta(sandbox.base, empresa="Nueva", urls=["https://x/1"], portales=["linkedin"])
    o = cli("oferta", oid).json()
    assert o["urls"] == ["https://x/1"] and o["portales"] == ["linkedin"]


def test_estado_cambia_la_oferta_y_anota(cli, sandbox):
    oid = ids_por_estado(sandbox.base, "nueva")[0]
    assert cli("estado", oid, "descartada", "--nota", "no me encaja").salida.strip() == f"{oid} -> descartada"
    assert campos(cli, oid, "estado,notas")["notas"] == "no me encaja"


# --- enviada y seguimiento -------------------------------------------------------------------------------------------
def test_enviada_por_linkedin_no_se_registra_aparte(cli, sandbox):
    oid = ids_por_estado(sandbox.base, "cv_adaptado")[0]
    r = cli("enviada", oid, "--origen", "LinkedIn")
    assert f"{oid} -> enviada" in r.salida and "Seguimiento" not in r.salida


def test_enviada_borra_la_carpeta_subir_de_esa_oferta(cli, sandbox):
    oid = ids_por_estado(sandbox.base, "cv_adaptado")[0]
    subir = sandbox.datos / "output" / "SUBIR" / oid
    subir.mkdir(parents=True)
    (subir / "cv.pdf").write_bytes(b"%PDF")
    cli("enviada", oid, "--origen", "LinkedIn")
    assert not subir.exists()


def test_enviada_por_otro_portal_sin_candidaturas_sync_lo_dice(cli, sandbox):
    oid = ids_por_estado(sandbox.base, "cv_adaptado")[0]
    assert "Seguimiento: sin candidaturas_sync configurado" in cli("enviada", oid, "--origen", "InfoJobs").salida


def test_enviada_por_otro_portal_la_registra_en_candidaturas_sync(cli, sandbox):
    args = candidaturas_falso(sandbox.activar_sync())
    oid = anadir_oferta(sandbox.base, empresa="Acme", titulo="Dev", urls=["https://x/1"])
    r = cli("enviada", oid, "--origen", "InfoJobs")
    assert "Seguimiento: nueva ok" in r.salida
    assert json.loads(args.read_text(encoding="utf-8")) == ["nueva", "--empresa=Acme", "--puesto=Dev", "--origen=InfoJobs",
                                                             f"--nota=Enviada por job-agents ({oid})", "--enlace=https://x/1"]


def test_un_nombre_de_empresa_con_guiones_no_se_interpreta_como_opcion(cli, sandbox):
    args = candidaturas_falso(sandbox.activar_sync())
    oid = anadir_oferta(sandbox.base, empresa="--malo", titulo="Dev")
    cli("enviada", oid, "--origen", "InfoJobs")
    assert "--empresa=--malo" in json.loads(args.read_text(encoding="utf-8")) and "--enlace" not in args.read_text(encoding="utf-8")


def test_enviada_de_una_oferta_inexistente_falla(cli):
    r = cli("enviada", "2026-W00-001", "--origen", "LinkedIn")
    assert r.codigo != 0 and "No existe la oferta" in r.texto


def test_en_prueba_enviada_no_se_envia_ni_se_registra(cli_prueba, sandbox):
    r = cli_prueba("enviada", ids_por_estado(sandbox.base, "cv_adaptado")[0], "--origen", "InfoJobs")
    assert r.codigo != 0 and "nunca se envía" in r.texto


# --- candidaturas_sync -----------------------------------------------------------------------------------------------
def test_una_carpeta_de_sync_fuera_del_proyecto_se_rechaza(cli, sandbox):
    sandbox.perfil.write_text(sandbox.perfil.read_text(encoding="utf-8").replace("candidaturas_sync: null", "candidaturas_sync: ../fuera"), encoding="utf-8")
    r = cli("filtrar", "-", entrada="[]")
    assert r.codigo != 0 and "debe estar dentro del proyecto" in r.texto


def test_el_excel_de_sync_por_defecto_es_candidaturas_xlsx(cli, sandbox):
    carpeta = sandbox.activar_sync()
    assert modulo.ruta_candidaturas() == carpeta.resolve() / "candidaturas.xlsx"


@pytest.mark.parametrize("excel, esperado", [("datos/c.xlsx", "datos/c.xlsx"), ("otro.xlsx", "otro.xlsx")])
def test_el_excel_de_sync_puede_venir_del_config_toml(cli, sandbox, excel, esperado):
    carpeta = sandbox.activar_sync()
    (carpeta / "config.toml").write_text(f'excel = "{excel}"\n', encoding="utf-8")
    assert modulo.ruta_candidaturas() == carpeta.resolve() / esperado


def test_el_excel_de_sync_puede_ser_una_ruta_absoluta(cli, sandbox, tmp_path):
    carpeta = sandbox.activar_sync()
    absoluta = (tmp_path / "fuera" / "c.xlsx").as_posix()
    (carpeta / "config.toml").write_text(f'excel = "{absoluta}"\n', encoding="utf-8")
    assert modulo.ruta_candidaturas() == tmp_path / "fuera" / "c.xlsx"


# --- resultados y embudo ---------------------------------------------------------------------------------------------
CABECERA_SYNC = ["Empresa", "Puesto", "Fase", "Notas", "Ref"]


@pytest.fixture
def con_envios(sandbox, cli):
    """Tres enviadas hace 30 días: A (rechazo en el Excel), B (entrevista por referencia) y C (silencio)."""
    carpeta = sandbox.activar_sync()
    con = db.conectar(sandbox.base)
    ids = enviadas(con, ["A", "B", "C"])
    con.commit()
    xlsx(carpeta / "candidaturas.xlsx", "Candidaturas", [CABECERA_SYNC, ["A", "Dev", "Rechazado", None, None],
                                                           ["Otra", "X", "En curso", "entrevista el lunes", "li:B"]])
    return ids


def test_resultados_aplica_rechazo_entrevista_y_silencio(cli, con_envios):
    r = cli("resultados")
    assert f"{con_envios['A']} A: enviada -> rechazo" in r.salida
    assert f"{con_envios['B']} B: enviada -> entrevista" in r.salida
    assert f"{con_envios['C']} C: enviada -> silencio_14d" in r.salida
    assert json.loads(r.salida.splitlines()[3]) == {"enviadas": 3, "respuesta": 0, "entrevista": 1, "rechazo": 1, "silencio_14d": 1}


def test_resultados_simular_no_guarda_los_cambios(cli, con_envios):
    cli("resultados", "--simular")
    assert campos(cli, con_envios["A"], "estado")["estado"] == "enviada"


def test_resultados_json_incluye_el_embudo_completo(cli, con_envios):
    r = cli("resultados", "--json")
    e = json.loads(r.salida.splitlines()[3])
    assert e["total"]["enviadas"] == 3 and e["espontaneas"]["enviadas"] == 0 and e["portal"]["?"]["enviadas"] == 3


def test_resultados_en_texto_desglosa_por_dimension(cli, con_envios):
    assert "portal    ?" in cli("resultados").salida and "espontáneas: 0 enviadas" in cli("resultados").salida


def test_el_embudo_agrupa_por_el_perfil_del_cv_usado(cli, sandbox, con_envios):
    adaptacion = sandbox.datos / "output" / campos(cli, con_envios["A"], "semana")["semana"] / con_envios["A"]
    adaptacion.mkdir(parents=True)
    (adaptacion / "adaptacion.json").write_text(json.dumps({"perfil": "ia"}), encoding="utf-8")
    e = json.loads(cli("resultados", "--json").salida.splitlines()[3])
    assert e["cv"]["ia"]["enviadas"] == 1 and e["cv"]["sin_cv"]["enviadas"] == 2


def test_resultados_sin_candidaturas_sync_no_marca_silencios(cli, sandbox):
    con = db.conectar(sandbox.base)
    ids = enviadas(con, ["A"])
    con.commit()
    r = cli("resultados")
    assert json.loads(r.salida.splitlines()[0])["silencio_14d"] == 0
    assert campos(cli, ids["A"], "estado")["estado"] == "enviada"


# --- contactos -------------------------------------------------------------------------------------------------------
def test_contactos_lista_a_quien_buscar(cli, sandbox):
    con = db.conectar(sandbox.base)
    ids = enviadas(con, ["A"])
    con.commit()
    assert cli("contactos").json()["contactar"][0]["id"] == ids["A"]


def test_contacto_guarda_persona_y_nota(cli, sandbox):
    con = db.conectar(sandbox.base)
    ids = enviadas(con, ["A"])
    con.commit()
    r = cli("contacto", ids["A"], "--persona", "Ana | TA | url", "--nota", "Hola")
    assert "contacto, nota_contacto, contacto_fecha guardado" in r.salida
    assert cli("contactos", "--hoy").json()[0]["contacto"] == "Ana | TA | url"


def test_contactos_hoy_omite_los_no_encontrados(cli, sandbox):
    con = db.conectar(sandbox.base)
    ids = enviadas(con, ["A"])
    con.commit()
    cli("contacto", ids["A"], "--persona", "no encontrado")
    assert cli("contactos", "--hoy").json() == []


def test_contacto_sin_nada_que_guardar_falla(cli, sandbox):
    r = cli("contacto", ids_por_estado(sandbox.base, "nueva")[0])
    assert r.codigo != 0 and "Nada que guardar" in r.texto


def test_contacto_de_una_oferta_inexistente_falla(cli):
    assert "No existe la oferta" in cli("contacto", "2026-W00-001", "--persona", "x").texto


@pytest.mark.parametrize("opcion, texto, motivo", [("--nota", "x" * 301, "máximo 300"), ("--seguimiento", "x" * 301, "máximo 300"),
                                                    ("--nota", "hola — adiós", "guiones"), ("--seguimiento", "hola – adiós", "guiones")])
def test_contacto_rechaza_textos_largos_o_con_guiones(cli, sandbox, opcion, texto, motivo):
    r = cli("contacto", ids_por_estado(sandbox.base, "nueva")[0], opcion, texto)
    assert r.codigo != 0 and motivo in r.texto


# --- excel y resumen -------------------------------------------------------------------------------------------------
def test_excel_importa_lo_editado_a_mano_y_lo_cuenta(cli, sandbox):
    cli("excel")
    ruta = sandbox.datos / "ofertas" / f"ofertas_{db.semana()}.xlsx"
    editar_excel(ruta, "Estado", 2, "descartada")
    r = cli("excel")
    assert "(editado en Excel)" in r.salida and "Excel actualizado" in r.salida and celda_excel(ruta, "Estado", 5) is not None


def test_resumen_cuenta_lo_de_hoy_y_anota_los_errores(cli, sandbox):
    r = cli("resumen", "--errores", "falló buscar")
    assert "- Ofertas nuevas hoy: 5" in r.salida and "- CVs adaptados pendientes de enviar: 2" in r.salida
    assert "- Errores: falló buscar" in r.salida and (sandbox.logs / f"{date.today().isoformat()}.md").exists()


def test_pendientes_sin_csv_de_espontaneas_no_tiene_espontaneas_hoy(cli):
    assert cli("pendientes").json()["espontaneas_hoy"] == []


# --- perfiles --------------------------------------------------------------------------------------------------------
@pytest.fixture
def con_cv_base(sandbox, monkeypatch):
    preparar_cv(sandbox.raiz)
    monkeypatch.setattr(cv, "BASE", sandbox.raiz / "cv_base.yaml")
    monkeypatch.setattr(cv, "PROFILE", sandbox.raiz / "profile.yaml")
    return sandbox.raiz


def test_perfiles_avisa_de_los_pdf_que_faltan(cli, con_cv_base):
    r = cli("perfiles").json()
    assert r["ok"] is True and r["perfiles"][0]["pdf"] == {"es": False, "en": False} and len(r["avisos"]) == 2


def test_perfiles_reconoce_el_pdf_unico_de_cada_idioma(cli, con_cv_base):
    for idioma in ("es", "en"):
        (con_cv_base / "cv" / "ia" / idioma).mkdir(parents=True)
        (con_cv_base / "cv" / "ia" / idioma / "CV.pdf").write_bytes(b"%PDF")
    r = cli("perfiles").json()
    assert r["perfiles"][0]["pdf"] == {"es": True, "en": True} and r["avisos"] == []


# --- preparar --------------------------------------------------------------------------------------------------------
def test_preparar_una_oferta_inexistente_falla(cli):
    r = cli("preparar", "2026-W00-001")
    assert r.codigo != 0 and "No existe la oferta" in r.texto


def test_preparar_sin_cv_adaptado_pide_adaptar_primero(cli, sandbox):
    r = cli("preparar", ids_por_estado(sandbox.base, "nueva")[0])
    assert r.codigo != 0 and "no tiene CV adaptado" in r.texto


# --- cv de una oferta (genera el PDF con Chromium) -------------------------------------------------------------------
@pytest.fixture
def adaptar(cli, sandbox, con_cv_base):
    """Ejecuta `cv <oferta A> <adaptación>`; la adaptación se escribe como JSON en la carpeta temporal."""
    def ejecutar(**adaptacion):
        ruta = sandbox.raiz / "adaptacion.json"
        ruta.write_text(json.dumps({"idioma": "es", "titular": "Front Angular | Datos", **adaptacion}), encoding="utf-8")
        oid = ids_por_estado(sandbox.base, "nueva")[0]
        return oid, cli("cv", oid, ruta)
    return ejecutar


def test_cv_de_una_oferta_deja_el_cv_adaptado(adaptar, cli):
    oid, r = adaptar(carencias=["Kubernetes"], palabras_clave=["Front", "Kubernetes"])
    assert f"{oid} -> cv_adaptado" in r.salida
    f = campos(cli, oid, "estado,coincidencia_kw,carencias")
    assert (f["estado"], f["coincidencia_kw"], f["carencias"]) == ("cv_adaptado", "50%", "Kubernetes")


def test_cv_sin_palabras_clave_no_guarda_coincidencia(adaptar, cli):
    oid, _ = adaptar()
    assert campos(cli, oid, "coincidencia_kw")["coincidencia_kw"] is None


def test_cv_guarda_la_adaptacion_junto_al_pdf(adaptar, sandbox, cli):
    oid, _ = adaptar()
    semana = campos(cli, oid, "semana")["semana"]
    assert json.loads((sandbox.datos / "output" / semana / oid / "adaptacion.json").read_text(encoding="utf-8"))["idioma"] == "es"


def test_cv_exige_el_titulo_del_puesto_en_el_titular(adaptar):
    _, r = adaptar(titular="Otro título | Datos")
    assert r.codigo != 0 and "el titular debe incluir el título del puesto" in r.texto


def test_cv_de_una_oferta_inexistente_falla(cli, sandbox):
    ruta = sandbox.raiz / "a.json"
    ruta.write_text("{}", encoding="utf-8")
    assert "No existe la oferta" in cli("cv", "2026-W00-001", ruta).texto


def test_cv_de_mas_de_una_pagina_se_rechaza(adaptar, cli):
    oid, r = adaptar(bullets={"job1": ["Una viñeta muy larga que ocupa varias líneas del documento. " * 8] * 40})
    assert r.codigo != 0 and "páginas" in r.texto and campos(cli, oid, "estado")["estado"] == "nueva"


def test_cv_con_guiones_en_la_base_se_rechaza(adaptar, con_cv_base):
    cambiar_cv_base(con_cv_base, "es", "resumen", "Texto con un guion – largo en la base")
    _, r = adaptar()
    assert r.codigo != 0 and "guiones largos o medios" in r.texto


# --- espontaneas-informe y consulta ----------------------------------------------------------------------------------
def test_informe_cruza_cada_empresa_con_su_resultado_exacto(cli, tmp_path):
    inf = cli("espontaneas-informe", "--csv", csv_de_envios(tmp_path / "e.csv"), "--excel", excel_de_resultados(tmp_path / "c.xlsx"), "--json").json()
    t = inf["total"]
    assert (t["enviadas"], t["entrevista"], t["rechazo"], inf["sin_fila_en_excel"]) == (3, 1, 1, 1)   # Acme no se confunde con AcmeSoft


def test_informe_en_texto(cli, tmp_path):
    r = cli("espontaneas-informe", "--csv", csv_de_envios(tmp_path / "e.csv"), "--excel", excel_de_resultados(tmp_path / "c.xlsx"))
    assert "3 enviadas" in r.salida


def test_informe_con_un_csv_que_no_existe_falla(cli, tmp_path):
    r = cli("espontaneas-informe", "--csv", tmp_path / "no.csv")
    assert r.codigo != 0 and "no existe el CSV de empresas" in r.texto


def test_consulta_con_un_csv_ilegible_falla(cli, tmp_path):
    r = cli("espontaneas-consulta", "--csv", csv_ilegible(tmp_path / "e.csv"))
    assert r.codigo != 0 and "no se puede leer" in r.salida


def test_consulta_con_un_excel_sin_columna_empresa_falla(cli, tmp_path):
    r = cli("espontaneas-consulta", "--csv", csv_de_envios(tmp_path / "e.csv"), "--empresa", "x",
            "--excel", xlsx(tmp_path / "c.xlsx", "Candidaturas", [["Otra"]]))
    assert r.codigo != 0 and "no tiene la columna Empresa" in r.salida


# --- sincronizar y embudo: los casos que no cambian nada -------------------------------------------------------------
def test_una_oferta_enviada_que_luego_se_descarta_no_se_sincroniza(cli, sandbox, con):
    ids = enviadas(con, ["A"])
    con.execute("UPDATE ofertas SET estado = 'descartada' WHERE id = ?", (ids["A"],))
    assert modulo.sincronizar(con, [], date(2026, 11, 17)) == []


def test_filas_del_excel_sin_resultado_no_cambian_nada(con):
    ids = enviadas(con, ["A"], dias=1)
    assert modulo.sincronizar(con, [{"Empresa": "A", "Puesto": "Dev", "Fase": "Enviada", "Notas": None}], date(2026, 11, 17)) == []


def test_el_total_del_embudo_no_cuenta_estados_fuera_del_embudo(con):
    enviadas(con, ["A"])
    con.execute("UPDATE ofertas SET estado = 'descartada'")
    assert modulo.embudo_total(con)["enviadas"] == 1 and modulo.embudo_total(con)["rechazo"] == 0


def test_una_espontanea_sin_respuesta_cuenta_como_enviada():
    assert modulo.embudo_espontaneas([{"Puesto": "Espontánea", "Fase": "Enviada", "Notas": None}])["enviadas"] == 1
