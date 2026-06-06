"""Tests del Muro de avisos (RF-COM-01, contratos C1/C2).

Dos capas, igual que el resto de la suite:

- **Sin BD** (rápidos, siempre corren): invariante alcance<->ids del schema
  (SUCURSAL sin sucursal_id -> 422, etc.), helpers puros (`es_expirado`,
  `aviso_visible_para_entrenador`, `_sucursales_permitidas`) y autorización pura de
  `require_role` (ADMIN pasa / ENTRENADOR -> 403).
- **Con BD** (`@pytest.mark.db`, requieren Postgres migrado con `0006` + RLS + rol
  `latinosport_app`): scoping por rol del feed (el entrenador NO ve un aviso de sucursal
  ajena ni vencidos, pero sí ORG y los de su sucursal/categoría), invariante 422 a
  nivel servicio (`ValueError`), y soft-delete (desaparece del feed; la fila sigue
  con `activo=false`, sin borrado físico).

Se usa `owner_engine` para sembrar (saltando RLS) y una `Session` sobre `app_engine`
(rol `latinosport_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS real. Skip si
no hay BD (ver conftest). Los `@pytest.mark.db` los corre main en F4 contra Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from app.core.tenant import CurrentUser, require_role
from app.schemas.aviso import AvisoCreate
from app.services import aviso as svc
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Invariante del schema (sin BD) -> 422
# --------------------------------------------------------------------------- #
def test_aviso_org_ok() -> None:
    obj = AvisoCreate(titulo="  Hola  ", cuerpo="  Cuerpo  ", alcance="ORG")
    assert obj.titulo == "Hola"  # normaliza (strip)
    assert obj.cuerpo == "Cuerpo"
    assert obj.sucursal_id is None and obj.categoria_id is None


def test_aviso_sucursal_sin_sucursal_id_falla() -> None:
    """alcance=SUCURSAL sin `sucursal_id` -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        AvisoCreate(titulo="T", cuerpo="C", alcance="SUCURSAL")


def test_aviso_categoria_sin_categoria_id_falla() -> None:
    """alcance=CATEGORIA sin `categoria_id` -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        AvisoCreate(titulo="T", cuerpo="C", alcance="CATEGORIA")


def test_aviso_org_con_sucursal_id_falla() -> None:
    """alcance=ORG con `sucursal_id` -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        AvisoCreate(titulo="T", cuerpo="C", alcance="ORG", sucursal_id=uuid.uuid4())


