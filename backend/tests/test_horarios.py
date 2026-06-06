"""Tests del módulo de Horarios (epic Programación de clases, C2/C3).

- Lógica pura (sin BD): `dia_label`, cálculo de fechas por `dia_semana`
  (`fechas_de_horario`), scoping de sucursales por rol, y validación de los
  schemas (`hora_fin > hora_inicio` -> 422).
- Tests marcados `db` (requieren Postgres migrado con 0007 + RLS): CRUD scoped
  por rol, generación idempotente (re-correr no duplica sesiones; reutiliza el
  get-or-create de Asistencia), y recordatorio (setea la marca y no reenvía).

Se usa `owner_engine` para sembrar (saltando RLS) y una Session sobre `app_engine`
(rol `cantera_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS real. Skip si
no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time

import pytest
from app.schemas.horarios import HorarioCreate, HorarioUpdate, dia_label
from app.services import horarios as svc
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Lógica pura (sin BD)
# --------------------------------------------------------------------------- #
def test_dia_label_lunes_a_domingo() -> None:
    assert dia_label(0) == "Lunes"
    assert dia_label(6) == "Domingo"


def test_dia_label_fuera_de_rango() -> None:
    with pytest.raises(ValueError):
        dia_label(7)


def test_fechas_de_horario_lunes_en_ventana() -> None:
    """Lunes (dia_semana=0) en [2026-06-01(lun), +7]: 2026-06-01 y 2026-06-08."""
    hoy = date(2026, 6, 1)  # es lunes
    assert hoy.weekday() == 0
    fechas = svc.fechas_de_horario(0, hoy, 7)
    assert fechas == [date(2026, 6, 1), date(2026, 6, 8)]


def test_fechas_de_horario_dia_sin_ocurrencia_en_ventana_corta() -> None:
    """Domingo (6) en [2026-06-01(lun), +3] no ocurre -> lista vacía."""
    hoy = date(2026, 6, 1)
    assert svc.fechas_de_horario(6, hoy, 3) == []


def test_fechas_de_horario_ventana_inclusiva_extremo() -> None:
    """El extremo `hoy+dias_ventana` se incluye (miércoles a +2 desde lunes)."""
    hoy = date(2026, 6, 1)  # lunes
    assert svc.fechas_de_horario(2, hoy, 2) == [date(2026, 6, 3)]  # miércoles


def test_admin_ve_todas_las_sucursales() -> None:
    assert svc._sucursales_permitidas("ADMIN", ["x"]) is None


def test_entrenador_limitado_a_sus_sucursales() -> None:
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    permitidas = svc._sucursales_permitidas("ENTRENADOR", [s1, s2, "no-uuid"])
    assert permitidas == {uuid.UUID(s1), uuid.UUID(s2)}


def test_schema_rechaza_hora_fin_menor_o_igual() -> None:
    """hora_fin <= hora_inicio -> ValidationError (=> 422 en la API)."""
    cat = uuid.uuid4()
    with pytest.raises(ValidationError):
        HorarioCreate(
            categoria_id=cat,
            dia_semana=0,
            hora_inicio=time(19, 0),
            hora_fin=time(18, 0),
        )
    with pytest.raises(ValidationError):
        HorarioCreate(
            categoria_id=cat,
            dia_semana=0,
            hora_inicio=time(18, 0),
            hora_fin=time(18, 0),
        )


def test_schema_rechaza_dia_semana_fuera_de_rango() -> None:
    with pytest.raises(ValidationError):
        HorarioCreate(
            categoria_id=uuid.uuid4(),
            dia_semana=7,
            hora_inicio=time(18, 0),
            hora_fin=time(19, 0),
        )


def test_schema_acepta_horario_valido() -> None:
    h = HorarioCreate(
        categoria_id=uuid.uuid4(),
        dia_semana=0,
        hora_inicio=time(18, 0),
        hora_fin=time(19, 30),
    )
    assert h.dia_semana == 0


# --------------------------------------------------------------------------- #
# Fixture de datos (org + 2 sucursales A/B + categoría A/B + alumnos/tutores)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def hor_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursales A/B + categoría A/B + 2 alumnos en A (con tutores).

    Devuelve ids. Limpia al final (orden FK-safe).
    """
    org = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()
    cat_a = uuid.uuid4()
    cat_b = uuid.uuid4()
    al_a1 = uuid.uuid4()
    al_a2 = uuid.uuid4()
    tut_1 = uuid.uuid4()
    tut_2 = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Hor (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        for suc_id, nom in ((suc_a, "Suc A"), (suc_b, "Suc B")):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(suc_id), "org": str(org), "nom": nom},
            )
        for cat_id, suc_id, nom in ((cat_a, suc_a, "Cat A"), (cat_b, suc_b, "Cat B")):
            conn.execute(
                text(
                    "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:nom,'PRINCIPIANTE',now(),now())"
                ),
                {"id": str(cat_id), "org": str(org), "suc": str(suc_id), "nom": nom},
            )
        for al_id, nom in ((al_a1, "Ana"), (al_a2, "Bruno")):
            conn.execute(
                text(
                    "INSERT INTO alumno (id, org_id, sucursal_id, categoria_id, nombres, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:cat,:nom,now(),now())"
                ),
                {
                    "id": str(al_id),
                    "org": str(org),
                    "suc": str(suc_a),
                    "cat": str(cat_a),
                    "nom": nom,
                },
            )
        for tut_id, nom in ((tut_1, "Tutor 1"), (tut_2, "Tutor 2")):
            conn.execute(
                text(
                    "INSERT INTO tutor (id, org_id, nombres, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(tut_id), "org": str(org), "nom": nom},
            )
        for al_id, tut_id in ((al_a1, tut_1), (al_a2, tut_2)):
            conn.execute(
                text(
                    "INSERT INTO alumno_tutor (id, org_id, alumno_id, tutor_id, "
                    "responsable_pago, created_at, updated_at) "
                    "VALUES (:id,:org,:al,:tut,true,now(),now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org),
                    "al": str(al_id),
                    "tut": str(tut_id),
                },
            )

    yield {
        "org": org,
        "suc_a": suc_a,
        "suc_b": suc_b,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "al_a1": al_a1,
        "al_a2": al_a2,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM asistencia WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sesion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM horario_clase WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM alumno_tutor WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM tutor WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# CRUD + scoping por rol (con BD)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_crud_y_scoping_por_rol(app_engine: Engine, hor_fixture: dict) -> None:
    """ADMIN crea/lista/edita/borra-soft; ENTRENADOR de Suc A solo ve los suyos."""
    org = hor_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)

        # ADMIN crea un horario en Cat A (lunes 18:00–19:30).
        out = svc.crear(
            db,
            HorarioCreate(
                categoria_id=hor_fixture["cat_a"],
                dia_semana=0,
                hora_inicio=time(18, 0),
                hora_fin=time(19, 30),
            ),
            org_id=org,
            role="ADMIN",
            sucursal_ids=[],
        )
        assert out.dia_label == "Lunes"
        assert out.sucursal.id == hor_fixture["suc_a"]
        assert out.activo is True
        horario_id = out.id

        # Duplicado exacto -> HorarioDuplicado (409).
        with pytest.raises(svc.HorarioDuplicado):
            svc.crear(
                db,
                HorarioCreate(
                    categoria_id=hor_fixture["cat_a"],
                    dia_semana=0,
                    hora_inicio=time(18, 0),
                    hora_fin=time(20, 0),
                ),
                org_id=org,
                role="ADMIN",
                sucursal_ids=[],
            )

        # ADMIN lista -> ve el horario.
        admin_list = svc.listar(db, role="ADMIN", sucursal_ids=[])
        assert {h.id for h in admin_list} == {horario_id}

        # ENTRENADOR de Suc A lo ve; de Suc B no ve nada.
        coach_a = svc.listar(db, role="ENTRENADOR", sucursal_ids=[str(hor_fixture["suc_a"])])
        assert {h.id for h in coach_a} == {horario_id}
        coach_b = svc.listar(db, role="ENTRENADOR", sucursal_ids=[str(hor_fixture["suc_b"])])
        assert coach_b == []

        # Editar (mover a martes 17:00–18:00).
        editado = svc.editar(
            db,
            horario_id,
            HorarioUpdate(
                categoria_id=hor_fixture["cat_a"],
                dia_semana=1,
                hora_inicio=time(17, 0),
                hora_fin=time(18, 0),
            ),
            role="ADMIN",
            sucursal_ids=[],
        )
        assert editado.dia_label == "Martes"

        # Soft-delete -> desaparece del listado.
        svc.eliminar(db, horario_id)
        assert svc.listar(db, role="ADMIN", sucursal_ids=[]) == []

        db.rollback()


@pytest.mark.db
def test_entrenador_no_crea_en_categoria_fuera(app_engine: Engine, hor_fixture: dict) -> None:
    """ENTRENADOR de Suc A no puede crear en Cat B (de Suc B) -> CategoriaFuera (403)."""
    org = hor_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        with pytest.raises(svc.CategoriaFuera):
            svc.crear(
                db,
                HorarioCreate(
                    categoria_id=hor_fixture["cat_b"],
                    dia_semana=0,
                    hora_inicio=time(18, 0),
                    hora_fin=time(19, 0),
                ),
                org_id=org,
                role="ENTRENADOR",
                sucursal_ids=[str(hor_fixture["suc_a"])],
            )
        db.rollback()


# --------------------------------------------------------------------------- #
# Generación idempotente (con BD) — reutiliza get-or-create de Asistencia
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_generacion_idempotente(app_engine: Engine, hor_fixture: dict) -> None:
    """Generar crea sesiones de la ventana; re-correr NO duplica (UNIQUE de sesion)."""
    org = hor_fixture["org"]
    hoy = date(2026, 6, 1)  # lunes

    with Session(app_engine) as db:
        _set_org(db, org)
        svc.crear(
            db,
            HorarioCreate(
                categoria_id=hor_fixture["cat_a"],
                dia_semana=0,  # lunes
                hora_inicio=time(18, 0),
                hora_fin=time(19, 30),
            ),
            org_id=org,
            role="ADMIN",
            sucursal_ids=[],
        )
        db.commit()

    # 1ª corrida: ventana de 7 días desde lunes -> 2 lunes (06-01 y 06-08).
    with Session(app_engine) as db:
        _set_org(db, org)
        creadas1 = svc.generar_sesiones_programadas(db, org, hoy=hoy, dias_ventana=7)
        db.commit()
    assert creadas1 == 2

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n_ses = conn.execute(
            text("SELECT count(*) FROM sesion WHERE org_id=:o AND horario_id IS NOT NULL"),
            {"o": str(org)},
        ).scalar_one()
    assert n_ses == 2

    # 2ª corrida idéntica: idempotente -> 0 nuevas, sigue habiendo 2 sesiones.
    with Session(app_engine) as db:
        _set_org(db, org)
        creadas2 = svc.generar_sesiones_programadas(db, org, hoy=hoy, dias_ventana=7)
        db.commit()
    assert creadas2 == 0

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n_ses2 = conn.execute(
            text("SELECT count(*) FROM sesion WHERE org_id=:o"), {"o": str(org)}
        ).scalar_one()
    assert n_ses2 == 2, "Re-correr no debe duplicar sesiones"


# --------------------------------------------------------------------------- #
# Recordatorio (con BD) — setea la marca y no reenvía
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_recordatorio_setea_marca_y_no_reenvia(app_engine: Engine, hor_fixture: dict) -> None:
    """Recordatorio marca `recordatorio_enviado_en`; re-correr no vuelve a notificar."""
    org = hor_fixture["org"]
    ahora = datetime(2026, 6, 1, 17, 0, tzinfo=UTC)  # 17:00 UTC
    # Clase a las 18:00 (dentro de [17:00, 17:00+2h]).
    fecha = ahora.date()
    sesion_id = uuid.uuid4()
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        conn.execute(
            text(
                "INSERT INTO sesion (id, org_id, categoria_id, fecha, hora, created_at) "
                "VALUES (:id,:org,:cat,:fecha,'18:00',now())"
            ),
            {
                "id": str(sesion_id),
                "org": str(org),
                "cat": str(hor_fixture["cat_a"]),
                "fecha": fecha.isoformat(),
            },
        )

    # 1ª corrida: notifica (1 sesión) y setea la marca.
    with Session(app_engine) as db:
        _set_org(db, org)
        n1 = svc.enviar_recordatorios_clase(db, org, ahora=ahora, horas=2)
        db.commit()
    assert n1 == 1

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        marca = conn.execute(
            text("SELECT recordatorio_enviado_en FROM sesion WHERE id=:s"),
            {"s": str(sesion_id)},
        ).scalar_one()
    assert marca is not None, "Debe setear recordatorio_enviado_en"

    # 2ª corrida: idempotente -> no reenvía.
    with Session(app_engine) as db:
        _set_org(db, org)
        n2 = svc.enviar_recordatorios_clase(db, org, ahora=ahora, horas=2)
        db.commit()
    assert n2 == 0, "No debe reenviar (marca ya no es NULL)"
