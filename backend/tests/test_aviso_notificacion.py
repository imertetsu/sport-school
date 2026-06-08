"""Tests del epic avisos-whatsapp (notificación de avisos por WhatsApp).

Cubre el servicio `app.services.aviso_notificacion` (resolver + envío idempotente +
preview) con el `MockWhatsAppAdapter` (no envía real, acumula en `.sent`):

- **Resolver por alcance** (ORG / SUCURSAL / CATEGORIA), incl. categoría sin
  `disciplina_id` ⇒ 0 entrenadores, y dedupe por id.
- **Idempotencia (DoD crítico)**: reejecutar el envío del mismo aviso ⇒ 1 fila por
  destinatario y un solo envío (el 2º no llama al puerto).
- **Sin teléfono** ⇒ fila `SIN_TELEFONO`, `destino=NULL`, sin llamada al puerto.
- **Preview** cuenta sin insertar/enviar; los números coinciden con lo que materializa.
- **RLS fail-closed**: `aviso_notificacion` sin contexto de tenant ⇒ 0 filas.

Patrón BD idéntico al resto de la suite: `owner_engine` siembra (saltando RLS) y una
`Session(app_engine, expire_on_commit=False)` ejercita el servicio bajo RLS real fijando
`app.current_org` con `set_config(..., true)` (SET LOCAL).

GOTCHA RLS: `SET LOCAL app.current_org` se pierde tras `commit`; al re-consultar en una
sesión/conexión nueva hay que re-fijarlo (`_set_org`). Los `@pytest.mark.db` los corre
main contra Postgres recién migrado (0021).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from app.adapters.whatsapp.mock import MockWhatsAppAdapter
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def _set_org(conn, org: uuid.UUID) -> None:
    """Fija `app.current_org` para la tx (SET LOCAL vía set_config 3er arg=true)."""
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _sembrar(conn, *, org: uuid.UUID, coach_telefono: str | None, tutor_telefono: str | None):
    """Siembra una org completa para los 3 alcances.

    Estructura:
    - 1 sucursal, 1 disciplina (catálogo global), 1 categoría CON disciplina + 1 categoría
      SIN disciplina (ambas en la sucursal).
    - 1 entrenador (usuario+perfil) asignado a la sucursal (`entrenador_sucursal`) y a la
      disciplina (`entrenador_disciplina`).
    - 1 deportista en la categoría CON disciplina (sucursal_id = suc) + 1 tutor con
      `deportista_tutor`.
    - 1 aviso ORG, 1 aviso SUCURSAL, 1 aviso CATEGORIA (cat con disciplina) y 1 aviso
      CATEGORIA (cat sin disciplina).
    Devuelve los ids sembrados.
    """
    suc = uuid.uuid4()
    disciplina = uuid.uuid4()
    cat_con_disc = uuid.uuid4()
    cat_sin_disc = uuid.uuid4()
    coach_user = uuid.uuid4()
    coach = uuid.uuid4()
    deportista = uuid.uuid4()
    tutor = uuid.uuid4()
    admin_user = uuid.uuid4()
    aviso_org = uuid.uuid4()
    aviso_suc = uuid.uuid4()
    aviso_cat_con = uuid.uuid4()
    aviso_cat_sin = uuid.uuid4()
    email = f"coach_{uuid.uuid4().hex}@test.bo"

    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, estado, created_at, updated_at) "
            "VALUES (:id,'Org Avisos (test)','BO','BOB','ANIVERSARIO',true,'ACTIVA',now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
            "VALUES (:id,:org,'Sucursal Centro',now(),now())"
        ),
        {"id": str(suc), "org": str(org)},
    )
    # Disciplina: catálogo GLOBAL (sin org_id). El esquema mínimo es id + nombre.
    conn.execute(
        text(
            "INSERT INTO disciplina (id, nombre, created_at, updated_at) "
            "VALUES (:id,'Futbol',now(),now()) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(disciplina)},
    )
    conn.execute(
        text(
            "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, disciplina_id, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:suc,'Sub-14','PRINCIPIANTE',:disc,now(),now())"
        ),
        {"id": str(cat_con_disc), "org": str(org), "suc": str(suc), "disc": str(disciplina)},
    )
    conn.execute(
        text(
            "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, disciplina_id, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:suc,'Sin Disc','PRINCIPIANTE',NULL,now(),now())"
        ),
        {"id": str(cat_sin_disc), "org": str(org), "suc": str(suc)},
    )
    # Admin (para tokens del endpoint preview).
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin',true,now(),now())"
        ),
        {"id": str(admin_user), "org": str(org), "email": f"admin_{uuid.uuid4().hex}@test.bo"},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ENTRENADOR','Coach',true,now(),now())"
        ),
        {"id": str(coach_user), "org": str(org), "email": email},
    )
    conn.execute(
        text(
            "INSERT INTO entrenador (id, org_id, usuario_id, nombres, telefono, disciplinas, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:uid,'Carlos Coach',:tel,'[]'::jsonb,now(),now())"
        ),
        {"id": str(coach), "org": str(org), "uid": str(coach_user), "tel": coach_telefono},
    )
    conn.execute(
        text(
            "INSERT INTO entrenador_sucursal (id, org_id, entrenador_id, sucursal_id, created_at) "
            "VALUES (:id,:org,:ent,:suc,now())"
        ),
        {"id": str(uuid.uuid4()), "org": str(org), "ent": str(coach), "suc": str(suc)},
    )
    conn.execute(
        text(
            "INSERT INTO entrenador_disciplina (id, org_id, entrenador_id, disciplina_id, "
            "created_at) VALUES (:id,:org,:ent,:disc,now())"
        ),
        {"id": str(uuid.uuid4()), "org": str(org), "ent": str(coach), "disc": str(disciplina)},
    )
    conn.execute(
        text(
            "INSERT INTO deportista (id, org_id, sucursal_id, categoria_id, nombres, ap_paterno, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:suc,:cat,'Juan','Perez',now(),now())"
        ),
        {"id": str(deportista), "org": str(org), "suc": str(suc), "cat": str(cat_con_disc)},
    )
    conn.execute(
        text(
            "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
            "VALUES (:id,:org,'Tutora Ana',:tel,now(),now())"
        ),
        {"id": str(tutor), "org": str(org), "tel": tutor_telefono},
    )
    conn.execute(
        text(
            "INSERT INTO deportista_tutor (id, org_id, deportista_id, tutor_id, responsable_pago, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:dep,:tut,true,now(),now())"
        ),
        {"id": str(uuid.uuid4()), "org": str(org), "dep": str(deportista), "tut": str(tutor)},
    )
    # Avisos (uno por alcance). created_por = admin (auditoría).
    for aviso_id, alcance, suc_col, cat_col in (
        (aviso_org, "ORG", None, None),
        (aviso_suc, "SUCURSAL", str(suc), None),
        (aviso_cat_con, "CATEGORIA", None, str(cat_con_disc)),
        (aviso_cat_sin, "CATEGORIA", None, str(cat_sin_disc)),
    ):
        conn.execute(
            text(
                "INSERT INTO aviso (id, org_id, titulo, cuerpo, alcance, sucursal_id, "
                "categoria_id, creado_por, activo, publicado_en, created_at) "
                "VALUES (:id,:org,'Partido del sabado','Nos vemos en la cancha a las 9am.',"
                ":alc,:suc,:cat,:cp,true,now(),now())"
            ),
            {
                "id": str(aviso_id),
                "org": str(org),
                "alc": alcance,
                "suc": suc_col,
                "cat": cat_col,
                "cp": str(admin_user),
            },
        )

    return {
        "suc": suc,
        "disciplina": disciplina,
        "cat_con_disc": cat_con_disc,
        "cat_sin_disc": cat_sin_disc,
        "coach_user": coach_user,
        "coach": coach,
        "admin_user": admin_user,
        "deportista": deportista,
        "tutor": tutor,
        "aviso_org": aviso_org,
        "aviso_suc": aviso_suc,
        "aviso_cat_con": aviso_cat_con,
        "aviso_cat_sin": aviso_cat_sin,
    }


def _limpiar(conn, org: uuid.UUID, disciplina: uuid.UUID) -> None:
    """Borra todo lo sembrado de una org (orden FK-safe)."""
    conn.execute(text("DELETE FROM aviso_notificacion WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM aviso WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM deportista_tutor WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM tutor WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM entrenador_disciplina WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM entrenador_sucursal WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM entrenador WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM disciplina WHERE id = :d"), {"d": str(disciplina)})


# --------------------------------------------------------------------------- #
# Fixtures de siembra (con BD)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def org_avisos(owner_engine: Engine) -> Iterator[dict]:
    """Org con coach + tutor CON teléfono, los 4 avisos sembrados."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar(conn, org=org, coach_telefono="59177712345", tutor_telefono="59177799999")
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar(conn, org, ids["disciplina"])


