"""Seed idempotente de datos de ejemplo (estilo Bolivia).

Crea: 1 organización (Bolivia/BOB), 1 usuario ADMIN, 1 usuario+entrenador, 2
sucursales (Centro, Cala Cala), categorías (Sub-10/14/17) y ~8 alumnos con
tutores + consentimiento + inscripción + ficha médica.

IMPORTANTE (RLS): `organizacion` NO tiene RLS, así que se inserta directo. El
resto son tablas tenant: antes de insertarlas se fija `app.current_org` en la
sesión (`set_config(..., true)` por transacción). Para que esto funcione con el
rol `cantera_app`, la migración de db-dev debe haber concedido los GRANTs (C2).

Idempotencia: usa claves naturales (email de usuario, nombre de org/sucursal,
CI de alumno) para no duplicar en re-ejecuciones.

Cómo correr (desde `backend/`, con la BD migrada):
    .venv\\Scripts\\python -m app.seed          # Windows
    .venv/bin/python -m app.seed                # Linux/Mac
Requiere `DATABASE_URL` apuntando a la BD (app o owner). Alternativa: correrlo
con `MIGRATION_DATABASE_URL` (rol owner) exportado como `DATABASE_URL`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.alumno import Alumno
from app.models.alumno_tutor import AlumnoTutor
from app.models.asistencia import Asistencia
from app.models.aviso import Aviso
from app.models.categoria import Categoria
from app.models.consentimiento import Consentimiento
from app.models.cuota import Cuota
from app.models.egreso import Egreso
from app.models.entrenador import Entrenador
from app.models.horario_clase import HorarioClase
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota
from app.models.sesion import Sesion
from app.models.solicitud_registro import SolicitudRegistro
from app.models.sucursal import Sucursal
from app.models.tutor import Tutor
from app.models.usuario import Usuario
from app.services.generacion import generar_cuotas_org

ADMIN_EMAIL = "admin@cantera.bo"
ADMIN_PASS = "admin1234"
COACH_EMAIL = "coach@cantera.bo"
COACH_PASS = "coach1234"
ORG_NOMBRE = "Academia Andina"


def _set_org_context(db: Session, org_id: uuid.UUID) -> None:
    """Fija el contexto de tenant en la sesión para insertar tablas con RLS."""
    db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})


def _get_or_create_org(db: Session) -> Organizacion:
    org = db.execute(
        select(Organizacion).where(Organizacion.nombre == ORG_NOMBRE)
    ).scalar_one_or_none()
    if org is not None:
        return org
    org = Organizacion(
        nombre=ORG_NOMBRE,
        pais="BO",
        moneda="BOB",
        regimen_fiscal="GENERAL",
        modo_cobro_default="ANIVERSARIO",
        dia_corte_fijo=None,
        prorratea_primer_periodo=True,
    )
    db.add(org)
    db.flush()
    return org


def _get_or_create_usuario(
    db: Session, org_id: uuid.UUID, *, email: str, password: str, role: str, nombre: str
) -> Usuario:
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
    if u is not None:
        return u
    u = Usuario(
        org_id=org_id,
        email=email,
        password_hash=hash_password(password),
        role=role,
        nombre=nombre,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _get_or_create_sucursal(
    db: Session, org_id: uuid.UUID, *, nombre: str, direccion: str
) -> Sucursal:
    s = db.execute(
        select(Sucursal).where(Sucursal.org_id == org_id, Sucursal.nombre == nombre)
    ).scalar_one_or_none()
    if s is not None:
        return s
    s = Sucursal(org_id=org_id, nombre=nombre, direccion=direccion)
    db.add(s)
    db.flush()
    return s


def _get_or_create_categoria(
    db: Session,
    org_id: uuid.UUID,
    *,
    sucursal_id: uuid.UUID,
    nombre: str,
    nivel: str,
    rango_edad: str,
) -> Categoria:
    c = db.execute(
        select(Categoria).where(
            Categoria.org_id == org_id,
            Categoria.sucursal_id == sucursal_id,
            Categoria.nombre == nombre,
        )
    ).scalar_one_or_none()
    if c is not None:
        return c
    c = Categoria(
        org_id=org_id,
        sucursal_id=sucursal_id,
        nombre=nombre,
        nivel=nivel,
        rango_edad=rango_edad,
    )
    db.add(c)
    db.flush()
    return c


# Datos de ejemplo (design-system.md): nombres bolivianos, CI "NNNNNNN LP".
_ALUMNOS = [
    ("Quispe", "Mamani", "Mateo", "9123451 LP", date(2012, 3, 14), "Fútbol",
     "O+", "Penicilina", "Asma leve (inhalador)"),
    ("Condori", "Huanca", "Valentina", "9123452 LP", date(2010, 7, 2), "Fútbol",
     "A+", None, None),
    ("Vargas", "Apaza", "Santiago", "9123453 LP", date(2009, 11, 20), "Básquetbol",
     "B+", "Polen", None),
    ("Mamani", "Ticona", "Diego", "9123454 LP", date(2013, 1, 9), "Natación",
     "O-", None, "Miopía"),
    ("Choque", "Calle", "Luciana", "9123455 LP", date(2011, 5, 30), "Fútbol",
     "AB+", "Maní", None),
    ("Gutiérrez", "Rojas", "Sebastián", "9123456 LP", date(2008, 9, 12), "Básquetbol",
     "A-", None, None),
    ("Aliaga", "Cuéllar", "Daniela", "9123457 LP", date(2014, 2, 25), "Natación",
     "O+", "Lactosa", "Asma leve"),
    ("Flores", "Nina", "Joaquín", "9123458 LP", date(2010, 12, 5), "Fútbol",
     "B-", None, None),
]


def _seed_cobranza(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Genera cuotas iniciales y deja estados variados para el Panel (idempotente).

    1. Corre el motor de generación (primera + siguientes vencidas) por inscripción.
    2. Marca como VENCIDO las cuotas PENDIENTE cuyo `vence_el` ya pasó.
    3. Deja algunas PAGADO (con su `pago` EFECTIVO CONFIRMADO + puente) para que el
       KPI de ingresos y la tabla tengan datos. Todo idempotente por claves.
    """
    hoy = date.today()
    creadas = generar_cuotas_org(db, org_id=org_id, hoy=hoy)

    # Marcar VENCIDO las PENDIENTE ya pasadas de fecha (idempotente por estado).
    cuotas = (
        db.execute(select(Cuota).order_by(Cuota.vence_el)).scalars().all()
    )
    vencidas = 0
    for c in cuotas:
        if c.estado == "PENDIENTE" and c.vence_el < hoy:
            c.estado = "VENCIDO"
            vencidas += 1
    db.flush()

    # Dejar algunas PAGADO con su pago EFECTIVO (1 de cada 3 inscripciones).
    inscripciones = (
        db.execute(select(Inscripcion).where(Inscripcion.estado == "ACTIVA")).scalars().all()
    )
    pagadas = 0
    for idx, insc in enumerate(inscripciones):
        if idx % 3 != 0:
            continue
        # primera cuota de la inscripción
        cuota = (
            db.execute(
                select(Cuota)
                .where(Cuota.inscripcion_id == insc.id)
                .order_by(Cuota.periodo_inicio)
            )
            .scalars()
            .first()
        )
        if cuota is None or cuota.estado == "PAGADO":
            continue
        # ¿ya tiene un pago aplicado? (idempotencia)
        ya = db.execute(
            select(PagoCuota.id).where(PagoCuota.cuota_id == cuota.id)
        ).first()
        if ya is not None:
            continue
        pago = Pago(
            org_id=org_id,
            metodo="EFECTIVO",
            estado="CONFIRMADO",
            monto=cuota.monto,
            pagado_en=datetime.now(UTC),
        )
        db.add(pago)
        db.flush()
        db.add(
            PagoCuota(
                org_id=org_id,
                pago_id=pago.id,
                cuota_id=cuota.id,
                monto_aplicado=cuota.monto,
            )
        )
        cuota.estado = "PAGADO"
        pago.comprobante_url = f"/api/v1/cobranza/comprobantes/{pago.id}.pdf"
        pagadas += 1
    db.flush()
    return {"creadas": creadas, "vencidas": vencidas, "pagadas": pagadas}


