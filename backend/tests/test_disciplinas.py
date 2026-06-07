"""Tests del epic Disciplinas (S2): catálogo GLOBAL + FK en categoría/deportista.

Niveles:
1. **Puros (sin BD):** forma de los schemas (`DisciplinaOut` solo {id, nombre};
   `DisciplinaAdminOut` incluye activo/created_at), `CategoriaOut` con disciplina nested.
2. **`@db` (requieren Postgres migrado a 0016):**
   - CRUD superadmin: crear, listar (activas+inactivas), 409 case-insensitive
     ("Voley"/"voley"), renombrar, soft-delete vía PUT activo=false, 404.
   - Lectura `/catalogo/disciplinas` por ADMIN y por ENTRENADOR (solo activas por defecto).
   - Categoría con `disciplina_id` inexistente → 404; inactiva → 422; válida → nested poblado.
   - `disciplina` GLOBAL: SELECT visible SIN contexto de org (tabla sin RLS).

Los `@db` se omiten (skip) si no hay BD alcanzable (ver conftest).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from app.core.security import create_access_token, hash_password
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# 1) Tests puros (sin BD): forma de los schemas
# --------------------------------------------------------------------------- #
def test_disciplina_out_solo_id_y_nombre() -> None:
    """`DisciplinaOut` (vista escuela) expone SOLO id y nombre (cero datos de tenant)."""
    from app.schemas.disciplina import DisciplinaOut

    out = DisciplinaOut(id=uuid.uuid4(), nombre="Voleibol")
    dumped = out.model_dump()
    assert set(dumped) == {"id", "nombre"}


def test_disciplina_admin_out_incluye_activo_y_created_at() -> None:
    """`DisciplinaAdminOut` (vista superadmin) incluye activo y created_at."""
    from datetime import UTC, datetime

    from app.schemas.disciplina import DisciplinaAdminOut

    out = DisciplinaAdminOut(
        id=uuid.uuid4(), nombre="Futsal", activo=True, created_at=datetime.now(UTC)
    )
    dumped = out.model_dump()
    assert set(dumped) == {"id", "nombre", "activo", "created_at"}


def test_categoria_out_acepta_disciplina_nested() -> None:
    """`CategoriaOut` admite `disciplina_id` + nested `disciplina` (o None ambos)."""
    from app.schemas.catalogo import CategoriaOut
    from app.schemas.disciplina import DisciplinaRef

    disc_id = uuid.uuid4()
    out = CategoriaOut(
        id=uuid.uuid4(),
        nombre="Sub-14",
        nivel="INTERMEDIO",
        sucursal_id=uuid.uuid4(),
        disciplina_id=disc_id,
        disciplina=DisciplinaRef(id=disc_id, nombre="Tenis"),
    )
    assert out.disciplina is not None
    assert out.disciplina.nombre == "Tenis"

    # Sin disciplina: ambos None por defecto (categoría sin asignar).
    sin = CategoriaOut(id=uuid.uuid4(), nombre="X", nivel="PRINCIPIANTE", sucursal_id=uuid.uuid4())
    assert sin.disciplina_id is None
    assert sin.disciplina is None


def test_categoria_create_disciplina_id_opcional() -> None:
    """`CategoriaCreate`/`CategoriaUpdate` aceptan `disciplina_id` opcional (default None)."""
    from app.schemas.catalogo import CategoriaCreate, CategoriaUpdate

    c = CategoriaCreate(nombre="A", nivel="PRINCIPIANTE", sucursal_id=uuid.uuid4())
    assert c.disciplina_id is None
    u = CategoriaUpdate(nombre="A", nivel="PRINCIPIANTE", disciplina_id=uuid.uuid4())
    assert u.disciplina_id is not None


# --------------------------------------------------------------------------- #
# 2) Tests @db (requieren Postgres migrado a 0016)
# --------------------------------------------------------------------------- #
pytest_db = pytest.mark.db

PLAT_EMAIL = "ops-disc-test@latinosport.bo"
PLAT_PASS = "ops-disc-1234"


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado a 0016")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def plataforma_admin(owner_engine: Engine) -> Iterator[dict]:
    """Crea (como owner) un super admin de plataforma para los tests. Limpia al final."""
    admin_id = uuid.uuid4()
    pwd_hash = hash_password(PLAT_PASS)
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM plataforma_admin WHERE email = :e"), {"e": PLAT_EMAIL})
        conn.execute(
            text(
                "INSERT INTO plataforma_admin (id, email, password_hash, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id, :email, :ph, 'Ops Disc', true, now(), now())"
            ),
            {"id": str(admin_id), "email": PLAT_EMAIL, "ph": pwd_hash},
        )
    yield {"id": admin_id, "email": PLAT_EMAIL, "password": PLAT_PASS}
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM plataforma_admin WHERE id = :id"), {"id": str(admin_id)})


def _platform_token(client, admin) -> str:
    resp = client.post(
        "/api/v1/plataforma/login",
        json={"email": admin["email"], "password": admin["password"]},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


@pytest.fixture()
def disciplinas_limpias(owner_engine: Engine) -> Iterator[set[uuid.UUID]]:
    """Registra ids de disciplina creadas durante el test y las borra al final.

    Hard delete SOLO en teardown de test (no es el flujo de producción, que es soft).
    """
    creadas: set[uuid.UUID] = set()
    yield creadas
    if creadas:
        ids = [str(i) for i in creadas]
        with owner_engine.begin() as conn:
            # Nulificar referencias antes del hard-delete: categoria.disciplina_id es
            # FK ON DELETE RESTRICT, así que el borrado falla si una categoría (u otra
            # entidad) aún la referencia. Hacer el teardown independiente del orden de
            # finalización de fixtures (owner_engine bypassa RLS → cubre todas las orgs).
            conn.execute(
                text("UPDATE categoria SET disciplina_id = NULL WHERE disciplina_id = ANY(:ids)"),
                {"ids": ids},
            )
            conn.execute(
                text("UPDATE deportista SET disciplina_id = NULL WHERE disciplina_id = ANY(:ids)"),
                {"ids": ids},
            )
            conn.execute(
                text("DELETE FROM disciplina WHERE id = ANY(:ids)"),
                {"ids": ids},
            )


@pytest_db
def test_crud_superadmin_disciplinas(
    plataforma_admin: dict, disciplinas_limpias: set, owner_engine: Engine
) -> None:
    """Crear, listar (activas+inactivas), 409 case-insensitive, renombrar, soft-delete, 404."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    headers = {"Authorization": f"Bearer {token}"}
    suf = uuid.uuid4().hex[:6]
    nombre = f"Voley {suf}"

    # Crear (201) → activo por defecto.
    created = client.post(
        "/api/v1/plataforma/disciplinas", headers=headers, json={"nombre": nombre}
    )
    assert created.status_code == 201, created.text
    data = created.json()
    disc_id = uuid.UUID(data["id"])
    disciplinas_limpias.add(disc_id)
    assert data["activo"] is True
    assert "created_at" in data

    # 409 case-insensitive: "voley ..." (lower igual) → conflicto.
    dup = client.post(
        "/api/v1/plataforma/disciplinas", headers=headers, json={"nombre": nombre.lower()}
    )
    assert dup.status_code == 409, dup.text

    # Listar incluye la recién creada.
    lista = client.get("/api/v1/plataforma/disciplinas", headers=headers)
    assert lista.status_code == 200
    assert any(d["id"] == str(disc_id) for d in lista.json())

    # Renombrar.
    nuevo = f"Voleibol {suf}"
    upd = client.put(
        f"/api/v1/plataforma/disciplinas/{disc_id}", headers=headers, json={"nombre": nuevo}
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["nombre"] == nuevo

    # Soft-delete vía PUT activo=false (NO hard delete).
    soft = client.put(
        f"/api/v1/plataforma/disciplinas/{disc_id}", headers=headers, json={"activo": False}
    )
    assert soft.status_code == 200
    assert soft.json()["activo"] is False

    # La fila sigue existiendo (soft, no hard).
    with owner_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM disciplina WHERE id = :i"), {"i": str(disc_id)}
        ).scalar_one()
    assert n == 1, "soft-delete: la fila NO se borra"

    # 404 en id inexistente.
    assert (
        client.put(
            f"/api/v1/plataforma/disciplinas/{uuid.uuid4()}", headers=headers, json={"nombre": "x"}
        ).status_code
        == 404
    )


