"""Tests del epic Super Admin (consola de plataforma).

Dos niveles:
1. **Puros (sin BD):** claims del token de plataforma, fail-closed de
   `require_superadmin` (no fija el GUC), `get_current_user` con/sin org_id.
2. **`@db` (requieren Postgres migrado a 0012 + seed):** login de plataforma,
   crear/suspender/reactivar escuela, RLS fail-closed con token SUPERADMIN, login
   de escuela suspendida, cron salta suspendidas, CRUD de super admins, idempotencia
   del seed.

Los `@db` se omiten (skip) si no hay BD alcanzable (ver conftest).
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from app.core.security import (
    create_access_token,
    create_platform_token,
    decode_access_token,
    hash_password,
)
from app.core.tenant import CurrentUser, get_current_user, require_superadmin
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# 1) Tests puros (sin BD)
# --------------------------------------------------------------------------- #
def _creds(token: str):
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_platform_token_sin_org_id() -> None:
    """El token de plataforma lleva role=SUPERADMIN y NO lleva org_id ni sucursal_ids."""
    token = create_platform_token("11111111-1111-1111-1111-111111111111")
    payload = decode_access_token(token)
    assert payload["role"] == "SUPERADMIN"
    assert payload["sub"] == "11111111-1111-1111-1111-111111111111"
    assert "org_id" not in payload
    assert "sucursal_ids" not in payload


def test_get_current_user_superadmin_sin_org() -> None:
    """get_current_user acepta token SUPERADMIN sin org_id (org_id = "")."""
    token = create_platform_token("22222222-2222-2222-2222-222222222222")
    user = get_current_user(_creds(token))
    assert user.role == "SUPERADMIN"
    assert user.org_id == ""  # nunca se usa como contexto


def test_get_current_user_escuela_sin_org_id_401() -> None:
    """Un token de ESCUELA (rol no SUPERADMIN) sin org_id sigue siendo 401 (sin regresión)."""
    import jwt as pyjwt
    from app.core.config import settings

    # Token manual sin org_id pero con rol de escuela.
    bad = pyjwt.encode(
        {"sub": "u1", "role": "ADMIN"}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(HTTPException) as exc:
        get_current_user(_creds(bad))
    assert exc.value.status_code == 401


def test_require_superadmin_rechaza_rol_escuela() -> None:
    """require_superadmin -> 403 si el rol no es SUPERADMIN."""
    user = CurrentUser(user_id="u1", org_id="o1", role="ADMIN")
    with pytest.raises(HTTPException) as exc:
        require_superadmin(user)
    assert exc.value.status_code == 403


def test_require_superadmin_no_fija_guc() -> None:
    """require_superadmin NO depende de set_tenant_context (no fija el GUC).

    Se verifica estructuralmente: la dependencia recibe `get_current_user` (no
    `set_tenant_context`) y no recibe una `Session`. Así nunca ejecuta set_config.
    """
    import inspect

    sig = inspect.signature(require_superadmin)
    params = list(sig.parameters)
    assert params == ["user"], "require_superadmin no debe pedir db/Session"
    # El default de `user` debe ser Depends(get_current_user), NO set_tenant_context.
    default = sig.parameters["user"].default
    assert default.dependency is get_current_user


def test_access_token_escuela_sigue_con_org_id() -> None:
    """create_access_token (login de escuela) sigue inyectando org_id (sin regresión)."""
    token = create_access_token(user_id="u1", org_id="o1", role="ADMIN", sucursal_ids=["s1"])
    payload = decode_access_token(token)
    assert payload["org_id"] == "o1"
    assert payload["sucursal_ids"] == ["s1"]


# --------------------------------------------------------------------------- #
# 2) Tests @db (requieren Postgres migrado a 0012)
# --------------------------------------------------------------------------- #
pytest_db = pytest.mark.db

PLAT_EMAIL = "ops-test@latinosport.bo"
PLAT_PASS = "ops-test-1234"


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado a 0012")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def plataforma_admin(owner_engine: Engine):
    """Crea (como owner) un super admin de plataforma para los tests. Limpia al final."""
    admin_id = uuid.uuid4()
    pwd_hash = hash_password(PLAT_PASS)
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM plataforma_admin WHERE email = :e"), {"e": PLAT_EMAIL})
        conn.execute(
            text(
                "INSERT INTO plataforma_admin (id, email, password_hash, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id, :email, :ph, 'Ops Test', true, now(), now())"
            ),
            {"id": str(admin_id), "email": PLAT_EMAIL, "ph": pwd_hash},
        )
    yield {"id": admin_id, "email": PLAT_EMAIL, "password": PLAT_PASS}
    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM plataforma_auditoria WHERE admin_id = :a"), {"a": str(admin_id)}
        )
        conn.execute(text("DELETE FROM plataforma_admin WHERE id = :id"), {"id": str(admin_id)})


def _platform_token(client, admin) -> str:
    resp = client.post(
        "/api/v1/plataforma/login",
        json={"email": admin["email"], "password": admin["password"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["admin"]["email"] == admin["email"]
    return str(data["access_token"])


@pytest_db
def test_login_plataforma_ok_y_401(plataforma_admin: dict) -> None:
    client = _client_or_skip()
    # ok
    token = _platform_token(client, plataforma_admin)
    payload = decode_access_token(token)
    assert payload["role"] == "SUPERADMIN"
    assert "org_id" not in payload
    # clave mala -> 401
    bad = client.post(
        "/api/v1/plataforma/login",
        json={"email": plataforma_admin["email"], "password": "incorrecta"},
    )
    assert bad.status_code == 401


@pytest_db
def test_escuelas_requiere_superadmin(plataforma_admin: dict) -> None:
    client = _client_or_skip()
    # sin token -> 401
    assert client.get("/api/v1/plataforma/escuelas").status_code == 401
    # token de escuela (admin del seed) -> 403
    escuela_login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@latinosport.bo", "password": "admin1234"},
    )
    if escuela_login.status_code == 200:
        escuela_token = escuela_login.json()["access_token"]
        resp = client.get(
            "/api/v1/plataforma/escuelas",
            headers={"Authorization": f"Bearer {escuela_token}"},
        )
        assert resp.status_code == 403
    # token de plataforma -> 200
    token = _platform_token(client, plataforma_admin)
    ok = client.get("/api/v1/plataforma/escuelas", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert isinstance(ok.json(), list)


@pytest_db
def test_superadmin_no_ve_tablas_tenant(plataforma_admin: dict) -> None:
    """RLS fail-closed: con token SUPERADMIN, /alumnos no expone datos (GUC no fijado)."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    resp = client.get("/api/v1/alumnos", headers={"Authorization": f"Bearer {token}"})
    # /alumnos exige rol ADMIN/ENTRENADOR -> SUPERADMIN no pasa el require_role (403),
    # y aunque pasara, RLS daría 0 filas. Lo crítico: NUNCA expone alumnos de una org.
    assert resp.status_code in (403, 200)
    if resp.status_code == 200:
        assert resp.json().get("items") == []


