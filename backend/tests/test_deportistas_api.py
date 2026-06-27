"""Tests de la API de Deportistas (contratos C4/C5).

- `test_deportista_create_schema_*`: validación dura de tutor+consentimiento a nivel
  schema (no requiere BD; cubre el 422 lógico de RF-USR-04).
- Tests marcados `db`: flujo end-to-end (login -> listar -> crear sin tutor 422 ->
  ficha médica gateada). Requieren BD migrada + seed. Skip si no hay BD.

El seed se asume ejecutado (admin@latinosport.bo / admin1234). Si no, hacer:
    .venv\\Scripts\\python -m app.seed
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.schemas.deportista import DeportistaCreate
from pydantic import ValidationError

# --------------------------------------------------------------------------- #
# Validación dura a nivel schema (sin BD)
# --------------------------------------------------------------------------- #
_BASE_BODY: dict[str, Any] = {
    "sucursal_id": "11111111-1111-1111-1111-111111111111",
    "nombres": "Test Deportista",
    # El CI del DEPORTISTA es OBLIGATORIO a nivel schema (regla de negocio).
    "ci": "CI-12345678",
    "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
}


def test_deportista_create_schema_ok() -> None:
    body = dict(_BASE_BODY)
    body["tutores"] = [{"nombres": "Tutor 1", "telefono": "777", "parentesco": "Padre"}]
    obj = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert len(obj.tutores) == 1
    assert obj.consentimiento.version_terminos == "v1"


def test_deportista_create_schema_sin_tutor_falla() -> None:
    """Sin tutores (lista vacía) -> ValidationError (=> 422 en la API)."""
    body = dict(_BASE_BODY)
    body["tutores"] = []
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]


def test_deportista_create_schema_sin_consentimiento_falla() -> None:
    """Sin consentimiento -> ValidationError (=> 422 en la API)."""
    body = {
        "sucursal_id": _BASE_BODY["sucursal_id"],
        "nombres": "Test",
        "ci": "CI-99999999",
        "tutores": [{"nombres": "Tutor 1"}],
    }
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]


def test_deportista_create_schema_sin_ci_falla() -> None:
    """CI del DEPORTISTA OBLIGATORIO: sin `ci` (o vacío) -> ValidationError (=> 422).

    Refuerza la asimetría: el deportista DEBE llevar CI; el TUTOR no.
    """
    # Sin `ci` en absoluto.
    body = {
        "sucursal_id": _BASE_BODY["sucursal_id"],
        "nombres": "Sin CI",
        "tutores": [{"nombres": "Tutor 1"}],
        "consentimiento": {"version_terminos": "v1"},
    }
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]

    # CI presente pero vacío / solo espacios -> también rechazado (validador strip).
    for ci_vacio in ("", "   "):
        body_vacio = dict(body)
        body_vacio["ci"] = ci_vacio
        with pytest.raises(ValidationError):
            DeportistaCreate(**body_vacio)  # type: ignore[arg-type]


def test_deportista_create_tutor_sin_ci_ok() -> None:
    """El TUTOR sin CI SÍ se permite (su CI es opcional), aun con CI del deportista."""
    body = dict(_BASE_BODY)
    # Tutor explícitamente sin `ci` (campo opcional).
    body["tutores"] = [{"nombres": "Tutor sin CI", "telefono": "777"}]
    obj = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert obj.ci == "CI-12345678"
    assert obj.tutores[0].ci is None


def test_deportista_create_disciplina_id_opcional() -> None:
    """`DeportistaCreate` acepta `disciplina_id` opcional (default None) sin perder el
    texto legacy `disciplina` (S3: FK canónica al catálogo global)."""
    import uuid

    body = dict(_BASE_BODY)
    body["tutores"] = [{"nombres": "Tutor 1"}]
    sin = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert sin.disciplina_id is None

    disc_id = uuid.uuid4()
    body2 = dict(_BASE_BODY)
    body2["tutores"] = [{"nombres": "Tutor 1"}]
    body2["disciplina_id"] = str(disc_id)
    body2["disciplina"] = "Voley (texto legacy)"
    con = DeportistaCreate(**body2)  # type: ignore[arg-type]
    assert con.disciplina_id == disc_id
    assert con.disciplina == "Voley (texto legacy)"  # legacy se conserva


def test_deportista_update_acepta_disciplina_id() -> None:
    """`DeportistaUpdate` acepta `disciplina_id` opcional (S3)."""
    import uuid

    from app.schemas.deportista import DeportistaUpdate

    disc_id = uuid.uuid4()
    u = DeportistaUpdate(disciplina_id=disc_id)
    assert u.disciplina_id == disc_id
    # Si no se envía, queda exclude_unset (no fuerza None destructivo).
    assert "disciplina_id" not in DeportistaUpdate().model_dump(exclude_unset=True)


# --------------------------------------------------------------------------- #
# Flujo end-to-end contra la API real (requiere BD + seed)
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado + seed")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _login_admin(client) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@latinosport.bo", "password": "admin1234"},
    )
    if resp.status_code != 200:
        pytest.skip(f"Login admin falló ({resp.status_code}); ¿seed ejecutado?")
    return resp.json()["access_token"]


@pytest.mark.db
def test_login_y_listar_deportistas() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    resp = client.get(
        "/api/v1/deportistas",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "page" in data
    assert isinstance(data["items"], list)


@pytest.mark.db
def test_listar_sin_token_401() -> None:
    client = _client_or_skip()
    resp = client.get("/api/v1/deportistas")
    assert resp.status_code == 401


@pytest.mark.db
def test_crear_deportista_sin_tutor_422() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    # tomamos una sucursal real
    suc = client.get("/api/v1/sucursales", headers={"Authorization": f"Bearer {token}"}).json()
    sucursal_id = suc[0]["id"] if suc else "11111111-1111-1111-1111-111111111111"
    resp = client.post(
        "/api/v1/deportistas",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Sin Tutor",
            "tutores": [],
            "consentimiento": {"version_terminos": "v1"},
        },
    )
    assert resp.status_code == 422


@pytest.mark.db
def test_ficha_medica_gateada_por_rol() -> None:
    """Comportamiento REAL hoy: el ENTRENADOR lista/ve sus deportistas (red de seguridad
    por disciplina) y, como su JWT incluye TODAS las sucursales de la org (auth.py lo
    hace a propósito), `_puede_ver_ficha` da True -> el coach SÍ ve la ficha médica.

    NOTA: el gating fino "el coach NO ve la ficha de otra sucursal" requiere que el token
    LIMITE las sucursales del entrenador (épica futura); hoy el entrenador trae todas, así
    que aquí solo afirmamos lo que el auth produce de verdad: el coach ve al deportista
    (200) y su ficha (campo presente, con datos si el deportista los tiene).
    """
    client = _client_or_skip()
    admin_token = _login_admin(client)

    # ADMIN: el contrato del detalle incluye `ficha_medica`.
    lista_admin = client.get(
        "/api/v1/deportistas?page_size=50",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    if not lista_admin["items"]:
        pytest.skip("No hay deportistas; ¿seed ejecutado?")
    detalle_admin = client.get(
        f"/api/v1/deportistas/{lista_admin['items'][0]['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert "ficha_medica" in detalle_admin

    # ENTRENADOR: tomar el deportista de SU PROPIA lista (siempre visible bajo la red
    # de seguridad por disciplina), no de la del admin.
    coach = client.post(
        "/api/v1/auth/login",
        json={"email": "coach@latinosport.bo", "password": "coach1234"},
    )
    if coach.status_code != 200:
        pytest.skip("Entrenador no sembrado")
    coach_token = coach.json()["access_token"]
    coach_headers = {"Authorization": f"Bearer {coach_token}"}

    lista_coach = client.get("/api/v1/deportistas?page_size=50", headers=coach_headers).json()
    if not lista_coach["items"]:
        pytest.skip("El entrenador no ve deportistas; ¿seed con disciplinas?")

    deportista_id = lista_coach["items"][0]["id"]
    detalle_coach = client.get(f"/api/v1/deportistas/{deportista_id}", headers=coach_headers)
    # 200 (visible) y el contrato del detalle expone `ficha_medica` (no 404 genérico del
    # scoping viejo: la red de seguridad solo bloquea si hay conflicto real de disciplina).
    assert detalle_coach.status_code == 200, detalle_coach.text
    assert "ficha_medica" in detalle_coach.json()


@pytest.mark.db
def test_crear_y_actualizar_campos_opcionales() -> None:
    """`domicilio` y `lugar_nacimiento` se persisten en el alta, vuelven en el detalle
    y se actualizan vía PUT (misma semántica que `contacto_emergencia`).

    No están en el item de lista (resumen), solo en el detalle (C5).
    """
    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    suc = client.get("/api/v1/sucursales", headers=headers).json()
    if not suc:
        pytest.skip("No hay sucursales; ¿seed ejecutado?")
    sucursal_id = suc[0]["id"]

    import uuid as _uuid

    ci = f"CI-OPT-{_uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/deportistas",
        headers=headers,
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Campos Opcionales",
            "ci": ci,
            "domicilio": "Calle Falsa 123, Zona Sur",
            "lugar_nacimiento": "Cochabamba, Bolivia",
            "tutores": [{"nombres": "Tutor Opt", "telefono": "777"}],
            "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
        },
    )
    assert resp.status_code == 201, resp.text
    creado = resp.json()
    assert creado["domicilio"] == "Calle Falsa 123, Zona Sur"
    assert creado["lugar_nacimiento"] == "Cochabamba, Bolivia"
    deportista_id = creado["id"]

    # El detalle (GET) los devuelve.
    detalle = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers)
    assert detalle.status_code == 200
    detalle_json = detalle.json()
    assert detalle_json["domicilio"] == "Calle Falsa 123, Zona Sur"
    assert detalle_json["lugar_nacimiento"] == "Cochabamba, Bolivia"

    # El item de lista NO los incluye (es resumen).
    lista = client.get(f"/api/v1/deportistas?q={ci}&page_size=50", headers=headers).json()
    items = [it for it in lista["items"] if it["id"] == deportista_id]
    if items:
        assert "domicilio" not in items[0]
        assert "lugar_nacimiento" not in items[0]

    # PUT los actualiza.
    upd = client.put(
        f"/api/v1/deportistas/{deportista_id}",
        headers=headers,
        json={
            "domicilio": "Av. Nueva 456",
            "lugar_nacimiento": "La Paz, Bolivia",
        },
    )
    assert upd.status_code == 200, upd.text
    upd_json = upd.json()
    assert upd_json["domicilio"] == "Av. Nueva 456"
    assert upd_json["lugar_nacimiento"] == "La Paz, Bolivia"


# --------------------------------------------------------------------------- #
# Baja / Reactivar (soft-delete, C4) — requiere BD + seed
# --------------------------------------------------------------------------- #
def _crear_deportista_basico(client, headers) -> str:
    """Crea un deportista mínimo (1 tutor + consentimiento) y devuelve su id."""
    import uuid as _uuid

    suc = client.get("/api/v1/sucursales", headers=headers).json()
    if not suc:
        pytest.skip("No hay sucursales; ¿seed ejecutado?")
    sucursal_id = suc[0]["id"]
    ci = f"CI-BAJA-{_uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/deportistas",
        headers=headers,
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Baja Test",
            "ci": ci,
            "tutores": [{"nombres": "Tutor Baja", "telefono": "777"}],
            "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.db
def test_baja_oculta_de_solo_activos_pero_accesible_por_id() -> None:
    """Dar de baja pone `activo=false`; el deportista desaparece de
    `?solo_activos=true` pero sigue accesible por id (con `activo=false`).
    Reactivar lo restaura (vuelve a aparecer en `?solo_activos=true`)."""
    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    deportista_id = _crear_deportista_basico(client, headers)

    # Arranca activo.
    detalle = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers).json()
    assert detalle["activo"] is True

    # Aparece en la lista de solo activos.
    def _en_solo_activos() -> bool:
        lista = client.get(
            "/api/v1/deportistas?solo_activos=true&page_size=100", headers=headers
        ).json()
        return any(it["id"] == deportista_id for it in lista["items"])

    assert _en_solo_activos() is True

    # Baja -> activo=false, devuelve el detalle actualizado.
    resp = client.post(f"/api/v1/deportistas/{deportista_id}/baja", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["activo"] is False

    # Desaparece de solo_activos...
    assert _en_solo_activos() is False
    # ...pero por defecto (solo_activos=false) sigue listado.
    lista_todos = client.get("/api/v1/deportistas?page_size=100", headers=headers).json()
    assert any(it["id"] == deportista_id for it in lista_todos["items"])
    # ...y sigue accesible por id, con activo=false.
    detalle_baja = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers)
    assert detalle_baja.status_code == 200
    assert detalle_baja.json()["activo"] is False

    # Reactivar -> activo=true, vuelve a solo_activos.
    resp = client.post(f"/api/v1/deportistas/{deportista_id}/reactivar", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["activo"] is True
    assert _en_solo_activos() is True


@pytest.mark.db
def test_baja_es_idempotente() -> None:
    """Dar de baja a alguien ya inactivo NO es error (idempotente). Idem reactivar."""
    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    deportista_id = _crear_deportista_basico(client, headers)

    primera = client.post(f"/api/v1/deportistas/{deportista_id}/baja", headers=headers)
    assert primera.status_code == 200
    assert primera.json()["activo"] is False
    # Repetir la baja: sigue 200, sigue inactivo (sin error).
    segunda = client.post(f"/api/v1/deportistas/{deportista_id}/baja", headers=headers)
    assert segunda.status_code == 200
    assert segunda.json()["activo"] is False

    # Reactivar dos veces también es idempotente.
    r1 = client.post(f"/api/v1/deportistas/{deportista_id}/reactivar", headers=headers)
    assert r1.status_code == 200 and r1.json()["activo"] is True
    r2 = client.post(f"/api/v1/deportistas/{deportista_id}/reactivar", headers=headers)
    assert r2.status_code == 200 and r2.json()["activo"] is True


@pytest.mark.db
def test_baja_404_si_no_existe() -> None:
    """Baja/reactivar de un id inexistente en la org -> 404."""
    import uuid as _uuid

    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}
    fantasma = str(_uuid.uuid4())

    assert client.post(f"/api/v1/deportistas/{fantasma}/baja", headers=headers).status_code == 404
    assert (
        client.post(f"/api/v1/deportistas/{fantasma}/reactivar", headers=headers).status_code == 404
    )


@pytest.mark.db
def test_baja_reactivar_solo_admin_entrenador_403() -> None:
    """ENTRENADOR -> 403 en baja y reactivar (escritura SOLO ADMIN, C4)."""
    client = _client_or_skip()
    admin_token = _login_admin(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    deportista_id = _crear_deportista_basico(client, admin_headers)

    coach = client.post(
        "/api/v1/auth/login",
        json={"email": "coach@latinosport.bo", "password": "coach1234"},
    )
    if coach.status_code != 200:
        pytest.skip("Entrenador no sembrado")
    coach_headers = {"Authorization": f"Bearer {coach.json()['access_token']}"}

    assert (
        client.post(f"/api/v1/deportistas/{deportista_id}/baja", headers=coach_headers).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/deportistas/{deportista_id}/reactivar", headers=coach_headers
        ).status_code
        == 403
    )
    # El deportista sigue activo (el coach no pudo tocarlo).
    detalle = client.get(f"/api/v1/deportistas/{deportista_id}", headers=admin_headers).json()
    assert detalle["activo"] is True


@pytest.mark.db
def test_baja_conserva_historial_tutores_y_cuotas() -> None:
    """La baja es soft-delete: conserva tutores y cuotas (historial). Nunca borra."""
    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    deportista_id = _crear_deportista_basico(client, headers)

    # Genera cuotas de la org (idempotente) para tener historial asociado.
    client.post("/api/v1/cobranza/generar", headers=headers)

    antes = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers).json()
    tutores_antes = len(antes["tutores"])
    assert tutores_antes >= 1
    cuotas_antes = client.get(
        f"/api/v1/cobranza/cuotas?deportista_id={deportista_id}&page_size=100",
        headers=headers,
    ).json()["total"]

    # Baja.
    resp = client.post(f"/api/v1/deportistas/{deportista_id}/baja", headers=headers)
    assert resp.status_code == 200 and resp.json()["activo"] is False

    # Tutores y cuotas se conservan tras la baja (mismo conteo, nada borrado).
    despues = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers).json()
    assert len(despues["tutores"]) == tutores_antes
    cuotas_despues = client.get(
        f"/api/v1/cobranza/cuotas?deportista_id={deportista_id}&page_size=100",
        headers=headers,
    ).json()["total"]
    assert cuotas_despues == cuotas_antes


# --------------------------------------------------------------------------- #
# Edición completa de deportista: reconciliación de tutores (C3, Fase 3)
# Requiere BD + seed. Invariante de menores validado SERVER-SIDE.
# --------------------------------------------------------------------------- #
def _crear_deportista_con_tutores(client, headers, tutores: list[dict]) -> str:
    """Crea un deportista con la lista de tutores dada y devuelve su id."""
    import uuid as _uuid

    suc = client.get("/api/v1/sucursales", headers=headers).json()
    if not suc:
        pytest.skip("No hay sucursales; ¿seed ejecutado?")
    sucursal_id = suc[0]["id"]
    ci = f"CI-REC-{_uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/deportistas",
        headers=headers,
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Reconcilia Test",
            "ci": ci,
            "tutores": tutores,
            "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.db
def test_put_sin_tutores_no_los_toca() -> None:
    """`tutores` ausente del body -> NO se tocan los tutores (comportamiento previo)."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(
        client, headers, [{"nombres": "Mamá", "telefono": "111", "parentesco": "Madre"}]
    )
    antes = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    assert len(antes["tutores"]) == 1

    # PUT solo de un campo del deportista: los tutores quedan intactos.
    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={"contacto_emergencia": "777-999"},
    )
    assert upd.status_code == 200, upd.text
    j = upd.json()
    assert j["contacto_emergencia"] == "777-999"
    assert len(j["tutores"]) == 1
    assert j["tutores"][0]["nombres"] == "Mamá"