@pytest.fixture()
def org_sin_telefono(owner_engine: Engine) -> Iterator[dict]:
    """Org con coach + tutor SIN teléfono (NULL)."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar(conn, org=org, coach_telefono=None, tutor_telefono=None)
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar(conn, org, ids["disciplina"])


def _aviso(db: Session, aviso_id: uuid.UUID):
    from app.models.aviso import Aviso

    a = db.get(Aviso, aviso_id)
    assert a is not None
    return a


def _count_filas(app_engine: Engine, org: uuid.UUID, aviso_id: uuid.UUID) -> int:
    with app_engine.begin() as conn:
        _set_org(conn, org)
        return conn.execute(
            text("SELECT count(*) FROM aviso_notificacion WHERE aviso_id = :a"),
            {"a": str(aviso_id)},
        ).scalar_one()


# --------------------------------------------------------------------------- #
# 1) Resolver por alcance + dedupe
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_resolver_org(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import resolver_destinatarios

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_avisos["org"])
        dests = resolver_destinatarios(
            db,
            alcance="ORG",
            sucursal_id=None,
            categoria_id=None,
            notificar_entrenadores=True,
            notificar_tutores=True,
        )
    tipos = sorted(d.tipo for d in dests)
    assert tipos == ["ENTRENADOR", "TUTOR"]
    # Dedupe por id: 1 entrenador + 1 tutor (aunque el tutor tenga 1 deportista).
    assert len(dests) == 2


@pytest.mark.db
def test_resolver_sucursal(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import resolver_destinatarios

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_avisos["org"])
        dests = resolver_destinatarios(
            db,
            alcance="SUCURSAL",
            sucursal_id=org_avisos["suc"],
            categoria_id=None,
            notificar_entrenadores=True,
            notificar_tutores=True,
        )
    assert sorted(d.tipo for d in dests) == ["ENTRENADOR", "TUTOR"]


@pytest.mark.db
def test_resolver_categoria_con_disciplina(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import resolver_destinatarios

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_avisos["org"])
        dests = resolver_destinatarios(
            db,
            alcance="CATEGORIA",
            sucursal_id=None,
            categoria_id=org_avisos["cat_con_disc"],
            notificar_entrenadores=True,
            notificar_tutores=True,
        )
    # Entrenador (via entrenador_disciplina de la disciplina de la categoría) + tutor.
    assert sorted(d.tipo for d in dests) == ["ENTRENADOR", "TUTOR"]


@pytest.mark.db
def test_resolver_categoria_sin_disciplina_cero_entrenadores(
    app_engine: Engine, org_avisos: dict
) -> None:
    from app.services.aviso_notificacion import resolver_destinatarios

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_avisos["org"])
        dests = resolver_destinatarios(
            db,
            alcance="CATEGORIA",
            sucursal_id=None,
            categoria_id=org_avisos["cat_sin_disc"],
            notificar_entrenadores=True,
            notificar_tutores=True,
        )
    # Categoría sin disciplina_id ⇒ 0 entrenadores (y 0 tutores: nadie en esa categoría).
    assert [d.tipo for d in dests if d.tipo == "ENTRENADOR"] == []


# --------------------------------------------------------------------------- #
# 2) Idempotencia (DoD crítico): 2 corridas ⇒ 1 fila/dest y un solo envío
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_idempotencia(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import enviar_aviso_whatsapp

    org = org_avisos["org"]
    aviso_id = org_avisos["aviso_org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        aviso = _aviso(db, aviso_id)
        n1 = enviar_aviso_whatsapp(
            db, aviso=aviso, port=mock, notificar_entrenadores=True, notificar_tutores=True
        )
        db.commit()
    # GOTCHA RLS: tras commit se pierde el SET LOCAL; re-fijar en una sesión nueva.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        aviso = _aviso(db, aviso_id)
        n2 = enviar_aviso_whatsapp(
            db, aviso=aviso, port=mock, notificar_entrenadores=True, notificar_tutores=True
        )
        db.commit()

    assert n1 == 2, "primer envío: 1 entrenador + 1 tutor (con teléfono)"
    assert n2 == 0, "re-ejecutar el mismo aviso no reenvía (idempotente)"
    assert len(mock.sent) == 2, "dos plantillas en total, no cuatro"

    assert _count_filas(app_engine, org, aviso_id) == 2, "1 fila por destinatario (UNIQUE)"


# --------------------------------------------------------------------------- #
# 3) Sin teléfono ⇒ SIN_TELEFONO, destino NULL, sin llamar al puerto
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_sin_telefono(app_engine: Engine, org_sin_telefono: dict) -> None:
    from app.services.aviso_notificacion import enviar_aviso_whatsapp

    org = org_sin_telefono["org"]
    aviso_id = org_sin_telefono["aviso_org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        aviso = _aviso(db, aviso_id)
        enviados = enviar_aviso_whatsapp(
            db, aviso=aviso, port=mock, notificar_entrenadores=True, notificar_tutores=True
        )
        db.commit()

    assert enviados == 0, "sin teléfono no cuenta como ENVIADO"
    assert len(mock.sent) == 0, "sin teléfono no llama al puerto"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        rows = conn.execute(
            text("SELECT estado, destino FROM aviso_notificacion WHERE aviso_id = :a"),
            {"a": str(aviso_id)},
        ).all()
    assert len(rows) == 2
    assert all(r.estado == "SIN_TELEFONO" and r.destino is None for r in rows)


# --------------------------------------------------------------------------- #
# 4) Preview cuenta sin insertar/enviar; coincide con el envío
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_preview_no_inserta_ni_envia(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import enviar_aviso_whatsapp, preview_notificacion

    org = org_avisos["org"]
    aviso_id = org_avisos["aviso_org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        conteo = preview_notificacion(
            db,
            alcance="ORG",
            sucursal_id=None,
            categoria_id=None,
            notificar_entrenadores=True,
            notificar_tutores=True,
        )

    assert conteo.entrenadores == 1
    assert conteo.tutores == 1
    assert conteo.total == 2
    assert conteo.sin_telefono == 0
    # No insertó ni llamó al puerto.
    assert len(mock.sent) == 0
    assert _count_filas(app_engine, org, aviso_id) == 0

    # Los números coinciden con lo que materializa el envío.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        aviso = _aviso(db, aviso_id)
        enviados = enviar_aviso_whatsapp(
            db, aviso=aviso, port=mock, notificar_entrenadores=True, notificar_tutores=True
        )
        db.commit()
    assert enviados == conteo.total


@pytest.mark.db
def test_preview_solo_grupo_marcado(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import preview_notificacion

    org = org_avisos["org"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        conteo = preview_notificacion(
            db,
            alcance="ORG",
            sucursal_id=None,
            categoria_id=None,
            notificar_entrenadores=True,
            notificar_tutores=False,
        )
    assert conteo.entrenadores == 1
    assert conteo.tutores == 0, "flag tutores en false ⇒ no se cuentan"
    assert conteo.total == 1


# --------------------------------------------------------------------------- #
# 5) RLS fail-closed: aviso_notificacion sin contexto ⇒ 0 filas
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_rls_fail_closed(app_engine: Engine, org_avisos: dict) -> None:
    from app.services.aviso_notificacion import enviar_aviso_whatsapp

    org = org_avisos["org"]
    aviso_id = org_avisos["aviso_org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        aviso = _aviso(db, aviso_id)
        enviar_aviso_whatsapp(
            db, aviso=aviso, port=mock, notificar_entrenadores=True, notificar_tutores=True
        )
        db.commit()

    # Sin contexto de tenant: aviso_notificacion devuelve 0 filas (fail-closed).
    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM aviso_notificacion")).scalar_one()
    assert count == 0, "sin contexto de tenant, aviso_notificacion devuelve 0 filas"


# --------------------------------------------------------------------------- #
# 6) Recorte del cuerpo (lógica pura, sin BD)
# --------------------------------------------------------------------------- #
def test_recortar_cuerpo() -> None:
    from app.services.aviso_notificacion import _CUERPO_MAX, _recortar_cuerpo

    corto = "Nos vemos a las 9am"
    assert _recortar_cuerpo(corto) == corto
    largo = "x" * (_CUERPO_MAX + 50)
    recortado = _recortar_cuerpo(largo)
    assert len(recortado) == _CUERPO_MAX
    assert recortado.endswith("…")


# Evita el warning de import no usado de `date` si alguna fixture cambia.
_ = date