@pytest_db
def test_crear_escuela_inserta_admin_con_org_correcta(
    plataforma_admin: dict, owner_engine: Engine
) -> None:
    """Crear escuela => org ACTIVA + admin con el org_id de la org nueva; admin loguea."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    suf = uuid.uuid4().hex[:8]
    admin_email = f"director-{suf}@escuela.bo"
    body = {
        "nombre": f"Escuela Test {suf}",
        "pais": "BO",
        "moneda": "BOB",
        "admin_nombre": "Director Test",
        "admin_email": admin_email,
        "admin_password": "director1234",
    }
    resp = client.post(
        "/api/v1/plataforma/escuelas",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    org_id = data["id"]
    assert data["estado"] == "ACTIVA"
    assert data["admin"]["email"] == admin_email

    try:
        # email duplicado -> 409
        dup = client.post(
            "/api/v1/plataforma/escuelas",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        assert dup.status_code == 409, dup.text

        # el admin nuevo puede loguearse y su token apunta a la org nueva
        login = client.post(
            "/api/v1/auth/login",
            json={"email": admin_email, "password": "director1234"},
        )
        assert login.status_code == 200, login.text
        tok = login.json()["access_token"]
        assert decode_access_token(tok)["org_id"] == org_id

        # auditoría CREAR_ESCUELA registrada (tabla sin RLS)
        with owner_engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM plataforma_auditoria "
                    "WHERE accion='CREAR_ESCUELA' AND org_id=:o"
                ),
                {"o": org_id},
            ).scalar_one()
        assert n == 1
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": org_id})
            conn.execute(text("DELETE FROM plataforma_auditoria WHERE org_id = :o"), {"o": org_id})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": org_id})


@pytest_db
def test_suspender_reactivar_idempotente_y_404(
    plataforma_admin: dict, owner_engine: Engine
) -> None:
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    headers = {"Authorization": f"Bearer {token}"}

    # 404 en org inexistente
    falsa = uuid.uuid4()
    assert (
        client.post(f"/api/v1/plataforma/escuelas/{falsa}/suspender", headers=headers).status_code
        == 404
    )

    # org de prueba
    org_id = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, estado, created_at, updated_at) "
                "VALUES (:id, 'Org Susp Test', 'BO', 'BOB', 'ANIVERSARIO', true, 'ACTIVA', "
                "now(), now())"
            ),
            {"id": str(org_id)},
        )
    try:
        # suspender (2x -> idempotente)
        r1 = client.post(f"/api/v1/plataforma/escuelas/{org_id}/suspender", headers=headers)
        assert r1.status_code == 200 and r1.json()["estado"] == "SUSPENDIDA"
        r2 = client.post(f"/api/v1/plataforma/escuelas/{org_id}/suspender", headers=headers)
        assert r2.json()["estado"] == "SUSPENDIDA"
        # reactivar (2x -> idempotente)
        r3 = client.post(f"/api/v1/plataforma/escuelas/{org_id}/reactivar", headers=headers)
        assert r3.json()["estado"] == "ACTIVA"
        r4 = client.post(f"/api/v1/plataforma/escuelas/{org_id}/reactivar", headers=headers)
        assert r4.json()["estado"] == "ACTIVA"
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM plataforma_auditoria WHERE org_id = :o"), {"o": str(org_id)}
            )
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


@pytest_db
def test_login_escuela_suspendida_403(plataforma_admin: dict, owner_engine: Engine) -> None:
    """Login de escuela con org SUSPENDIDA -> 403; reactivar -> vuelve a loguear."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    headers = {"Authorization": f"Bearer {token}"}

    suf = uuid.uuid4().hex[:8]
    admin_email = f"susp-{suf}@escuela.bo"
    org_id = client.post(
        "/api/v1/plataforma/escuelas",
        headers=headers,
        json={
            "nombre": f"Escuela Susp {suf}",
            "admin_nombre": "Dir",
            "admin_email": admin_email,
            "admin_password": "dir1234",
        },
    ).json()["id"]
    try:
        # login ok mientras ACTIVA
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": admin_email, "password": "dir1234"}
            ).status_code
            == 200
        )
        # suspender -> login 403
        client.post(f"/api/v1/plataforma/escuelas/{org_id}/suspender", headers=headers)
        susp = client.post("/api/v1/auth/login", json={"email": admin_email, "password": "dir1234"})
        assert susp.status_code == 403
        # reactivar -> login 200
        client.post(f"/api/v1/plataforma/escuelas/{org_id}/reactivar", headers=headers)
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": admin_email, "password": "dir1234"}
            ).status_code
            == 200
        )
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": org_id})
            conn.execute(text("DELETE FROM plataforma_auditoria WHERE org_id = :o"), {"o": org_id})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": org_id})