def test_aviso_sucursal_con_categoria_id_falla() -> None:
    """alcance=SUCURSAL no admite `categoria_id` -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        AvisoCreate(
            titulo="T",
            cuerpo="C",
            alcance="SUCURSAL",
            sucursal_id=uuid.uuid4(),
            categoria_id=uuid.uuid4(),
        )


def test_aviso_titulo_vacio_falla() -> None:
    with pytest.raises(ValidationError):
        AvisoCreate(titulo="   ", cuerpo="C", alcance="ORG")


# --------------------------------------------------------------------------- #
# Helpers puros (sin BD)
# --------------------------------------------------------------------------- #
def test_es_expirado() -> None:
    hoy = date(2026, 6, 6)
    assert svc.es_expirado(None, hoy) is False  # sin caducidad nunca expira
    assert svc.es_expirado(date(2026, 6, 5), hoy) is True  # ayer -> vencido
    assert svc.es_expirado(date(2026, 6, 6), hoy) is False  # hoy aún vigente
    assert svc.es_expirado(date(2026, 6, 7), hoy) is False  # futuro vigente


def test_sucursales_permitidas() -> None:
    assert svc._sucursales_permitidas("ADMIN", ["x"]) is None  # ADMIN ve todas
    s1 = str(uuid.uuid4())
    assert svc._sucursales_permitidas("ENTRENADOR", [s1, "malo"]) == {uuid.UUID(s1)}
    assert svc._sucursales_permitidas("ENTRENADOR", []) == set()


def test_aviso_visible_para_entrenador() -> None:
    suc_propia = uuid.uuid4()
    suc_ajena = uuid.uuid4()
    permitidas = {suc_propia}

    # ORG: siempre visible.
    assert svc.aviso_visible_para_entrenador(
        alcance="ORG", sucursal_id=None, categoria_sucursal_id=None, permitidas=permitidas
    )
    # SUCURSAL propia / ajena.
    assert svc.aviso_visible_para_entrenador(
        alcance="SUCURSAL",
        sucursal_id=suc_propia,
        categoria_sucursal_id=None,
        permitidas=permitidas,
    )
    assert not svc.aviso_visible_para_entrenador(
        alcance="SUCURSAL",
        sucursal_id=suc_ajena,
        categoria_sucursal_id=None,
        permitidas=permitidas,
    )
    # CATEGORIA cuya sucursal es propia / ajena.
    assert svc.aviso_visible_para_entrenador(
        alcance="CATEGORIA",
        sucursal_id=None,
        categoria_sucursal_id=suc_propia,
        permitidas=permitidas,
    )
    assert not svc.aviso_visible_para_entrenador(
        alcance="CATEGORIA",
        sucursal_id=None,
        categoria_sucursal_id=suc_ajena,
        permitidas=permitidas,
    )


# --------------------------------------------------------------------------- #
# Autorización (sin BD) -> caso: ADMIN pasa / ENTRENADOR -> 403 en escritura
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role)


def test_require_role_admin_pasa() -> None:
    checker = require_role("ADMIN")
    user = _user("ADMIN")
    assert checker(user=user) is user


def test_require_role_entrenador_403() -> None:
    """ENTRENADOR -> HTTPException 403 (no puede publicar/editar/eliminar)."""
    checker = require_role("ADMIN")
    with pytest.raises(HTTPException) as exc:
        checker(user=_user("ENTRENADOR"))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Fixture de datos con BD: 1 org, 2 sucursales A/B, 1 categoría en B, 1 usuario admin.
# Avisos: ORG, SUCURSAL A, SUCURSAL B, CATEGORIA (de B), y uno SUCURSAL A vencido.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def aviso_fixture(owner_engine: Engine) -> Iterator[dict]:
    org = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()
    cat_b = uuid.uuid4()
    usuario = uuid.uuid4()

    av_org = uuid.uuid4()
    av_suc_a = uuid.uuid4()
    av_suc_b = uuid.uuid4()
    av_cat_b = uuid.uuid4()
    av_suc_a_vencido = uuid.uuid4()

    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    futuro = hoy + timedelta(days=30)

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Avisos (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Avisos',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"av_{uuid.uuid4().hex}@test.bo"},
        )
        for suc_id, nom in ((suc_a, "Suc A"), (suc_b, "Suc B")):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(suc_id), "org": str(org), "nom": nom},
            )
        conn.execute(
            text(
                "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Cat B','PRINCIPIANTE',now(),now())"
            ),
            {"id": str(cat_b), "org": str(org), "suc": str(suc_b)},
        )

        # Avisos: (id, alcance, sucursal_id, categoria_id, vigente_hasta, titulo)
        avisos: list[
            tuple[uuid.UUID, str, uuid.UUID | None, uuid.UUID | None, date | None, str]
        ] = [
            (av_org, "ORG", None, None, None, "Aviso ORG"),
            (av_suc_a, "SUCURSAL", suc_a, None, futuro, "Aviso Suc A"),
            (av_suc_b, "SUCURSAL", suc_b, None, futuro, "Aviso Suc B"),
            (av_cat_b, "CATEGORIA", None, cat_b, futuro, "Aviso Cat B"),
            (av_suc_a_vencido, "SUCURSAL", suc_a, None, ayer, "Aviso Suc A vencido"),
        ]
        for aid, av_alcance, av_suc, av_cat, av_vig, av_titulo in avisos:
            conn.execute(
                text(
                    "INSERT INTO aviso (id, org_id, titulo, cuerpo, alcance, sucursal_id, "
                    "categoria_id, vigente_hasta, creado_por, activo, publicado_en, created_at) "
                    "VALUES (:id,:org,:tit,'cuerpo',:alc,:suc,:cat,:vig,:cp,true,now(),now())"
                ),
                {
                    "id": str(aid),
                    "org": str(org),
                    "tit": av_titulo,
                    "alc": av_alcance,
                    "suc": str(av_suc) if av_suc is not None else None,
                    "cat": str(av_cat) if av_cat is not None else None,
                    "vig": av_vig,
                    "cp": str(usuario),
                },
            )

    yield {
        "org": org,
        "suc_a": suc_a,
        "suc_b": suc_b,
        "cat_b": cat_b,
        "usuario": usuario,
        "av_org": av_org,
        "av_suc_a": av_suc_a,
        "av_suc_b": av_suc_b,
        "av_cat_b": av_cat_b,
        "av_suc_a_vencido": av_suc_a_vencido,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM aviso WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Scoping por rol del feed (con BD)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_admin_ve_todos_los_activos(app_engine: Engine, aviso_fixture: dict) -> None:
    """ADMIN ve todos los activos no vencidos; con incluir_expirados, también el vencido."""
    org = aviso_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        page = svc.feed(db, role="ADMIN", sucursal_ids=[], page_size=100)
        page_exp = svc.feed(
            db, role="ADMIN", sucursal_ids=[], incluir_expirados=True, page_size=100
        )

    ids = {it.id for it in page.items}
    # 4 activos no vencidos (ORG, Suc A, Suc B, Cat B); el vencido NO sin el flag.
    assert aviso_fixture["av_org"] in ids
    assert aviso_fixture["av_suc_a"] in ids
    assert aviso_fixture["av_suc_b"] in ids
    assert aviso_fixture["av_cat_b"] in ids
    assert aviso_fixture["av_suc_a_vencido"] not in ids
    assert page.total == 4

    ids_exp = {it.id for it in page_exp.items}
    assert aviso_fixture["av_suc_a_vencido"] in ids_exp, "incluir_expirados trae el vencido"
    assert page_exp.total == 5
    vencido = next(it for it in page_exp.items if it.id == aviso_fixture["av_suc_a_vencido"])
    assert vencido.expirado is True


@pytest.mark.db
def test_entrenador_no_ve_aviso_de_sucursal_ajena(app_engine: Engine, aviso_fixture: dict) -> None:
    """ENTRENADOR de Suc A: ve ORG + Suc A; NO ve Suc B ni la categoría de B ni vencidos."""
    org = aviso_fixture["org"]
    coach_sucs = [str(aviso_fixture["suc_a"])]
    with Session(app_engine) as db:
        _set_org(db, org)
        page = svc.feed(db, role="ENTRENADOR", sucursal_ids=coach_sucs, page_size=100)

    ids = {it.id for it in page.items}
    assert aviso_fixture["av_org"] in ids, "El entrenador ve los de alcance ORG"
    assert aviso_fixture["av_suc_a"] in ids, "Ve los de su propia sucursal"
    assert aviso_fixture["av_suc_b"] not in ids, "NO ve avisos de sucursal ajena"
    assert aviso_fixture["av_cat_b"] not in ids, "NO ve la categoría cuya sucursal es ajena"
    assert aviso_fixture["av_suc_a_vencido"] not in ids, "NO ve avisos vencidos"
    assert page.total == 2


@pytest.mark.db
def test_entrenador_ve_categoria_de_su_sucursal(app_engine: Engine, aviso_fixture: dict) -> None:
    """ENTRENADOR de Suc B ve la CATEGORIA cuya sucursal (B) está en su alcance."""
    org = aviso_fixture["org"]
    coach_sucs = [str(aviso_fixture["suc_b"])]
    with Session(app_engine) as db:
        _set_org(db, org)
        page = svc.feed(db, role="ENTRENADOR", sucursal_ids=coach_sucs, page_size=100)

    ids = {it.id for it in page.items}
    assert aviso_fixture["av_org"] in ids
    assert aviso_fixture["av_suc_b"] in ids
    assert aviso_fixture["av_cat_b"] in ids, "Ve la categoría de su sucursal (Cat B)"
    assert aviso_fixture["av_suc_a"] not in ids, "NO ve la sucursal ajena (A)"
    assert page.total == 3


# --------------------------------------------------------------------------- #
# Invariante 422 a nivel servicio (con BD; el servicio re-valida)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_crear_invariante_sucursal_sin_id_falla(app_engine: Engine, aviso_fixture: dict) -> None:
    """El servicio re-valida la invariante: SUCURSAL sin sucursal_id -> ValueError (=> 422).

    Se construye `AvisoCreate` con `model_construct` para saltar el validator del
    schema y comprobar la defensa en profundidad del servicio.
    """
    org = aviso_fixture["org"]
    usuario = aviso_fixture["usuario"]
    invalido = AvisoCreate.model_construct(
        titulo="T",
        cuerpo="C",
        alcance="SUCURSAL",
        sucursal_id=None,
        categoria_id=None,
        vigente_hasta=None,
    )
    with Session(app_engine) as db:
        _set_org(db, org)
        with pytest.raises(ValueError):
            svc.crear(db, invalido, org_id=org, usuario_id=usuario)


# --------------------------------------------------------------------------- #
# Soft-delete: desaparece del feed; la fila sigue con activo=false
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_soft_delete_desaparece_del_feed_pero_persiste(
    app_engine: Engine, aviso_fixture: dict
) -> None:
    """DELETE -> activo=false: el aviso sale del feed pero la fila NO se borra físicamente."""
    org = aviso_fixture["org"]
    av_id = aviso_fixture["av_org"]

    with Session(app_engine) as db:
        _set_org(db, org)
        svc.eliminar(db, av_id)
        db.commit()

    # Ya no aparece en el feed (ni ADMIN).
    with Session(app_engine) as db:
        _set_org(db, org)
        page = svc.feed(db, role="ADMIN", sucursal_ids=[], incluir_expirados=True, page_size=100)
    assert av_id not in {it.id for it in page.items}, "El aviso soft-eliminado sale del feed"

    # Pero la fila sigue existiendo con activo=false (sin borrado físico).
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        activo = conn.execute(
            text("SELECT activo FROM aviso WHERE id = :id"), {"id": str(av_id)}
        ).scalar_one()
    assert activo is False, "La fila persiste con activo=false (soft-delete, no físico)"


@pytest.mark.db
def test_eliminar_inexistente_404(app_engine: Engine, aviso_fixture: dict) -> None:
    """Eliminar un aviso inexistente -> AvisoNoEncontrado (el router lo traduce a 404)."""
    org = aviso_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        with pytest.raises(svc.AvisoNoEncontrado):
            svc.eliminar(db, uuid.uuid4())


@pytest.mark.db
def test_crear_y_editar_setea_creado_por(app_engine: Engine, aviso_fixture: dict) -> None:
    """crear setea creado_por=token; editar no reescribe el autor y respeta la invariante."""
    org = aviso_fixture["org"]
    usuario = aviso_fixture["usuario"]
    with Session(app_engine) as db:
        _set_org(db, org)
        out = svc.crear(
            db,
            AvisoCreate(titulo="Nuevo", cuerpo="Cuerpo", alcance="ORG"),
            org_id=org,
            usuario_id=usuario,
        )
        nuevo_id = out.id
        db.commit()
    assert out.creado_por_nombre == "Admin Avisos", "Resuelve el nombre del autor del token"
    assert out.alcance == "ORG" and out.sucursal is None and out.categoria is None
    assert out.expirado is False

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        cp = conn.execute(
            text("SELECT creado_por FROM aviso WHERE id = :id"), {"id": str(nuevo_id)}
        ).scalar_one()
    assert str(cp) == str(usuario), "creado_por = usuario del token (auditoría)"