@pytest_db
def test_disciplinas_requiere_superadmin(plataforma_admin: dict) -> None:
    """CRUD de disciplinas: sin token → 401; token de escuela → 403."""
    client = _client_or_skip()
    # sin token → 401
    assert client.get("/api/v1/plataforma/disciplinas").status_code == 401
    # token de escuela (ADMIN) → 403
    escuela_token = create_access_token(
        user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role="ADMIN", sucursal_ids=[]
    )
    resp = client.get(
        "/api/v1/plataforma/disciplinas",
        headers={"Authorization": f"Bearer {escuela_token}"},
    )
    assert resp.status_code == 403


@pytest_db
def test_catalogo_lectura_admin_y_entrenador(
    plataforma_admin: dict, disciplinas_limpias: set
) -> None:
    """`GET /catalogo/disciplinas` lo leen ADMIN y ENTRENADOR; respuesta solo {id, nombre}."""
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    headers = {"Authorization": f"Bearer {token}"}
    suf = uuid.uuid4().hex[:6]

    # Una activa y una inactiva.
    activa = client.post(
        "/api/v1/plataforma/disciplinas", headers=headers, json={"nombre": f"Activa {suf}"}
    ).json()
    inactiva = client.post(
        "/api/v1/plataforma/disciplinas", headers=headers, json={"nombre": f"Inactiva {suf}"}
    ).json()
    disciplinas_limpias.add(uuid.UUID(activa["id"]))
    disciplinas_limpias.add(uuid.UUID(inactiva["id"]))
    client.put(
        f"/api/v1/plataforma/disciplinas/{inactiva['id']}", headers=headers, json={"activo": False}
    )

    org = uuid.uuid4()
    for role in ("ADMIN", "ENTRENADOR"):
        tok = create_access_token(
            user_id=str(uuid.uuid4()), org_id=str(org), role=role, sucursal_ids=[]
        )
        resp = client.get(
            "/api/v1/catalogo/disciplinas", headers={"Authorization": f"Bearer {tok}"}
        )
        assert resp.status_code == 200, f"{role}: {resp.text}"
        ids = {d["id"] for d in resp.json()}
        # Por defecto solo_activas=true: la activa aparece, la inactiva no.
        assert activa["id"] in ids, f"{role} debe ver la disciplina activa"
        assert inactiva["id"] not in ids, "solo_activas=true por defecto"
        # Respuesta = solo {id, nombre} (cero datos de tenant).
        for d in resp.json():
            assert set(d) == {"id", "nombre"}

    # solo_activas=false incluye las inactivas.
    tok = create_access_token(
        user_id=str(uuid.uuid4()), org_id=str(org), role="ADMIN", sucursal_ids=[]
    )
    todas = client.get(
        "/api/v1/catalogo/disciplinas?solo_activas=false",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert inactiva["id"] in {d["id"] for d in todas.json()}


@pytest_db
def test_catalogo_requiere_token(plataforma_admin: dict) -> None:
    """`GET /catalogo/disciplinas` sin token → 401 (set_tenant_context exige auth)."""
    client = _client_or_skip()
    assert client.get("/api/v1/catalogo/disciplinas").status_code == 401


@pytest_db
def test_disciplina_global_select_visible_sin_org(
    app_engine: Engine, plataforma_admin: dict, disciplinas_limpias: set
) -> None:
    """`disciplina` es GLOBAL (sin RLS): SELECT la ve SIN fijar `app.current_org`.

    Contraste con tablas tenant (fail-closed). Crea una disciplina vía superadmin y la
    lee con una Session del rol app SIN contexto de org.
    """
    client = _client_or_skip()
    token = _platform_token(client, plataforma_admin)
    suf = uuid.uuid4().hex[:6]
    created = client.post(
        "/api/v1/plataforma/disciplinas",
        headers={"Authorization": f"Bearer {token}"},
        json={"nombre": f"Global {suf}"},
    ).json()
    disc_id = uuid.UUID(created["id"])
    disciplinas_limpias.add(disc_id)

    # Sin set_config('app.current_org', ...): si tuviera RLS, daría 0 filas.
    with Session(app_engine, expire_on_commit=False) as db:
        n = db.execute(
            text("SELECT count(*) FROM disciplina WHERE id = :i"), {"i": str(disc_id)}
        ).scalar_one()
    assert n == 1, "disciplina es global sin RLS: visible sin contexto de tenant"


# --------------------------------------------------------------------------- #
# Categoría + disciplina_id
# --------------------------------------------------------------------------- #
def _sembrar_org_admin(conn, *, org: uuid.UUID, user: uuid.UUID, email: str) -> None:
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Disc (test)','BO','BOB','ANIVERSARIO',true,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
            "activo, created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin Disc',true,now(),now())"
        ),
        {"id": str(user), "org": str(org), "email": email},
    )