@pytest_db
def test_cron_salta_orgs_suspendidas(owner_engine: Engine) -> None:
    """cobranza_diaria no procesa orgs SUSPENDIDA (no aparecen en el conteo)."""
    from app.workers import tasks

    org_id = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, estado, created_at, updated_at) "
                "VALUES (:id, 'Org Cron Susp', 'BO', 'BOB', 'ANIVERSARIO', true, 'SUSPENDIDA', "
                "now(), now())"
            ),
            {"id": str(org_id)},
        )
    try:
        # El cron lista solo ACTIVA: la org suspendida no debe ser procesada. No falla
        # y el resultado es un dict (las orgs ACTIVA del seed sí se procesan).
        res = tasks.cobranza_diaria()
        assert isinstance(res, dict) and "orgs" in res
        # Verifica que NO se generaron cuotas para la org suspendida.
        with owner_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM cuota WHERE org_id = :o"), {"o": str(org_id)}
            ).scalar_one()
        assert n == 0
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


@pytest_db
def test_crud_super_admins(plataforma_admin: dict, owner_engine: Engine) -> None:
    """Listar (sin password_hash), crear (409 dup), salvaguarda >=1 activo."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    headers = {"Authorization": f"Bearer {token}"}

    # listar -> nunca expone password_hash
    lista = client.get("/api/v1/plataforma/admins", headers=headers)
    assert lista.status_code == 200
    for item in lista.json():
        assert "password_hash" not in item

    # crear
    suf = uuid.uuid4().hex[:8]
    nuevo_email = f"nuevo-{suf}@latinosport.bo"
    created = client.post(
        "/api/v1/plataforma/admins",
        headers=headers,
        json={"nombre": "Nuevo", "email": nuevo_email, "password": "nuevo1234"},
    )
    assert created.status_code == 201, created.text
    nuevo_id = created.json()["id"]
    assert "password_hash" not in created.json()
    try:
        # email duplicado -> 409
        dup = client.post(
            "/api/v1/plataforma/admins",
            headers=headers,
            json={"nombre": "Otro", "email": nuevo_email, "password": "x1234567"},
        )
        assert dup.status_code == 409

        # activar/desactivar idempotente
        d1 = client.post(f"/api/v1/plataforma/admins/{nuevo_id}/desactivar", headers=headers)
        assert d1.status_code == 200 and d1.json()["activo"] is False
        d2 = client.post(f"/api/v1/plataforma/admins/{nuevo_id}/desactivar", headers=headers)
        assert d2.json()["activo"] is False
        a1 = client.post(f"/api/v1/plataforma/admins/{nuevo_id}/activar", headers=headers)
        assert a1.json()["activo"] is True

        # 404 en id inexistente
        assert (
            client.post(
                f"/api/v1/plataforma/admins/{uuid.uuid4()}/activar", headers=headers
            ).status_code
            == 404
        )
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM plataforma_admin WHERE id = :id"), {"id": nuevo_id})


@pytest_db
def test_salvaguarda_ultimo_admin_activo(owner_engine: Engine) -> None:
    """Desactivar al ÚLTIMO super admin activo -> 409 (siempre >=1 activo).

    Aísla el conteo: desactiva todos los demás como owner, deja uno solo activo y
    pide desactivarlo vía API -> 409.
    """
    client = _client_or_skip()
    solo_id = uuid.uuid4()
    solo_email = f"solo-{uuid.uuid4().hex[:8]}@latinosport.bo"
    pwd = "solo12345"
    with owner_engine.begin() as conn:
        # snapshot de quiénes estaban activos para restaurarlos al final
        previos = [
            str(r)
            for r in conn.execute(text("SELECT id FROM plataforma_admin WHERE activo = true"))
            .scalars()
            .all()
        ]
        conn.execute(text("UPDATE plataforma_admin SET activo = false WHERE activo = true"))
        conn.execute(
            text(
                "INSERT INTO plataforma_admin (id, email, password_hash, nombre, activo, "
                "created_at, updated_at) VALUES (:id, :e, :ph, 'Solo', true, now(), now())"
            ),
            {"id": str(solo_id), "e": solo_email, "ph": hash_password(pwd)},
        )
    try:
        login = client.post("/api/v1/plataforma/login", json={"email": solo_email, "password": pwd})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post(f"/api/v1/plataforma/admins/{solo_id}/desactivar", headers=headers)
        assert resp.status_code == 409, resp.text
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM plataforma_admin WHERE id = :id"), {"id": str(solo_id)})
            if previos:
                conn.execute(
                    text("UPDATE plataforma_admin SET activo = true WHERE id = ANY(:ids)"),
                    {"ids": previos},
                )


@pytest_db
def test_seed_plataforma_idempotente(owner_engine: Engine, monkeypatch: Any) -> None:
    """`seed_plataforma` 2x no falla ni duplica (idempotente por email)."""
    from app.core.config import settings

    email = f"seed-{uuid.uuid4().hex[:8]}@latinosport.bo"
    monkeypatch.setattr(settings, "platform_admin_email", email, raising=False)
    monkeypatch.setattr(settings, "platform_admin_password", "seed12345", raising=False)
    from app.seed_plataforma import seed_plataforma

    try:
        seed_plataforma()
        seed_plataforma()  # 2ª vez: no debe fallar ni duplicar
        with owner_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM plataforma_admin WHERE email = :e"), {"e": email}
            ).scalar_one()
        assert n == 1
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM plataforma_admin WHERE email = :e"), {"e": email})


# --------------------------------------------------------------------------- #
# 3) Tests @db a nivel SERVICIO / RLS directo (más finos que los de TestClient)
#
# Los de arriba ejercitan el epic end-to-end vía HTTP; estos demuestran, a nivel
# de SQL/servicio, las invariantes de seguridad del epic:
#   - RLS fail-closed del super admin sobre tablas tenant (sin pasar por require_role).
#   - plataforma_admin / plataforma_auditoria NO tienen RLS (se leen/escriben sin GUC).
#   - crear_escuela: org+admin con el org_id correcto, visible SOLO bajo su GUC,
#     login_lookup lo encuentra, 409 dup, 1 fila de auditoría.
#   - desactivar_admin / login_plataforma a nivel servicio (lanzan HTTPException).
# --------------------------------------------------------------------------- #
def _set_org(conn: Any, org: uuid.UUID) -> None:
    """Fija `app.current_org` para la tx (SET LOCAL vía set_config 3er arg=true)."""
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


@pytest_db
def test_superadmin_rls_fail_closed_sobre_tabla_tenant(app_engine: Engine, two_orgs: dict) -> None:
    """CRÍTICO: el camino del super admin (Session SIN `app.current_org`) deja RLS
    fail-closed sobre `alumno`.

    `require_superadmin` NUNCA fija el GUC; aquí lo reproducimos abriendo una sesión
    del rol app sin contexto de tenant. Aunque `two_orgs` sembró 1 alumno por org
    (como owner, saltando RLS), una query sin GUC debe devolver 0 filas (NULLIF →
    NULL → 0). Si esto devolviera >0, el super admin podría ver datos de cualquier
    escuela: fuga de tenant.
    """
    with Session(app_engine, expire_on_commit=False) as db:
        # Sin set_config('app.current_org', ...): es EXACTAMENTE lo que ocurre bajo
        # require_superadmin (no encadena set_tenant_context).
        n_alumnos = db.execute(text("SELECT count(*) FROM alumno")).scalar_one()
        n_insc = db.execute(text("SELECT count(*) FROM inscripcion")).scalar_one()
    assert n_alumnos == 0, "sin contexto de tenant, alumno debe devolver 0 filas (fail-closed)"
    assert n_insc == 0, "fail-closed también en otras tablas tenant"


@pytest_db
def test_plataforma_tablas_sin_rls_se_leen_sin_contexto(app_engine: Engine) -> None:
    """`plataforma_admin` y `plataforma_auditoria` NO tienen RLS: se insertan/leen
    sin GUC (a diferencia de las tablas tenant, fail-closed).

    Inserta un PlataformaAdmin con el rol app SIN contexto y lo lee de vuelta.
    """
    from app.models.plataforma_admin import PlataformaAdmin
    from app.models.plataforma_auditoria import PlataformaAuditoria

    admin_id = uuid.uuid4()
    org_ref = uuid.uuid4()  # solo un dato en auditoría (no es scope RLS)
    email = f"norls-{uuid.uuid4().hex[:8]}@latinosport.bo"
    try:
        with Session(app_engine, expire_on_commit=False) as db:
            # SIN set_config: si tuvieran RLS, el INSERT/SELECT del rol app fallaría
            # o devolvería 0 filas. Como NO tienen RLS, funciona.
            db.add(
                PlataformaAdmin(
                    id=admin_id,
                    email=email,
                    password_hash=hash_password("norls1234"),
                    nombre="Sin RLS",
                    activo=True,
                )
            )
            db.add(
                PlataformaAuditoria(
                    admin_id=admin_id,
                    accion="CREAR_ESCUELA",
                    org_id=org_ref,
                    detalle="sin-contexto",
                )
            )
            db.commit()

        with app_engine.connect() as conn:
            # Lectura sin GUC: las filas de plataforma se ven igual.
            n_admin = conn.execute(
                text("SELECT count(*) FROM plataforma_admin WHERE id = :id"),
                {"id": str(admin_id)},
            ).scalar_one()
            n_aud = conn.execute(
                text("SELECT count(*) FROM plataforma_auditoria WHERE admin_id = :a"),
                {"a": str(admin_id)},
            ).scalar_one()
        assert n_admin == 1, "plataforma_admin no tiene RLS: se lee sin contexto"
        assert n_aud == 1, "plataforma_auditoria no tiene RLS: se lee sin contexto"
    finally:
        with app_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM plataforma_auditoria WHERE admin_id = :a"), {"a": str(admin_id)}
            )
            conn.execute(text("DELETE FROM plataforma_admin WHERE id = :id"), {"id": str(admin_id)})


@pytest_db
def test_crear_escuela_servicio_org_admin_y_aislamiento(
    plataforma_admin: dict, app_engine: Engine, owner_engine: Engine
) -> None:
    """`svc.crear_escuela` a nivel servicio: crea org ACTIVA + Usuario ADMIN con el
    org_id correcto, visible SOLO bajo el GUC de esa org, login_lookup lo encuentra,
    409 en email duplicado, y 1 fila de auditoría CREAR_ESCUELA.
    """
    from app.services import plataforma as svc

    admin_id = plataforma_admin["id"]
    suf = uuid.uuid4().hex[:8]
    admin_email = f"svc-dir-{suf}@escuela.bo"
    otra_org = uuid.uuid4()
    org_id: uuid.UUID | None = None
    try:
        # Una org "ajena" para probar el aislamiento (creada como owner, saltando RLS).
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, estado, created_at, updated_at) "
                    "VALUES (:id, 'Otra Org (test)', 'BO', 'BOB', 'ANIVERSARIO', true, "
                    "'ACTIVA', now(), now())"
                ),
                {"id": str(otra_org)},
            )

        # El servicio fija el GUC a la org nueva solo para el INSERT del usuario; el
        # super admin NO trae contexto de tenant (sesión sin set_config previo).
        with Session(app_engine, expire_on_commit=False) as db:
            org, user = svc.crear_escuela(
                db,
                admin_id=admin_id,
                nombre=f"Escuela Svc {suf}",
                pais="BO",
                moneda="BOB",
                admin_nombre="Director Svc",
                admin_email=admin_email,
                admin_password="director1234",
            )
            db.commit()
            org_id = org.id
            assert org.estado == "ACTIVA"
            assert user.role == "ADMIN"
            assert user.org_id == org.id

        # El usuario admin es visible SOLO bajo el GUC de su org.
        with app_engine.begin() as conn:
            _set_org(conn, org_id)
            visto = conn.execute(
                text("SELECT count(*) FROM usuario WHERE id = :id"), {"id": str(user.id)}
            ).scalar_one()
        assert visto == 1, "bajo el GUC de su org, el admin es visible"

        # Con el GUC de OTRA org → 0 filas (aislamiento RLS).
        with app_engine.begin() as conn:
            _set_org(conn, otra_org)
            ajeno = conn.execute(
                text("SELECT count(*) FROM usuario WHERE id = :id"), {"id": str(user.id)}
            ).scalar_one()
        assert ajeno == 0, "el admin de una escuela NO es visible bajo el GUC de otra"

        # login_lookup (SECURITY DEFINER) lo encuentra (es el camino del login real).
        with app_engine.connect() as conn:
            row = (
                conn.execute(text("SELECT org_id, role FROM login_lookup(:e)"), {"e": admin_email})
                .mappings()
                .first()
            )
        assert row is not None
        assert str(row["org_id"]) == str(org_id)
        assert row["role"] == "ADMIN"

        # 1 fila de auditoría CREAR_ESCUELA (tabla sin RLS).
        with owner_engine.connect() as conn:
            n_aud = conn.execute(
                text(
                    "SELECT count(*) FROM plataforma_auditoria "
                    "WHERE accion = 'CREAR_ESCUELA' AND org_id = :o AND admin_id = :a"
                ),
                {"o": str(org_id), "a": str(admin_id)},
            ).scalar_one()
        assert n_aud == 1

        # Email duplicado → HTTPException 409.
        with Session(app_engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as exc:
                svc.crear_escuela(
                    db,
                    admin_id=admin_id,
                    nombre=f"Escuela Dup {suf}",
                    pais="BO",
                    moneda="BOB",
                    admin_nombre="Otro Dir",
                    admin_email=admin_email,  # mismo email global → 409
                    admin_password="otro1234",
                )
            db.rollback()
        assert exc.value.status_code == 409
    finally:
        with owner_engine.begin() as conn:
            if org_id is not None:
                conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org_id)})
                conn.execute(
                    text("DELETE FROM plataforma_auditoria WHERE org_id = :o"), {"o": str(org_id)}
                )
                conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(otra_org)})


@pytest_db
def test_desactivar_admin_guard_servicio(app_engine: Engine, owner_engine: Engine) -> None:
    """`svc.desactivar_admin`: con 1 solo activo → 409; con 2, se desactiva uno.

    Aísla el conteo: desactiva los demás como owner, deja 2 propios activos.
    """
    from app.services import plataforma as svc

    a1, a2 = uuid.uuid4(), uuid.uuid4()
    e1 = f"guard1-{uuid.uuid4().hex[:8]}@latinosport.bo"
    e2 = f"guard2-{uuid.uuid4().hex[:8]}@latinosport.bo"
    previos: list[str] = []
    try:
        with owner_engine.begin() as conn:
            previos = [
                str(r)
                for r in conn.execute(text("SELECT id FROM plataforma_admin WHERE activo = true"))
                .scalars()
                .all()
            ]
            conn.execute(text("UPDATE plataforma_admin SET activo = false WHERE activo = true"))
            for aid, em in ((a1, e1), (a2, e2)):
                conn.execute(
                    text(
                        "INSERT INTO plataforma_admin (id, email, password_hash, nombre, activo, "
                        "created_at, updated_at) VALUES (:id, :e, :ph, 'Guard', true, now(), now())"
                    ),
                    {"id": str(aid), "e": em, "ph": hash_password("guard1234")},
                )

        # Con 2 activos: desactivar uno funciona.
        with Session(app_engine, expire_on_commit=False) as db:
            admin = svc.desactivar_admin(db, admin_id=a1)
            db.commit()
            assert admin.activo is False

        # Ahora solo queda 1 activo (a2): desactivarlo → 409.
        with Session(app_engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as exc:
                svc.desactivar_admin(db, admin_id=a2)
            db.rollback()
        assert exc.value.status_code == 409
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM plataforma_admin WHERE id = ANY(:ids)"),
                {"ids": [str(a1), str(a2)]},
            )
            if previos:
                conn.execute(
                    text("UPDATE plataforma_admin SET activo = true WHERE id = ANY(:ids)"),
                    {"ids": previos},
                )


@pytest_db
def test_login_plataforma_servicio(app_engine: Engine, plataforma_admin: dict) -> None:
    """`svc.login_plataforma`: credenciales válidas → admin; clave mala o inactivo → 401."""
    from app.services import plataforma as svc

    email = plataforma_admin["email"]
    password = plataforma_admin["password"]
    admin_id = plataforma_admin["id"]

    # Válido → devuelve el admin.
    with Session(app_engine, expire_on_commit=False) as db:
        admin = svc.login_plataforma(db, email=email, password=password)
        assert admin.id == admin_id

    # Clave incorrecta → 401.
    with Session(app_engine, expire_on_commit=False) as db:
        with pytest.raises(HTTPException) as exc_pass:
            svc.login_plataforma(db, email=email, password="incorrecta")
    assert exc_pass.value.status_code == 401

    # Email inexistente → 401.
    with Session(app_engine, expire_on_commit=False) as db:
        with pytest.raises(HTTPException) as exc_mail:
            svc.login_plataforma(db, email="no-existe@latinosport.bo", password=password)
    assert exc_mail.value.status_code == 401

    # Admin inactivo → 401 (lo desactivamos como owner para no romper la salvaguarda).
    with app_engine.begin() as conn:
        conn.execute(
            text("UPDATE plataforma_admin SET activo = false WHERE id = :id"),
            {"id": str(admin_id)},
        )
    try:
        with Session(app_engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as exc_inact:
                svc.login_plataforma(db, email=email, password=password)
        assert exc_inact.value.status_code == 401
    finally:
        with app_engine.begin() as conn:
            conn.execute(
                text("UPDATE plataforma_admin SET activo = true WHERE id = :id"),
                {"id": str(admin_id)},
            )