def _seed_asistencia(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Crea 1 sesión de ejemplo con asistencias para que el historial tenga datos.

    Idempotente: toma la primera categoría (con alumnos) de la org, busca/crea la
    sesión por (categoria, fecha, hora=NULL) y hace upsert de una marca por
    alumno (PRESENTE, con un AUSENTE para variedad). `registrado_por` = ADMIN.
    """
    # Categoría con al menos un alumno (orden estable por nombre).
    cat_row = db.execute(
        select(Categoria, Alumno.id)
        .join(Alumno, Alumno.categoria_id == Categoria.id)
        .order_by(Categoria.nombre)
    ).first()
    if cat_row is None:
        return {"sesiones": 0, "marcas": 0}
    categoria = cat_row[0]

    alumnos = (
        db.execute(
            select(Alumno)
            .where(Alumno.categoria_id == categoria.id)
            .order_by(Alumno.ap_paterno, Alumno.nombres)
        )
        .scalars()
        .all()
    )
    if not alumnos:
        return {"sesiones": 0, "marcas": 0}

    fecha = date.today()
    admin = db.execute(select(Usuario).where(Usuario.email == ADMIN_EMAIL)).scalar_one_or_none()
    registrado_por = admin.id if admin else None

    # get-or-create sesión (idempotente por UNIQUE(categoria_id, fecha, hora)).
    sesion = db.execute(
        select(Sesion).where(
            Sesion.categoria_id == categoria.id,
            Sesion.fecha == fecha,
            Sesion.hora.is_(None),
        )
    ).scalar_one_or_none()
    sesiones_creadas = 0
    if sesion is None:
        sesion = Sesion(org_id=org_id, categoria_id=categoria.id, fecha=fecha, hora=None)
        db.add(sesion)
        db.flush()
        sesiones_creadas = 1

    existentes = {
        a.alumno_id
        for a in db.execute(
            select(Asistencia).where(Asistencia.sesion_id == sesion.id)
        )
        .scalars()
        .all()
    }
    marcas = 0
    for i, alumno in enumerate(alumnos):
        if alumno.id in existentes:
            continue
        estado = "AUSENTE" if i % 4 == 0 else "PRESENTE"  # mayoría presentes
        db.add(
            Asistencia(
                org_id=org_id,
                sesion_id=sesion.id,
                alumno_id=alumno.id,
                estado=estado,
                registrado_por=registrado_por,
            )
        )
        marcas += 1
    db.flush()
    return {"sesiones": sesiones_creadas, "marcas": marcas}


def _seed_egresos(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Crea 2-3 egresos de ejemplo (estilo Bolivia, montos en Bs) para el panel.

    Idempotente por clave natural (org + categoría + fecha + monto). `registrado_por`
    = ADMIN. Variedad: uno a nivel org (sin sucursal) y otros atados a Centro, para
    ejercitar el filtro por sucursal y el `sucursal: null`.
    """
    admin = db.execute(select(Usuario).where(Usuario.email == ADMIN_EMAIL)).scalar_one_or_none()
    registrado_por = admin.id if admin else None
    centro = db.execute(
        select(Sucursal).where(Sucursal.org_id == org_id, Sucursal.nombre == "Centro")
    ).scalar_one_or_none()
    centro_id = centro.id if centro else None

    fecha = date.today().replace(day=1)
    ejemplos = [
        ("Alquiler de cancha", Decimal("1500.00"), centro_id, "Cancha sintética (mes en curso)"),
        ("Material deportivo", Decimal("800.00"), centro_id, "Balones y conos"),
        ("Servicios (luz/agua)", Decimal("320.00"), None, "Servicios básicos - nivel organización"),
    ]
    creados = 0
    for categoria, monto, suc_id, descripcion in ejemplos:
        existente = db.execute(
            select(Egreso.id).where(
                Egreso.org_id == org_id,
                Egreso.categoria_gasto == categoria,
                Egreso.fecha == fecha,
                Egreso.monto == monto,
            )
        ).first()
        if existente is not None:
            continue
        db.add(
            Egreso(
                org_id=org_id,
                sucursal_id=suc_id,
                categoria_gasto=categoria,
                monto=monto,
                fecha=fecha,
                descripcion=descripcion,
                registrado_por=registrado_por,
            )
        )
        creados += 1
    db.flush()
    return {"egresos": creados}


def _seed_avisos(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Crea 1-2 avisos de ejemplo para el muro (uno ORG, uno SUCURSAL Centro).

    Idempotente por clave natural (org + titulo). `creado_por` = ADMIN. El de
    alcance ORG no caduca; el de SUCURSAL caduca en 30 días (vigencia de ejemplo).
    """
    admin = db.execute(select(Usuario).where(Usuario.email == ADMIN_EMAIL)).scalar_one_or_none()
    creado_por = admin.id if admin else None
    centro = db.execute(
        select(Sucursal).where(Sucursal.org_id == org_id, Sucursal.nombre == "Centro")
    ).scalar_one_or_none()

    # (titulo, cuerpo, alcance, sucursal_id, vigente_hasta)
    ejemplos: list[tuple[str, str, str, uuid.UUID | None, date | None]] = [
        (
            "Bienvenidos a la temporada",
            "¡Arrancamos una nueva temporada! Revisen sus horarios y mantengan al día "
            "sus cuotas. Cualquier cambio de clima o cancelación se publicará aquí.",
            "ORG",
            None,
            None,
        )
    ]
    if centro is not None:
        ejemplos.append(
            (
                "Mantenimiento de cancha - Centro",
                "La cancha de la sucursal Centro estará en mantenimiento este fin de "
                "semana. Los entrenamientos se reprograman; consulten con su entrenador.",
                "SUCURSAL",
                centro.id,
                date.today() + timedelta(days=30),
            )
        )

    creados = 0
    for titulo, cuerpo, alcance, sucursal_id, vigente_hasta in ejemplos:
        existente = db.execute(
            select(Aviso.id).where(Aviso.org_id == org_id, Aviso.titulo == titulo)
        ).first()
        if existente is not None:
            continue
        db.add(
            Aviso(
                org_id=org_id,
                titulo=titulo,
                cuerpo=cuerpo,
                alcance=alcance,
                sucursal_id=sucursal_id,
                categoria_id=None,
                vigente_hasta=vigente_hasta,
                creado_por=creado_por,
                activo=True,
            )
        )
        creados += 1
    db.flush()
    return {"avisos": creados}


def _seed_horarios(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Crea 1-2 horarios recurrentes de ejemplo (idempotente) para la rejilla.

    Ej.: Sub-10 Principiante (Centro) lunes 18:00–19:30 y miércoles 18:00–19:30,
    con el entrenador de ejemplo. Idempotente por la clave natural
    `(categoria_id, dia_semana, hora_inicio)` (espeja el UNIQUE de BD).
    """
    centro = db.execute(
        select(Sucursal).where(Sucursal.org_id == org_id, Sucursal.nombre == "Centro")
    ).scalar_one_or_none()
    if centro is None:
        return {"horarios": 0}

    categoria = db.execute(
        select(Categoria).where(
            Categoria.org_id == org_id,
            Categoria.sucursal_id == centro.id,
            Categoria.nombre == "Sub-10 Principiante",
        )
    ).scalar_one_or_none()
    if categoria is None:
        return {"horarios": 0}

    entrenador = db.execute(
        select(Entrenador).where(Entrenador.org_id == org_id)
    ).scalars().first()
    entrenador_id = entrenador.id if entrenador else None

    # (dia_semana 0=Lun … 6=Dom, hora_inicio, hora_fin)
    ejemplos: list[tuple[int, time, time]] = [
        (0, time(18, 0), time(19, 30)),  # Lunes 18:00–19:30
        (2, time(18, 0), time(19, 30)),  # Miércoles 18:00–19:30
    ]
    creados = 0
    for dia_semana, hora_inicio, hora_fin in ejemplos:
        existente = db.execute(
            select(HorarioClase.id).where(
                HorarioClase.categoria_id == categoria.id,
                HorarioClase.dia_semana == dia_semana,
                HorarioClase.hora_inicio == hora_inicio,
            )
        ).first()
        if existente is not None:
            continue
        db.add(
            HorarioClase(
                org_id=org_id,
                categoria_id=categoria.id,
                dia_semana=dia_semana,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                entrenador_id=entrenador_id,
                activo=True,
            )
        )
        creados += 1
    db.flush()
    return {"horarios": creados}


def _seed_solicitudes(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Crea 1 solicitud de auto-registro PENDIENTE de ejemplo (idempotente).

    `creado_por` = entrenador (capturó la solicitud desde el sistema). Sugerencia
    de sucursal Centro + su primera categoría. Idempotente por clave natural
    (org + CI del alumno propuesto). NO hay token/link público.
    """
    coach = db.execute(
        select(Usuario).where(Usuario.email == COACH_EMAIL)
    ).scalar_one_or_none()
    centro = db.execute(
        select(Sucursal).where(Sucursal.org_id == org_id, Sucursal.nombre == "Centro")
    ).scalar_one_or_none()
    if centro is None:
        return {"solicitudes": 0}
    categoria = db.execute(
        select(Categoria).where(
            Categoria.org_id == org_id, Categoria.sucursal_id == centro.id
        )
    ).scalars().first()

    ci_propuesto = "9200001 LP"
    existente = db.execute(
        select(SolicitudRegistro.id).where(
            SolicitudRegistro.org_id == org_id, SolicitudRegistro.ci == ci_propuesto
        )
    ).first()
    if existente is not None:
        return {"solicitudes": 0}

    db.add(
        SolicitudRegistro(
            org_id=org_id,
            estado="PENDIENTE",
            ap_paterno="Rojas",
            ap_materno="Mamani",
            nombres="Camila",
            ci=ci_propuesto,
            fecha_nac=date(2013, 6, 20),
            disciplina="Fútbol",
            contacto_emergencia="Madre · +591 70000001",
            ficha_medica={"tipo_sangre": "O+", "alergias": None, "condiciones": None},
            tutor_nombres="María Rojas",
            tutor_telefono="+591 70000001",
            tutor_ci="8200001 LP",
            parentesco="Madre",
            consent_version="v1",
            consent_canal="SISTEMA",
            consent_aceptado_en=datetime.now(UTC),
            sucursal_sugerida_id=centro.id,
            categoria_sugerida_id=categoria.id if categoria else None,
            creado_por=coach.id if coach else None,
        )
    )
    db.flush()
    return {"solicitudes": 1}


def seed() -> None:
    """Ejecuta el seed idempotente. Imprime un resumen."""
    db = SessionLocal()
    try:
        # 1) Organización (sin RLS).
        org = _get_or_create_org(db)
        org_id = org.id

        # 2) A partir de aquí, todo es tenant -> fijar contexto.
        _set_org_context(db, org_id)

        # 3) Usuarios (ADMIN + ENTRENADOR) y entrenador.
        _get_or_create_usuario(
            db, org_id, email=ADMIN_EMAIL, password=ADMIN_PASS, role="ADMIN",
            nombre="Admin CanteraSport",
        )
        coach_user = _get_or_create_usuario(
            db, org_id, email=COACH_EMAIL, password=COACH_PASS, role="ENTRENADOR",
            nombre="Carlos Coach",
        )
        existing_coach = db.execute(
            select(Entrenador).where(Entrenador.usuario_id == coach_user.id)
        ).scalar_one_or_none()
        if existing_coach is None:
            db.add(
                Entrenador(
                    org_id=org_id,
                    usuario_id=coach_user.id,
                    nombres="Carlos Coach",
                    especialidad="Fútbol",
                )
            )
            db.flush()

        # 4) Sucursales.
        centro = _get_or_create_sucursal(
            db, org_id, nombre="Centro", direccion="Av. Heroínas 123, Cochabamba"
        )
        cala_cala = _get_or_create_sucursal(
            db, org_id, nombre="Cala Cala", direccion="Av. América 456, Cochabamba"
        )

        # 5) Categorías (en ambas sucursales para variedad).
        cats = {}
        for suc in (centro, cala_cala):
            cats[(suc.id, "Sub-10 Principiante")] = _get_or_create_categoria(
                db, org_id, sucursal_id=suc.id, nombre="Sub-10 Principiante",
                nivel="PRINCIPIANTE", rango_edad="Sub-10",
            )
            cats[(suc.id, "Sub-14 Intermedio")] = _get_or_create_categoria(
                db, org_id, sucursal_id=suc.id, nombre="Sub-14 Intermedio",
                nivel="INTERMEDIO", rango_edad="Sub-14",
            )
            cats[(suc.id, "Sub-17 Avanzado")] = _get_or_create_categoria(
                db, org_id, sucursal_id=suc.id, nombre="Sub-17 Avanzado",
                nivel="AVANZADO", rango_edad="Sub-17",
            )

        # 6) Alumnos + tutores + consentimiento + inscripción + ficha médica.
        sucursales = [centro, cala_cala]
        cat_nombres = ["Sub-10 Principiante", "Sub-14 Intermedio", "Sub-17 Avanzado"]
        created = 0
        for i, (ap_pat, ap_mat, nom, ci, fnac, disc, sangre, alergias, cond) in enumerate(
            _ALUMNOS
        ):
            existing = db.execute(
                select(Alumno).where(Alumno.org_id == org_id, Alumno.ci == ci)
            ).scalar_one_or_none()
            if existing is not None:
                continue

            suc = sucursales[i % 2]
            cat = cats[(suc.id, cat_nombres[i % 3])]
            alumno = Alumno(
                org_id=org_id,
                sucursal_id=suc.id,
                categoria_id=cat.id,
                ap_paterno=ap_pat,
                ap_materno=ap_mat,
                nombres=nom,
                ci=ci,
                fecha_nac=fnac,
                disciplina=disc,
                contacto_emergencia=f"Tutor de {nom} · +591 7{i}123456",
                ficha_medica={
                    "tipo_sangre": sangre,
                    "alergias": alergias,
                    "condiciones": cond,
                },
            )
            db.add(alumno)
            db.flush()

            tutor = Tutor(
                org_id=org_id,
                nombres=f"Tutor {ap_pat}",
                telefono=f"+591 7{i}123456",
                ci=f"812345{i} LP",
            )
            db.add(tutor)
            db.flush()
            db.add(
                AlumnoTutor(
                    org_id=org_id,
                    alumno_id=alumno.id,
                    tutor_id=tutor.id,
                    parentesco="Padre/Madre",
                    responsable_pago=True,
                )
            )
            db.add(
                Consentimiento(
                    org_id=org_id,
                    tutor_id=tutor.id,
                    alumno_id=alumno.id,
                    version_terminos="v1",
                    canal="PRESENCIAL",
                    aceptado_en=datetime.now(UTC),
                )
            )
            db.add(
                Inscripcion(
                    org_id=org_id,
                    alumno_id=alumno.id,
                    disciplina=disc,
                    fecha_inscripcion=date(2024, 2, 10),
                    monto_mensual=Decimal("250.00"),
                    modo_cobro=None,
                    dia_corte=None,
                    estado="ACTIVA",
                )
            )
            created += 1

        # 7) Cobranza: cuotas + estados variados para el Panel.
        db.flush()
        cob = _seed_cobranza(db, org_id)

        # 8) Asistencia: 1 sesión de ejemplo con marcas (historial con datos).
        asis = _seed_asistencia(db, org_id)

        # 9) Egresos: 2-3 gastos de ejemplo (panel financiero con salidas).
        egr = _seed_egresos(db, org_id)

        # 10) Avisos: 1-2 avisos de ejemplo para el muro (ORG + SUCURSAL).
        avs = _seed_avisos(db, org_id)

        # 11) Horarios: 1-2 horarios recurrentes de ejemplo (rejilla semanal).
        hor = _seed_horarios(db, org_id)

        # 12) Solicitudes: 1 solicitud de auto-registro PENDIENTE (capturada por coach).
        sol = _seed_solicitudes(db, org_id)

        db.commit()
        print(
            f"Seed OK: org='{ORG_NOMBRE}' ({org_id}), admin={ADMIN_EMAIL}/{ADMIN_PASS}, "
            f"entrenador={COACH_EMAIL}/{COACH_PASS}, sucursales=2, "
            f"alumnos nuevos={created} (de {len(_ALUMNOS)}). "
            f"Cobranza: cuotas_creadas={cob['creadas']}, vencidas={cob['vencidas']}, "
            f"pagadas={cob['pagadas']}. "
            f"Asistencia: sesiones_creadas={asis['sesiones']}, marcas={asis['marcas']}. "
            f"Egresos: creados={egr['egresos']}. "
            f"Avisos: creados={avs['avisos']}. "
            f"Horarios: creados={hor['horarios']}. "
            f"Solicitudes: creadas={sol['solicitudes']}."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