@pytest.fixture()
def org_admin(owner_engine: Engine) -> Iterator[dict]:
    """Una org con un usuario ADMIN; limpia al final (categorías incluidas)."""
    org = uuid.uuid4()
    user = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org_admin(conn, org=org, user=user, email=f"admin_{user.hex}@disc.test")
    token = create_access_token(user_id=str(user), org_id=str(org), role="ADMIN", sucursal_ids=[])
    yield {"org": org, "user": user, "token": token}
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


@pytest_db
def test_categoria_disciplina_id_inexistente_404(org_admin: dict) -> None:
    """Crear categoría con `disciplina_id` que no existe → 404."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    suc_id = client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Suc"}).json()["id"]

    resp = client.post(
        "/api/v1/categorias",
        headers=headers,
        json={
            "nombre": "Sub-12",
            "nivel": "PRINCIPIANTE",
            "sucursal_id": suc_id,
            "disciplina_id": str(uuid.uuid4()),  # no existe
        },
    )
    assert resp.status_code == 404, resp.text


@pytest_db
def test_categoria_disciplina_inactiva_422(
    org_admin: dict, plataforma_admin: dict, disciplinas_limpias: set
) -> None:
    """Crear categoría con una disciplina INACTIVA → 422 (no se puede asignar)."""
    client = _client_or_skip()
    # Crear + desactivar una disciplina como superadmin.
    plat_token = _platform_token(client, plataforma_admin)
    plat_headers = {"Authorization": f"Bearer {plat_token}"}
    suf = uuid.uuid4().hex[:6]
    disc = client.post(
        "/api/v1/plataforma/disciplinas", headers=plat_headers, json={"nombre": f"Inact {suf}"}
    ).json()
    disciplinas_limpias.add(uuid.UUID(disc["id"]))
    client.put(
        f"/api/v1/plataforma/disciplinas/{disc['id']}", headers=plat_headers, json={"activo": False}
    )

    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    suc_id = client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Suc2"}).json()[
        "id"
    ]
    resp = client.post(
        "/api/v1/categorias",
        headers=headers,
        json={
            "nombre": "Sub-10",
            "nivel": "PRINCIPIANTE",
            "sucursal_id": suc_id,
            "disciplina_id": disc["id"],
        },
    )
    assert resp.status_code == 422, resp.text


@pytest_db
def test_categoria_disciplina_valida_pobla_nested(
    org_admin: dict, plataforma_admin: dict, disciplinas_limpias: set
) -> None:
    """Categoría con disciplina activa válida → 201 y `CategoriaOut.disciplina` poblado."""
    client = _client_or_skip()
    plat_token = _platform_token(client, plataforma_admin)
    suf = uuid.uuid4().hex[:6]
    nombre_disc = f"Basquet {suf}"
    disc = client.post(
        "/api/v1/plataforma/disciplinas",
        headers={"Authorization": f"Bearer {plat_token}"},
        json={"nombre": nombre_disc},
    ).json()
    disciplinas_limpias.add(uuid.UUID(disc["id"]))

    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    suc_id = client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Suc3"}).json()[
        "id"
    ]
    resp = client.post(
        "/api/v1/categorias",
        headers=headers,
        json={
            "nombre": "Sub-16",
            "nivel": "AVANZADO",
            "sucursal_id": suc_id,
            "disciplina_id": disc["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["disciplina_id"] == disc["id"]
    assert body["disciplina"] is not None
    assert body["disciplina"]["id"] == disc["id"]
    assert body["disciplina"]["nombre"] == nombre_disc

    # GET de la lista también lo trae poblado.
    lista = client.get(f"/api/v1/categorias?sucursal_id={suc_id}", headers=headers).json()
    item = next(c for c in lista if c["id"] == body["id"])
    assert item["disciplina"]["nombre"] == nombre_disc