@pytest.mark.db
def test_put_edita_datos_ficha_y_anade_tutor() -> None:
    """Editar datos + ficha_medica + añadir un tutor nuevo (sin id) en un solo PUT."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(
        client, headers, [{"nombres": "Papá", "telefono": "111", "parentesco": "Padre"}]
    )
    detalle = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    tutor_existente = detalle["tutores"][0]

    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={
            "nombres": "Nombre Editado",
            "ficha_medica": {"tipo_sangre": "O+", "alergias": "polen"},
            "tutores": [
                # Conserva al existente (por id).
                {
                    "id": tutor_existente["id"],
                    "nombres": tutor_existente["nombres"],
                    "telefono": tutor_existente["telefono"],
                    "parentesco": "Padre",
                },
                # Tutor NUEVO sin id.
                {"nombres": "Tía Nueva", "telefono": "222", "parentesco": "Tía"},
            ],
        },
    )
    assert upd.status_code == 200, upd.text
    j = upd.json()
    assert j["nombres"] == "NOMBRE EDITADO"  # el nombre del deportista se guarda en MAYÚSCULAS
    assert j["ficha_medica"]["tipo_sangre"] == "O+"
    nombres = {t["nombres"] for t in j["tutores"]}
    assert nombres == {"Papá", "Tía Nueva"}
    assert len(j["tutores"]) == 2


@pytest.mark.db
def test_put_edita_tutor_existente_por_id() -> None:
    """Tutor con id -> se actualiza el tutor (nombres/teléfono) y su vínculo."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(
        client,
        headers,
        [{"nombres": "Original", "telefono": "111", "parentesco": "Madre"}],
    )
    detalle = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    tutor = detalle["tutores"][0]

    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={
            "tutores": [
                {
                    "id": tutor["id"],
                    "nombres": "Renombrada",
                    "telefono": "999",
                    "parentesco": "Tutora legal",
                    "responsable_pago": True,
                }
            ]
        },
    )
    assert upd.status_code == 200, upd.text
    t = upd.json()["tutores"]
    assert len(t) == 1
    assert t[0]["id"] == tutor["id"]  # mismo tutor (editado, no recreado)
    assert t[0]["nombres"] == "Renombrada"
    assert t[0]["telefono"] == "999"
    assert t[0]["parentesco"] == "Tutora legal"
    assert t[0]["responsable_pago"] is True


