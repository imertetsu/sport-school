"""Tests del módulo de Entrenadores (epic B · Gestión de Entrenadores).

Dos capas, igual que el resto de la suite:

- **Sin BD** (rápidos, siempre corren): validación de los schemas (`password < 8`
  -> 422, `email` mal formado -> 422, defaults de `disciplinas`) y la autorización
  pura de `require_role` (ENTRENADOR -> 403 en escritura).
- **Con BD** (`@pytest.mark.db`, requieren Postgres migrado con `0013` + RLS + rol
  `latinosport_app`): aislamiento RLS del listado (la org A no ve a la org B), alta
  bajo RLS (el usuario creado es ENTRENADOR/activo con hash válido), el **GOTCHA de
  RLS** (email usado en OTRA org -> `EmailEnUso`, capturado por `IntegrityError`),
  `solo_activos`, edición/baja y 404.

Se usa `owner_engine` para sembrar (saltando RLS) y una `Session` sobre `app_engine`
(rol `latinosport_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS real. Las
pruebas de gating de la API usan `TestClient` + tokens emitidos en proceso. Skip si
no hay BD (ver conftest).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from app.core.security import create_access_token, verify_password
from app.core.tenant import CurrentUser, require_role
from app.schemas.entrenador import EntrenadorCreate, EntrenadorUpdate
from app.services import entrenador as svc
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Validación de schemas (sin BD) -> 422
# --------------------------------------------------------------------------- #
def test_create_schema_ok() -> None:
    obj = EntrenadorCreate(
        nombres="Carlos",
        email="carlos@test.bo",
        password="secreto8",
        especialidad="Fútbol",
        disciplinas=["Fútbol", "Natación"],
    )
    assert obj.disciplinas == ["Fútbol", "Natación"]
    assert obj.especialidad == "Fútbol"


def test_create_schema_disciplinas_default_vacia() -> None:
    obj = EntrenadorCreate(nombres="Ana", email="ana@test.bo", password="12345678")
    assert obj.disciplinas == []
    assert obj.especialidad is None


def test_create_schema_password_corta_falla() -> None:
    """password < 8 -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        EntrenadorCreate(nombres="Ana", email="ana@test.bo", password="1234567")


def test_create_schema_email_invalido_falla() -> None:
    with pytest.raises(ValidationError):
        EntrenadorCreate(nombres="Ana", email="no-es-email", password="12345678")


