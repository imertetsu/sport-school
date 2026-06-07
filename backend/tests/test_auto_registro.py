"""Tests de Auto-registro (contratos C2/C3) — versión EN SISTEMA.

- Tests de schema (sin BD): validación dura de consentimiento aceptado + datos
  mínimos del tutor -> 422 lógico.
- Tests marcados `db`: flujo end-to-end contra la API real (requieren BD migrada
  con 0008 + seed). Skip si no hay BD.
    * entrenador crea solicitud PENDIENTE
    * aprobar (ADMIN) crea el deportista real y deja APROBADA con `deportista_id`
    * re-aprobar -> 409
    * rechazar -> RECHAZADA con motivo
    * 403 entrenador en aprobar/rechazar
    * 422 sin consentimiento aceptado
    * entrenador con `sucursal_sugerida_id` fuera de su alcance -> 403

El seed se asume ejecutado (admin@latinosport.bo / coach@latinosport.bo). NO hay token ni
endpoint público: todo es autenticado con Bearer.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from app.schemas.registro import SolicitudCreate
from pydantic import ValidationError

# --------------------------------------------------------------------------- #
# Validación dura a nivel schema (sin BD)
# --------------------------------------------------------------------------- #
_BASE_BODY: dict[str, Any] = {
    "nombres": "Camila",
    # El CI del DEPORTISTA es OBLIGATORIO también en la captura de auto-registro.
    "ci": "CI-CAMILA-01",
    "tutor": {"nombres": "María Rojas", "telefono": "777", "parentesco": "Madre"},
}


def test_solicitud_schema_ok() -> None:
    body = dict(_BASE_BODY)
    body["consentimiento"] = {"aceptado": True, "version_terminos": "v1"}
    obj = SolicitudCreate(**body)  # type: ignore[arg-type]
    assert obj.consentimiento.aceptado is True
    assert obj.tutor.nombres == "María Rojas"


def test_solicitud_schema_consentimiento_no_aceptado_falla() -> None:
    """`consentimiento.aceptado=false` -> ValidationError (=> 422 en la API)."""
    body = dict(_BASE_BODY)
    body["consentimiento"] = {"aceptado": False, "version_terminos": "v1"}
    with pytest.raises(ValidationError):
        SolicitudCreate(**body)  # type: ignore[arg-type]


def test_solicitud_schema_sin_consentimiento_falla() -> None:
    """Sin objeto consentimiento -> ValidationError (=> 422)."""
    body = dict(_BASE_BODY)
    with pytest.raises(ValidationError):
        SolicitudCreate(**body)  # type: ignore[arg-type]


def test_solicitud_schema_tutor_sin_nombres_falla() -> None:
    """Tutor sin nombres (dato mínimo) -> ValidationError (=> 422)."""
    body = {
        "nombres": "Camila",
        "ci": "CI-CAMILA-02",
        "tutor": {"telefono": "777"},
        "consentimiento": {"aceptado": True, "version_terminos": "v1"},
    }
    with pytest.raises(ValidationError):
        SolicitudCreate(**body)  # type: ignore[arg-type]


def test_solicitud_schema_sin_ci_deportista_falla() -> None:
    """CI del DEPORTISTA OBLIGATORIO en la captura: sin `ci` (o vacío) -> 422."""
    base = {
        "nombres": "Camila",
        "tutor": {"nombres": "María Rojas", "telefono": "777"},
        "consentimiento": {"aceptado": True, "version_terminos": "v1"},
    }
    # Sin `ci`.
    with pytest.raises(ValidationError):
        SolicitudCreate(**base)  # type: ignore[arg-type]
    # CI vacío / solo espacios.
    for ci_vacio in ("", "   "):
        body = dict(base)
        body["ci"] = ci_vacio
        with pytest.raises(ValidationError):
            SolicitudCreate(**body)  # type: ignore[arg-type]


def test_solicitud_schema_tutor_sin_ci_ok() -> None:
    """El TUTOR de la solicitud sin CI SÍ se permite (su CI es opcional)."""
    body = dict(_BASE_BODY)
    body["consentimiento"] = {"aceptado": True, "version_terminos": "v1"}
    # Tutor explícitamente sin `ci`.
    body["tutor"] = {"nombres": "María Rojas", "telefono": "777"}
    obj = SolicitudCreate(**body)  # type: ignore[arg-type]
    assert obj.ci == "CI-CAMILA-01"
    assert obj.tutor.ci is None


# --------------------------------------------------------------------------- #
# Flujo end-to-end contra la API real (requiere BD + seed)
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado + seed")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _login(client, email: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        pytest.skip(f"Login {email} falló ({resp.status_code}); ¿seed ejecutado?")
    return resp.json()["access_token"]


def _login_admin(client) -> str:
    return _login(client, "admin@latinosport.bo", "admin1234")


def _login_coach(client) -> str:
    return _login(client, "coach@latinosport.bo", "coach1234")


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _primera_sucursal(client, token: str) -> str:
    suc = client.get("/api/v1/sucursales", headers=_hdr(token)).json()
    if not suc:
        pytest.skip("No hay sucursales; ¿seed ejecutado?")
    return suc[0]["id"]


def _solicitud_body(sucursal_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ap_paterno": "Test",
        "ap_materno": "Auto",
        "nombres": f"Registro {uuid.uuid4().hex[:8]}",
        "ci": f"TST{uuid.uuid4().hex[:7]}",
        "fecha_nac": "2013-05-10",
        "disciplina": "Fútbol",
        "tutor": {"nombres": "Tutor Test", "telefono": "777", "parentesco": "Madre"},
        "consentimiento": {"aceptado": True, "version_terminos": "v1"},
    }
    if sucursal_id is not None:
        body["sucursal_sugerida_id"] = sucursal_id
    return body


@pytest.mark.db
def test_listar_solicitudes_sin_token_401() -> None:
    client = _client_or_skip()
    resp = client.get("/api/v1/solicitudes")
    assert resp.status_code == 401


@pytest.mark.db
def test_entrenador_crea_solicitud() -> None:
    """Un ENTRENADOR captura una solicitud PENDIENTE en su sucursal."""
    client = _client_or_skip()
    coach = _login_coach(client)
    sucursal_id = _primera_sucursal(client, coach)
    resp = client.post(
        "/api/v1/solicitudes", headers=_hdr(coach), json=_solicitud_body(sucursal_id)
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["estado"] == "PENDIENTE"
    assert data["deportista_id"] is None
    assert data["tutor"]["nombres"] == "Tutor Test"


@pytest.mark.db
def test_crear_solicitud_sin_consentimiento_422() -> None:
    """Sin consentimiento aceptado -> 422."""
    client = _client_or_skip()
    admin = _login_admin(client)
    body = _solicitud_body()
    body["consentimiento"] = {"aceptado": False, "version_terminos": "v1"}
    resp = client.post("/api/v1/solicitudes", headers=_hdr(admin), json=body)
    assert resp.status_code == 422


@pytest.mark.db
def test_entrenador_sucursal_fuera_de_alcance_403() -> None:
    """Entrenador con `sucursal_sugerida_id` fuera de su alcance -> 403."""
    client = _client_or_skip()
    coach = _login_coach(client)
    # UUID aleatorio: nunca está en las sucursales del token del coach.
    body = _solicitud_body(str(uuid.uuid4()))
    resp = client.post("/api/v1/solicitudes", headers=_hdr(coach), json=body)
    assert resp.status_code == 403


@pytest.mark.db
def test_aprobar_crea_deportista_y_marca_aprobada() -> None:
    """Aprobar (ADMIN) crea el deportista real y deja APROBADA con `deportista_id`."""
    client = _client_or_skip()
    admin = _login_admin(client)
    sucursal_id = _primera_sucursal(client, admin)

    # Crear solicitud (como admin) -> PENDIENTE
    crear = client.post(
        "/api/v1/solicitudes", headers=_hdr(admin), json=_solicitud_body(sucursal_id)
    )
    assert crear.status_code == 201, crear.text
    solicitud_id = crear.json()["id"]

    # Aprobar -> crea deportista real
    aprobar = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/aprobar",
        headers=_hdr(admin),
        json={"sucursal_id": sucursal_id, "monto_mensual": "250.00"},
    )
    assert aprobar.status_code == 200, aprobar.text
    deportista = aprobar.json()
    deportista_id = deportista["id"]
    assert deportista["nombres"]

    # La solicitud queda APROBADA con deportista_id
    detalle = client.get(f"/api/v1/solicitudes/{solicitud_id}", headers=_hdr(admin)).json()
    assert detalle["estado"] == "APROBADA"
    assert detalle["deportista_id"] == deportista_id

    # El deportista existe en Deportistas (reutilización de la creación)
    al = client.get(f"/api/v1/deportistas/{deportista_id}", headers=_hdr(admin))
    assert al.status_code == 200


@pytest.mark.db
def test_re_aprobar_409() -> None:
    """Re-aprobar una solicitud ya resuelta -> 409."""
    client = _client_or_skip()
    admin = _login_admin(client)
    sucursal_id = _primera_sucursal(client, admin)

    crear = client.post(
        "/api/v1/solicitudes", headers=_hdr(admin), json=_solicitud_body(sucursal_id)
    )
    solicitud_id = crear.json()["id"]
    body = {"sucursal_id": sucursal_id}
    primera = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/aprobar", headers=_hdr(admin), json=body
    )
    assert primera.status_code == 200, primera.text
    segunda = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/aprobar", headers=_hdr(admin), json=body
    )
    assert segunda.status_code == 409


@pytest.mark.db
def test_rechazar_marca_rechazada() -> None:
    """Rechazar (ADMIN) deja RECHAZADA con motivo; re-rechazar -> 409."""
    client = _client_or_skip()
    admin = _login_admin(client)
    sucursal_id = _primera_sucursal(client, admin)

    crear = client.post(
        "/api/v1/solicitudes", headers=_hdr(admin), json=_solicitud_body(sucursal_id)
    )
    solicitud_id = crear.json()["id"]
    rechazar = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/rechazar",
        headers=_hdr(admin),
        json={"motivo": "Datos incompletos"},
    )
    assert rechazar.status_code == 200, rechazar.text
    assert rechazar.json()["estado"] == "RECHAZADA"
    assert rechazar.json()["motivo_rechazo"] == "Datos incompletos"

    # Re-rechazar -> 409
    re = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/rechazar",
        headers=_hdr(admin),
        json={"motivo": "otra vez"},
    )
    assert re.status_code == 409


@pytest.mark.db
def test_entrenador_no_puede_aprobar_ni_rechazar_403() -> None:
    """ENTRENADOR en aprobar/rechazar -> 403 (require_role ADMIN)."""
    client = _client_or_skip()
    admin = _login_admin(client)
    coach = _login_coach(client)
    sucursal_id = _primera_sucursal(client, admin)

    crear = client.post(
        "/api/v1/solicitudes", headers=_hdr(admin), json=_solicitud_body(sucursal_id)
    )
    solicitud_id = crear.json()["id"]

    apr = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/aprobar",
        headers=_hdr(coach),
        json={"sucursal_id": sucursal_id},
    )
    assert apr.status_code == 403

    rech = client.post(
        f"/api/v1/solicitudes/{solicitud_id}/rechazar",
        headers=_hdr(coach),
        json={"motivo": "no"},
    )
    assert rech.status_code == 403