@pytest.mark.db
def test_put_reusa_tutor_por_ci_no_duplica() -> None:
    """Tutor sin id pero con CI ya existente en la org -> se REUSA (no se duplica)."""
    import uuid as _uuid

    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    ci_compartido = f"CI-TUT-{_uuid.uuid4().hex[:10]}"
    # Deportista A con un tutor con CI conocido.
    did_a = _crear_deportista_con_tutores(
        client,
        headers,
        [{"nombres": "Tutor Compartido", "telefono": "111", "ci": ci_compartido}],
    )
    detalle_a = client.get(f"/api/v1/deportistas/{did_a}", headers=headers).json()
    tutor_id_compartido = detalle_a["tutores"][0]["id"]

    # Deportista B con su propio tutor; luego vía PUT añadimos un tutor sin id pero
    # con el MISMO CI -> debe reusar el tutor existente (mismo id), no crear otro.
    did_b = _crear_deportista_con_tutores(
        client, headers, [{"nombres": "Mamá B", "telefono": "222"}]
    )
    detalle_b = client.get(f"/api/v1/deportistas/{did_b}", headers=headers).json()
    tutor_b = detalle_b["tutores"][0]

    upd = client.put(
        f"/api/v1/deportistas/{did_b}",
        headers=headers,
        json={
            "tutores": [
                {
                    "id": tutor_b["id"],
                    "nombres": tutor_b["nombres"],
                    "telefono": tutor_b["telefono"],
                },
                # Sin id, con CI ya existente -> reusa el tutor compartido.
                {"nombres": "Tutor Compartido", "telefono": "333", "ci": ci_compartido},
            ]
        },
    )
    assert upd.status_code == 200, upd.text
    tutores_b = upd.json()["tutores"]
    ids = {t["id"] for t in tutores_b}
    assert tutor_id_compartido in ids  # se reusó el mismo registro tutor
    assert len(tutores_b) == 2