def test_update_schema_password_corta_falla() -> None:
    """password < 8 en update -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        EntrenadorUpdate(password="corto")


def test_update_schema_todo_opcional() -> None:
    obj = EntrenadorUpdate()
    assert obj.nombres is None and obj.activo is None and obj.password is None


# --------------------------------------------------------------------------- #
# Autorización (sin BD): ADMIN pasa / ENTRENADOR -> 403 en escritura
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role)


def test_require_role_admin_pasa() -> None:
    checker = require_role("ADMIN")
    user = _user("ADMIN")
    assert checker(user=user) is user


def test_require_role_entrenador_403() -> None:
    """ENTRENADOR -> HTTPException 403 (no puede crear/editar)."""
    checker = require_role("ADMIN")
    with pytest.raises(HTTPException) as exc:
        checker(user=_user("ENTRENADOR"))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Fixture con BD: 2 orgs A/B, cada una con un usuario ADMIN; B con 1 entrenador.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ent_fixture(owner_engine: Engine) -> Iterator[dict]:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    # Entrenador ya existente en B (usuario + perfil).
    coach_b_user = uuid.uuid4()
    coach_b = uuid.uuid4()

    email_admin_a = f"admin_a_{uuid.uuid4().hex}@test.bo"
    email_admin_b = f"admin_b_{uuid.uuid4().hex}@test.bo"
    email_coach_b = f"coach_b_{uuid.uuid4().hex}@test.bo"

    with owner_engine.begin() as conn:
        for org_id, nombre in ((org_a, "Org A Ent (test)"), (org_b, "Org B Ent (test)")):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id,:nom,'BO','BOB','ANIVERSARIO',true,now(),now())"
                ),
                {"id": str(org_id), "nom": nombre},
            )
        for uid, org_id, email, role, nom in (
            (admin_a, org_a, email_admin_a, "ADMIN", "Admin A"),
            (admin_b, org_b, email_admin_b, "ADMIN", "Admin B"),
            (coach_b_user, org_b, email_coach_b, "ENTRENADOR", "Coach B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
                    "activo, created_at, updated_at) "
                    "VALUES (:id,:org,:email,'x',:role,:nom,true,now(),now())"
                ),
                {"id": str(uid), "org": str(org_id), "email": email, "role": role, "nom": nom},
            )
        conn.execute(
            text(
                "INSERT INTO entrenador (id, org_id, usuario_id, nombres, especialidad, "
                "disciplinas, created_at, updated_at) "
                "VALUES (:id,:org,:uid,'Coach B','Básquet','[\"Básquetbol\"]',now(),now())"
            ),
            {"id": str(coach_b), "org": str(org_b), "uid": str(coach_b_user)},
        )

    yield {
        "org_a": org_a,
        "org_b": org_b,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "coach_b_user": coach_b_user,
        "coach_b": coach_b,
        "email_admin_a": email_admin_a,
        "email_admin_b": email_admin_b,
        "email_coach_b": email_coach_b,
    }

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM entrenador WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Aislamiento RLS: la org A no ve a los entrenadores de la org B
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_aislamiento_rls_listar(app_engine: Engine, ent_fixture: dict) -> None:
    """`listar` bajo el contexto de A no devuelve el entrenador de B (RLS)."""
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, ent_fixture["org_a"])
        filas_a = svc.listar(db, solo_activos=False)
    # A no tiene entrenadores aún; y NO ve el de B.
    ids_a = {row[0].id for row in filas_a}
    assert ent_fixture["coach_b"] not in ids_a
    assert filas_a == []

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, ent_fixture["org_b"])
        filas_b = svc.listar(db, solo_activos=False)
    ids_b = {row[0].id for row in filas_b}
    assert ent_fixture["coach_b"] in ids_b, "B ve a su propio entrenador"


# --------------------------------------------------------------------------- #
# Alta (ADMIN) bajo RLS: usuario ENTRENADOR activo, hash válido, perfil con disciplinas
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_crear_entrenador_bajo_rls(app_engine: Engine, ent_fixture: dict) -> None:
    """`crear` en la org A inserta usuario(ENTRENADOR, activo) + perfil; hash verifica."""
    org_a = ent_fixture["org_a"]
    email = f"nuevo_{uuid.uuid4().hex}@test.bo"
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        row = svc.crear(
            db,
            EntrenadorCreate(
                nombres="Nuevo Coach",
                email=email,
                password="clave1234",
                especialidad="Natación",
                disciplinas=["Natación"],
            ),
            org_id=org_a,
        )
        # El servicio solo hace flush; el test commitea para que el bloque
        # siguiente (sesión/transacción nueva) vea al entrenador (RLS por org).
        db.commit()
    entrenador, usuario = row
    assert usuario.role == "ENTRENADOR" and usuario.activo is True
    assert verify_password("clave1234", usuario.password_hash)
    assert entrenador.disciplinas == ["Natación"]
    assert entrenador.org_id == org_a

    # Aparece en el listado de A (y no en el de B).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        ids_a = {r[0].id for r in svc.listar(db, solo_activos=False)}
    assert entrenador.id in ids_a


# --------------------------------------------------------------------------- #
# GOTCHA de RLS: email usado en OTRA org -> EmailEnUso (capturado por IntegrityError,
# NO solo por el pre-chequeo, que bajo RLS no ve la otra org).
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_email_en_otra_org_da_409(app_engine: Engine, ent_fixture: dict) -> None:
    """Reusar el email del admin de B desde la org A -> EmailEnUso (no IntegrityError crudo)."""
    org_a = ent_fixture["org_a"]
    email_existente = ent_fixture["email_admin_b"]  # vive en la org B (no visible bajo RLS de A)
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        # El pre-chequeo (RLS) NO ve al usuario de B -> el INSERT lo destapa.
        assert svc._buscar_usuario_por_email(db, email_existente) is None
        with pytest.raises(svc.EmailEnUso):
            svc.crear(
                db,
                EntrenadorCreate(
                    nombres="Choca",
                    email=email_existente,
                    password="clave1234",
                ),
                org_id=org_a,
            )
        db.rollback()


@pytest.mark.db
def test_email_en_misma_org_da_409(app_engine: Engine, ent_fixture: dict) -> None:
    """Reusar el email del propio admin (visible bajo RLS) -> EmailEnUso por pre-chequeo."""
    org_b = ent_fixture["org_b"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_b)
        with pytest.raises(svc.EmailEnUso):
            svc.crear(
                db,
                EntrenadorCreate(
                    nombres="Dup",
                    email=ent_fixture["email_admin_b"],
                    password="clave1234",
                ),
                org_id=org_b,
            )
        db.rollback()


# --------------------------------------------------------------------------- #
# solo_activos excluye los dados de baja
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_solo_activos_excluye_inactivos(app_engine: Engine, ent_fixture: dict) -> None:
    """Un entrenador con `usuario.activo=false` no aparece con `solo_activos=true`."""
    org_a = ent_fixture["org_a"]
    email = f"baja_{uuid.uuid4().hex}@test.bo"
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        row = svc.crear(
            db,
            EntrenadorCreate(nombres="Por Dar Baja", email=email, password="clave1234"),
            org_id=org_a,
        )
        ent_id = row[0].id
        # Dar de baja.
        svc.editar(db, ent_id, EntrenadorUpdate(activo=False))
        # Commit explícito (el servicio solo flushea) para verlo en el bloque siguiente.
        db.commit()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        activos = {r[0].id for r in svc.listar(db, solo_activos=True)}
        todos = {r[0].id for r in svc.listar(db, solo_activos=False)}
    assert ent_id not in activos, "solo_activos=true excluye al dado de baja"
    assert ent_id in todos, "sin el flag, sí aparece"


# --------------------------------------------------------------------------- #
# Editar: baja/reactivación + campos; id inexistente -> 404
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_editar_baja_y_reactiva(app_engine: Engine, ent_fixture: dict) -> None:
    org_a = ent_fixture["org_a"]
    email = f"edit_{uuid.uuid4().hex}@test.bo"
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        row = svc.crear(
            db,
            EntrenadorCreate(nombres="Editable", email=email, password="clave1234"),
            org_id=org_a,
        )
        ent_id = row[0].id

        # Editar nombres/disciplinas + baja.
        baja = svc.editar(
            db,
            ent_id,
            EntrenadorUpdate(nombres="Editado", disciplinas=["Tenis"], activo=False),
        )
        assert baja[0].nombres == "Editado"
        assert baja[0].disciplinas == ["Tenis"]
        assert baja[1].activo is False

        # Reactivar.
        reactiva = svc.editar(db, ent_id, EntrenadorUpdate(activo=True))
        assert reactiva[1].activo is True


@pytest.mark.db
def test_editar_inexistente_404(app_engine: Engine, ent_fixture: dict) -> None:
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, ent_fixture["org_a"])
        with pytest.raises(svc.EntrenadorNoEncontrado):
            svc.editar(db, uuid.uuid4(), EntrenadorUpdate(nombres="X"))


# --------------------------------------------------------------------------- #
# Gating de la API (con BD): POST/PUT ENTRENADOR -> 403; GET ENTRENADOR -> 200;
# POST email de otra org -> 409 (no 500); PUT password<8 -> 422.
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    return create_access_token(user_id=str(user_id), org_id=str(org_id), role=role, sucursal_ids=[])


@pytest.mark.db
def test_api_get_entrenador_role_200(ent_fixture: dict) -> None:
    """GET por un ENTRENADOR autenticado -> 200 (cualquier rol puede listar)."""
    client = _client_or_skip()
    token = _token(ent_fixture["coach_b_user"], ent_fixture["org_b"], "ENTRENADOR")
    resp = client.get("/api/v1/entrenadores", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.db
def test_api_post_entrenador_role_403(ent_fixture: dict) -> None:
    """POST por un ENTRENADOR -> 403 (alta es solo ADMIN)."""
    client = _client_or_skip()
    token = _token(ent_fixture["coach_b_user"], ent_fixture["org_b"], "ENTRENADOR")
    resp = client.post(
        "/api/v1/entrenadores",
        headers={"Authorization": f"Bearer {token}"},
        json={"nombres": "X", "email": f"x_{uuid.uuid4().hex}@test.bo", "password": "clave1234"},
    )
    assert resp.status_code == 403


@pytest.mark.db
def test_api_put_entrenador_role_403(ent_fixture: dict) -> None:
    """PUT por un ENTRENADOR -> 403."""
    client = _client_or_skip()
    token = _token(ent_fixture["coach_b_user"], ent_fixture["org_b"], "ENTRENADOR")
    resp = client.put(
        f"/api/v1/entrenadores/{ent_fixture['coach_b']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"nombres": "X"},
    )
    assert resp.status_code == 403


@pytest.mark.db
def test_api_post_email_otra_org_409(ent_fixture: dict) -> None:
    """ADMIN de A crea con el email del admin de B -> 409 (GOTCHA), no 500."""
    client = _client_or_skip()
    token = _token(ent_fixture["admin_a"], ent_fixture["org_a"], "ADMIN")
    resp = client.post(
        "/api/v1/entrenadores",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "nombres": "Colisión",
            "email": ent_fixture["email_admin_b"],
            "password": "clave1234",
        },
    )
    assert resp.status_code == 409


@pytest.mark.db
def test_api_post_y_login(ent_fixture: dict) -> None:
    """ADMIN de A crea un entrenador (201) que luego puede hacer login."""
    client = _client_or_skip()
    token = _token(ent_fixture["admin_a"], ent_fixture["org_a"], "ADMIN")
    email = f"loginable_{uuid.uuid4().hex}@test.bo"
    resp = client.post(
        "/api/v1/entrenadores",
        headers={"Authorization": f"Bearer {token}"},
        json={"nombres": "Loginable", "email": email, "password": "clave1234"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email and body["activo"] is True

    login = client.post("/api/v1/auth/login", json={"email": email, "password": "clave1234"})
    assert login.status_code == 200, "El entrenador creado puede autenticarse"
    assert login.json()["user"]["role"] == "ENTRENADOR"


@pytest.mark.db
def test_api_put_password_corta_422(ent_fixture: dict) -> None:
    """PUT con password < 8 -> 422 (validación del schema)."""
    client = _client_or_skip()
    token = _token(ent_fixture["admin_b"], ent_fixture["org_b"], "ADMIN")
    resp = client.put(
        f"/api/v1/entrenadores/{ent_fixture['coach_b']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "corto"},
    )
    assert resp.status_code == 422


@pytest.mark.db
def test_api_put_inexistente_404(ent_fixture: dict) -> None:
    """PUT con id inexistente -> 404."""
    client = _client_or_skip()
    token = _token(ent_fixture["admin_a"], ent_fixture["org_a"], "ADMIN")
    resp = client.put(
        f"/api/v1/entrenadores/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
        json={"nombres": "X"},
    )
    assert resp.status_code == 404
