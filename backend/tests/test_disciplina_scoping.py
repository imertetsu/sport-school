"""Scoping POR DISCIPLINA para no-ADMIN (fix UX entrenador + RED DE SEGURIDAD).

Decisión de producto: un ENTRENADOR ve lo de las DISCIPLINAS que tiene asignadas
(`entrenador_disciplina`), MÁS los registros con disciplina NULL (red de seguridad:
nunca invisibles). ADMIN ve todo. **Sin disciplinas asignadas -> NO se filtra por
disciplina** (cae al comportamiento por sucursal de antes; ve lo de su org/sucursales,
no vacío).

Cubre:
- `entrenador_svc.disciplina_ids_de_usuario`: resuelve las disciplinas del entrenador
  cuyo usuario es el dado (vacío si no es entrenador o no tiene disciplinas).
- Deportistas: ENTRENADOR de la disciplina A ve los de A + los de disciplina NULL en el
  listado (NO los de B) y recibe 404 SOLO en el detalle de un deportista de B; ADMIN ve
  todos; ENTRENADOR sin disciplinas -> ve por sucursal (red de seguridad, no vacío).
- Asistencia `listar_categorias`: ENTRENADOR ve categorías de su disciplina + las de
  disciplina NULL; roster/guardar/sesiones de una categoría de otra disciplina ->
  `CategoriaFuera`. Sin disciplinas asignadas (set vacío) -> sin filtro de disciplina.

`owner_engine` siembra saltando RLS; el servicio corre sobre `app_engine` (rol
`latinosport_app`, NOBYPASSRLS) bajo RLS real. GOTCHA: `SET LOCAL app.current_org` se
pierde tras `commit()`; se re-fija con `_set_org`. Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from app.services import asistencia as asis_svc
from app.services import entrenador as entrenador_svc
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Fixture: org con 2 disciplinas (A=Futsal, B=Voley), 2 sucursales, categoría +
# deportista por disciplina, 1 entrenador (usuario) asignado SOLO a la disciplina A.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def scope_fixture(owner_engine: Engine) -> Iterator[dict]:
    org = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()
    disc_a = uuid.uuid4()  # Futsal
    disc_b = uuid.uuid4()  # Voley
    cat_a = uuid.uuid4()
    cat_b = uuid.uuid4()
    al_a = uuid.uuid4()  # deportista de la disciplina A
    al_b = uuid.uuid4()  # deportista de la disciplina B
    al_sin_disc = uuid.uuid4()  # deportista sin disciplina (no debe verlo el entrenador)
    admin_user = uuid.uuid4()
    coach_user = uuid.uuid4()  # usuario del entrenador
    coach = uuid.uuid4()  # perfil entrenador
    coach_sin_disc_user = uuid.uuid4()
    coach_sin_disc = uuid.uuid4()
    suf = uuid.uuid4().hex[:8]

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Scope (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        for disc_id, nom in ((disc_a, f"Futsal {suf}"), (disc_b, f"Voley {suf}")):
            conn.execute(
                text(
                    "INSERT INTO disciplina (id, nombre, activo, created_at, updated_at) "
                    "VALUES (:id,:nom,true,now(),now())"
                ),
                {"id": str(disc_id), "nom": nom},
            )
        for suc_id, nom in ((suc_a, "Suc A"), (suc_b, "Suc B")):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(suc_id), "org": str(org), "nom": nom},
            )
        for uid, email, role, nom in (
            (admin_user, f"admin_{suf}@test.bo", "ADMIN", "Admin"),
            (coach_user, f"coach_{suf}@test.bo", "ENTRENADOR", "Coach A"),
            (coach_sin_disc_user, f"coachsd_{suf}@test.bo", "ENTRENADOR", "Coach SD"),
        ):
            conn.execute(
                text(
                    "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
                    "activo, created_at, updated_at) "
                    "VALUES (:id,:org,:email,'x',:role,:nom,true,now(),now())"
                ),
                {"id": str(uid), "org": str(org), "email": email, "role": role, "nom": nom},
            )
        for ent_id, uid, nom in (
            (coach, coach_user, "Coach A"),
            (coach_sin_disc, coach_sin_disc_user, "Coach SD"),
        ):
            conn.execute(
                text(
                    "INSERT INTO entrenador (id, org_id, usuario_id, nombres, "
                    "created_at, updated_at) VALUES (:id,:org,:uid,:nom,now(),now())"
                ),
                {"id": str(ent_id), "org": str(org), "uid": str(uid), "nom": nom},
            )
        # El entrenador `coach` queda asignado SOLO a la disciplina A.
        conn.execute(
            text(
                "INSERT INTO entrenador_disciplina (id, org_id, entrenador_id, disciplina_id, "
                "created_at) VALUES (:id,:org,:ent,:disc,now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(org),
                "ent": str(coach),
                "disc": str(disc_a),
            },
        )
        for cat_id, suc_id, disc_id, nom in (
            (cat_a, suc_a, disc_a, "Cat A"),
            (cat_b, suc_b, disc_b, "Cat B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO categoria (id, org_id, sucursal_id, disciplina_id, nombre, "
                    "nivel, created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:disc,:nom,'PRINCIPIANTE',now(),now())"
                ),
                {
                    "id": str(cat_id),
                    "org": str(org),
                    "suc": str(suc_id),
                    "disc": str(disc_id),
                    "nom": nom,
                },
            )
        deportistas_seed: tuple[
            tuple[uuid.UUID, uuid.UUID, uuid.UUID | None, uuid.UUID | None, str], ...
        ] = (
            (al_a, suc_a, cat_a, disc_a, "Ana A"),
            (al_b, suc_b, cat_b, disc_b, "Bruno B"),
            (al_sin_disc, suc_a, None, None, "Sin Disc"),
        )
        for al_id, al_suc, al_cat, al_disc, al_nom in deportistas_seed:
            conn.execute(
                text(
                    "INSERT INTO deportista (id, org_id, sucursal_id, categoria_id, "
                    "disciplina_id, nombres, created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:cat,:disc,:nom,now(),now())"
                ),
                {
                    "id": str(al_id),
                    "org": str(org),
                    "suc": str(al_suc),
                    "cat": str(al_cat) if al_cat else None,
                    "disc": str(al_disc) if al_disc else None,
                    "nom": al_nom,
                },
            )

    yield {
        "org": org,
        "suc_a": suc_a,
        "suc_b": suc_b,
        "disc_a": disc_a,
        "disc_b": disc_b,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "al_a": al_a,
        "al_b": al_b,
        "al_sin_disc": al_sin_disc,
        "admin_user": admin_user,
        "coach_user": coach_user,
        "coach": coach,
        "coach_sin_disc_user": coach_sin_disc_user,
        "coach_sin_disc": coach_sin_disc,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM asistencia WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sesion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM entrenador_disciplina WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM entrenador WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})
        for disc_id in (disc_a, disc_b):
            conn.execute(text("DELETE FROM disciplina WHERE id = :d"), {"d": str(disc_id)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# disciplina_ids_de_usuario (TAREA 1)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_disciplina_ids_de_usuario_resuelve(app_engine: Engine, scope_fixture: dict) -> None:
    """El usuario del entrenador resuelve sus disciplinas asignadas (solo A)."""
    org = scope_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        ids = entrenador_svc.disciplina_ids_de_usuario(db, scope_fixture["coach_user"])
    assert ids == {scope_fixture["disc_a"]}


@pytest.mark.db
def test_disciplina_ids_de_usuario_sin_disciplinas(app_engine: Engine, scope_fixture: dict) -> None:
    """Un entrenador sin disciplinas asignadas -> set vacío."""
    org = scope_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        ids = entrenador_svc.disciplina_ids_de_usuario(db, scope_fixture["coach_sin_disc_user"])
    assert ids == set()


@pytest.mark.db
def test_disciplina_ids_de_usuario_no_entrenador(app_engine: Engine, scope_fixture: dict) -> None:
    """Un usuario que NO es entrenador (admin) -> set vacío (no rompe)."""
    org = scope_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        ids = entrenador_svc.disciplina_ids_de_usuario(db, scope_fixture["admin_user"])
    assert ids == set()


# --------------------------------------------------------------------------- #
# Asistencia: scoping por disciplina (TAREA 3)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_listar_categorias_entrenador_solo_su_disciplina(
    app_engine: Engine, scope_fixture: dict
) -> None:
    """ENTRENADOR de la disciplina A solo ve Cat A; ADMIN ve A y B."""
    org = scope_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        admin = asis_svc.listar_categorias(db, role="ADMIN", sucursal_ids=[], disciplina_ids=None)
        coach = asis_svc.listar_categorias(
            db,
            role="ENTRENADOR",
            sucursal_ids=[str(scope_fixture["suc_a"]), str(scope_fixture["suc_b"])],
            disciplina_ids={scope_fixture["disc_a"]},
        )
    admin_ids = {c.id for (c, _t) in admin}
    assert scope_fixture["cat_a"] in admin_ids and scope_fixture["cat_b"] in admin_ids
    coach_ids = {c.id for (c, _t) in coach}
    assert coach_ids == {scope_fixture["cat_a"]}, "ENTRENADOR solo ve su disciplina"


@pytest.mark.db
def test_listar_categorias_entrenador_sin_disciplinas_red_de_seguridad(
    app_engine: Engine, scope_fixture: dict
) -> None:
    """ENTRENADOR sin disciplinas (set vacío) -> RED DE SEGURIDAD: NO se filtra por
    disciplina, ve las categorías de sus sucursales (ambas aquí: A y B)."""
    org = scope_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        coach = asis_svc.listar_categorias(
            db,
            role="ENTRENADOR",
            sucursal_ids=[str(scope_fixture["suc_a"]), str(scope_fixture["suc_b"])],
            disciplina_ids=set(),
        )
    coach_ids = {c.id for (c, _t) in coach}
    # Sin filtro de disciplina: ve ambas (filtra solo por sucursal, tiene las dos).
    assert scope_fixture["cat_a"] in coach_ids
    assert scope_fixture["cat_b"] in coach_ids


@pytest.mark.db
def test_categoria_de_otra_disciplina_fuera_de_alcance(
    app_engine: Engine, scope_fixture: dict
) -> None:
    """Roster/guardar/sesiones de Cat B (disciplina B) por un ENTRENADOR de A -> CategoriaFuera."""
    org = scope_fixture["org"]
    disc_a = {scope_fixture["disc_a"]}
    sucs = [str(scope_fixture["suc_a"]), str(scope_fixture["suc_b"])]
    with Session(app_engine) as db:
        _set_org(db, org)
        # Su propia categoría (A) sí la ve.
        cat, _ses, _deps, _est = asis_svc.obtener_roster(
            db,
            categoria_id=scope_fixture["cat_a"],
            fecha=date(2026, 6, 1),
            role="ENTRENADOR",
            sucursal_ids=sucs,
            disciplina_ids=disc_a,
        )
        assert cat.id == scope_fixture["cat_a"]

        # Cat B (disciplina B) -> fuera de alcance en roster.
        with pytest.raises(asis_svc.CategoriaFuera):
            asis_svc.obtener_roster(
                db,
                categoria_id=scope_fixture["cat_b"],
                fecha=date(2026, 6, 1),
                role="ENTRENADOR",
                sucursal_ids=sucs,
                disciplina_ids=disc_a,
            )

        # Tampoco puede guardar en Cat B.
        with pytest.raises(asis_svc.CategoriaFuera):
            asis_svc.guardar_asistencia(
                db,
                org_id=org,
                categoria_id=scope_fixture["cat_b"],
                fecha=date(2026, 6, 1),
                hora=None,
                marcas=[(scope_fixture["al_b"], "PRESENTE")],
                registrado_por=scope_fixture["coach_user"],
                role="ENTRENADOR",
                sucursal_ids=sucs,
                disciplina_ids=disc_a,
            )

        # Ni ver el historial de sesiones de Cat B.
        with pytest.raises(asis_svc.CategoriaFuera):
            asis_svc.listar_sesiones(
                db,
                categoria_id=scope_fixture["cat_b"],
                role="ENTRENADOR",
                sucursal_ids=sucs,
                page=1,
                page_size=20,
                disciplina_ids=disc_a,
            )
        db.rollback()


# --------------------------------------------------------------------------- #
# Deportistas API: lista/detalle scoped por disciplina (TAREA 2)
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _token(user_id: uuid.UUID, org_id: uuid.UUID, role: str, sucursal_ids: list[str]) -> str:
    from app.core.security import create_access_token

    return create_access_token(
        user_id=str(user_id), org_id=str(org_id), role=role, sucursal_ids=sucursal_ids
    )


@pytest.mark.db
def test_deportistas_lista_y_detalle_scoped_por_disciplina(
    scope_fixture: dict,
) -> None:
    """ENTRENADOR de A ve a Ana (disc A) + Sin Disc (disc NULL, red de seguridad), pero
    NO a Bruno (disc B), y recibe 404 SOLO en el detalle de Bruno.

    ADMIN ve a todos. El total del listado respeta el alcance (Ana + Sin Disc = 2).
    """
    client = _client_or_skip()
    org = scope_fixture["org"]
    sucs = [str(scope_fixture["suc_a"]), str(scope_fixture["suc_b"])]

    admin_token = _token(scope_fixture["admin_user"], org, "ADMIN", sucs)
    coach_token = _token(scope_fixture["coach_user"], org, "ENTRENADOR", sucs)

    # ADMIN ve a Ana, Bruno y Sin Disc (>= 3 en la org).
    admin_list = client.get(
        "/api/v1/deportistas?page_size=100",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    admin_ids = {it["id"] for it in admin_list["items"]}
    assert str(scope_fixture["al_a"]) in admin_ids
    assert str(scope_fixture["al_b"]) in admin_ids

    # ENTRENADOR de A: ve Ana (disc A) y Sin Disc (disc NULL, red de seguridad); NO Bruno.
    coach_resp = client.get(
        "/api/v1/deportistas?page_size=100",
        headers={"Authorization": f"Bearer {coach_token}"},
    )
    assert coach_resp.status_code == 200
    coach_list = coach_resp.json()
    coach_ids = {it["id"] for it in coach_list["items"]}
    assert str(scope_fixture["al_a"]) in coach_ids
    assert str(scope_fixture["al_sin_disc"]) in coach_ids, "NULL siempre visible (red de seguridad)"
    assert str(scope_fixture["al_b"]) not in coach_ids
    assert coach_list["total"] == 2, "alcance = disciplina A + los de disciplina NULL"

    # Detalle: ve a Ana (200) y a Sin Disc (200, disc NULL); 404 SOLO para Bruno (disc B).
    ok = client.get(
        f"/api/v1/deportistas/{scope_fixture['al_a']}",
        headers={"Authorization": f"Bearer {coach_token}"},
    )
    assert ok.status_code == 200
    ok_null = client.get(
        f"/api/v1/deportistas/{scope_fixture['al_sin_disc']}",
        headers={"Authorization": f"Bearer {coach_token}"},
    )
    assert ok_null.status_code == 200, "deportista sin disciplina visible (red de seguridad)"
    nope = client.get(
        f"/api/v1/deportistas/{scope_fixture['al_b']}",
        headers={"Authorization": f"Bearer {coach_token}"},
    )
    assert nope.status_code == 404, "deportista de otra disciplina -> 404 (no 403)"


@pytest.mark.db
def test_deportistas_entrenador_sin_disciplinas_red_de_seguridad(scope_fixture: dict) -> None:
    """ENTRENADOR sin disciplinas -> RED DE SEGURIDAD: NO se filtra por disciplina, ve
    los deportistas de la org (sin filtro por disciplina), no lista vacía.

    Con ambas sucursales en el token y sin filtro de sucursal en el query, ve a los tres
    deportistas de la org (Ana A, Bruno B, Sin Disc)."""
    client = _client_or_skip()
    org = scope_fixture["org"]
    sucs = [str(scope_fixture["suc_a"]), str(scope_fixture["suc_b"])]
    token = _token(scope_fixture["coach_sin_disc_user"], org, "ENTRENADOR", sucs)

    resp = client.get(
        "/api/v1/deportistas?page_size=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = {it["id"] for it in data["items"]}
    assert str(scope_fixture["al_a"]) in ids
    assert str(scope_fixture["al_b"]) in ids
    assert str(scope_fixture["al_sin_disc"]) in ids
    assert data["total"] >= 3, "sin disciplinas -> ve por sucursal (red de seguridad), no vacío"