@pytest.mark.db
def test_put_desvincula_tutor_dejando_uno_ok() -> None:
    """Quitar un tutor de la lista (omitirlo) lo desvincula; deja ≥1 -> OK."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(
        client,
        headers,
        [
            {"nombres": "Tutor Uno", "telefono": "111", "parentesco": "Padre"},
            {"nombres": "Tutor Dos", "telefono": "222", "parentesco": "Madre"},
        ],
    )
    detalle = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    assert len(detalle["tutores"]) == 2

    # El tutor del consentimiento es el PRIMERO creado (crear_deportista lo ata así);
    # conservamos ese y desvinculamos al otro.
    cons_tutor = next(t for t in detalle["tutores"] if t["nombres"] == "Tutor Uno")

    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={
            "tutores": [
                {
                    "id": cons_tutor["id"],
                    "nombres": cons_tutor["nombres"],
                    "telefono": cons_tutor["telefono"],
                }
            ]
        },
    )
    assert upd.status_code == 200, upd.text
    t = upd.json()["tutores"]
    assert len(t) == 1
    assert t[0]["nombres"] == "Tutor Uno"


@pytest.mark.db
def test_put_quitar_todos_los_tutores_422() -> None:
    """Lista de tutores vacía -> 422 (invariante: ≥1 tutor siempre). Server-side."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(client, headers, [{"nombres": "Único", "telefono": "111"}])

    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={"tutores": []},
    )
    assert upd.status_code == 422, upd.text

    # El tutor original sigue intacto (nada se persistió a medias).
    detalle = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    assert len(detalle["tutores"]) == 1
    assert detalle["tutores"][0]["nombres"] == "Único"


@pytest.mark.db
def test_put_quitar_tutor_del_consentimiento_422() -> None:
    """Desvincular al tutor atado al consentimiento -> 422 (invariante). Server-side.

    El consentimiento se ata al PRIMER tutor en el alta. Intentamos dejar SOLO al otro
    tutor (omitiendo al del consentimiento): debe fallar con 422 aunque quede ≥1 tutor.
    """
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {_login_admin(client)}"}

    did = _crear_deportista_con_tutores(
        client,
        headers,
        [
            {"nombres": "Firmante", "telefono": "111", "parentesco": "Madre"},
            {"nombres": "Secundario", "telefono": "222", "parentesco": "Padre"},
        ],
    )
    detalle = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    secundario = next(t for t in detalle["tutores"] if t["nombres"] == "Secundario")

    # Intentar quedarnos SOLO con el secundario -> quita al firmante del consentimiento.
    upd = client.put(
        f"/api/v1/deportistas/{did}",
        headers=headers,
        json={
            "tutores": [
                {
                    "id": secundario["id"],
                    "nombres": secundario["nombres"],
                    "telefono": secundario["telefono"],
                }
            ]
        },
    )
    assert upd.status_code == 422, upd.text

    # Nada se persistió: siguen los 2 tutores.
    despues = client.get(f"/api/v1/deportistas/{did}", headers=headers).json()
    assert len(despues["tutores"]) == 2
