"""Servicio de Deportistas (C5) — crea deportista+tutores+puente+consentimiento[+inscripción].

Factorizado del router `app/api/v1/deportistas.py` para poder **reutilizar** la creación
del deportista desde otros flujos (p. ej. aprobar una `solicitud_registro` del epic de
auto-registro) sin duplicar la lógica ni romper la validación dura (≥1 tutor +
consentimiento obligatorio, RNF-02).

Corre SIEMPRE con `app.current_org` ya fijado por el llamador (RLS es la barrera
real, no `WHERE org_id`). No se salta el contexto de tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.consentimiento import Consentimiento
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.disciplina import Disciplina
from app.models.inscripcion import Inscripcion
from app.models.tutor import Tutor
from app.schemas.deportista import (
    DeportistaCreate,
    DeportistaUpdate,
    InscripcionIn,
    TutorIn,
    TutorUpsert,
)
from app.services import generacion


# --------------------------------------------------------------------------- #
# Errores de negocio (el router los traduce a HTTP)
# --------------------------------------------------------------------------- #
class DeportistaError(Exception):
    """Error base de negocio del módulo de Deportistas."""


class CIDuplicado(DeportistaError):
    """Ya existe un deportista con ese CI en la org (índice único parcial) -> 409."""


class DisciplinaInvalida(DeportistaError):
    """`disciplina_id` no existe en el catálogo global o está inactiva -> 422.

    Evita un FK colgante (la FK `deportista.disciplina_id` lo impediría con un
    `IntegrityError` -> 500); el pre-chequeo lo traduce a 422 con mensaje claro.
    """


# CI "placeholder" para deportistas que aún no presentan su documento: se teclea "0"
# y significa "lo presentará luego". NO identifica a un deportista → puede repetirse
# (el índice único parcial lo excluye, migración 0024) y NUNCA se recupera-por-CI.
CI_PENDIENTE = "0"


class TutorInvarianteViolado(DeportistaError):
    """La reconciliación de tutores rompería el invariante de menores -> 422.

    Se lanza cuando la lista resultante quedaría **vacía** (un deportista menor
    SIEMPRE necesita ≥1 tutor, RNF-02) o cuando se intenta **desvincular al tutor
    atado al `Consentimiento`** existente (rompería la atadura del consentimiento,
    requisito duro para persistir un deportista). Validado SERVER-SIDE (no se
    confía en la UI). El router lo traduce a 422 con mensaje claro de negocio.
    """


# --------------------------------------------------------------------------- #
# Validación de `disciplina_id` contra el catálogo GLOBAL (mismo patrón que
# `services/disciplina.get_disciplina_activa_o_error`, que usa categoría en S2).
# `disciplina` es una tabla GLOBAL sin RLS: se consulta directo por id (sin GUC).
# Aquí lanzamos un error de NEGOCIO (no HTTPException) para no acoplar el servicio
# a FastAPI; el router lo traduce a 422.
# --------------------------------------------------------------------------- #
def _validar_disciplina_id(db: Session, disciplina_id: uuid.UUID) -> None:
    """Exige que `disciplina_id` exista en el catálogo y esté activa. Si no, 422.

    Inexistente o inactiva ⇒ `DisciplinaInvalida` (-> 422; nunca 500 por FK colgante).
    La FK es el backstop ante carreras (borrado concurrente de la disciplina).
    """
    disc = db.execute(
        select(Disciplina.activo).where(Disciplina.id == disciplina_id)
    ).scalar_one_or_none()
    if disc is None:
        raise DisciplinaInvalida("La disciplina indicada no existe en el catálogo")
    if not disc:
        raise DisciplinaInvalida("La disciplina indicada está inactiva")


# --------------------------------------------------------------------------- #
# Lookup por CI (recuperar-por-CI; corre bajo `app.current_org` ya fijado, RLS)
# --------------------------------------------------------------------------- #
def buscar_deportista_por_ci(db: Session, ci: str) -> Deportista | None:
    """Devuelve el deportista de la org del contexto con ese CI, o None.

    Scoped por org vía RLS (no se filtra por `org_id` en Python; la barrera real es
    RLS). El índice único parcial `(org_id, ci) WHERE ci IS NOT NULL AND ci <> '0'`
    garantiza a lo sumo una fila por CI no-placeholder dentro de la org.

    `"0"` es el CI placeholder ("presentará luego"): puede repetirse, así que NO
    identifica a un deportista → se devuelve `None` (no se recupera-por-CI y se evita
    `MultipleResultsFound` si hubiera varios "0").
    """
    if not ci or ci.strip() == CI_PENDIENTE:
        return None
    return db.execute(select(Deportista).where(Deportista.ci == ci)).scalar_one_or_none()


def buscar_tutor_por_ci(db: Session, ci: str) -> Tutor | None:
    """Devuelve el tutor de la org del contexto con ese CI, o None (scoped por RLS)."""
    return db.execute(select(Tutor).where(Tutor.ci == ci)).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Reutilizar/crear tutor (recuperar-por-CI + actualizar teléfono, contrato #4)
# --------------------------------------------------------------------------- #
def _resolver_tutor(db: Session, t: TutorIn, *, org_id: uuid.UUID) -> Tutor:
    """Reutiliza un tutor existente por CI (en la org) o crea uno nuevo.

    Contrato #4: si el `ci` del tutor coincide con uno existente de la org, se
    **reusa** ese tutor (sin duplicar) y se **actualiza su teléfono** con el valor
    entrante (solo si viene). El CI del tutor es OPCIONAL: si no viene CI, siempre se
    crea un tutor nuevo (múltiples `ci IS NULL` permitidos por el índice parcial).
    """
    if t.ci:
        existente = buscar_tutor_por_ci(db, t.ci)
        if existente is not None:
            if t.telefono:
                existente.telefono = t.telefono
            db.flush()
            return existente

    tutor = Tutor(org_id=org_id, nombres=t.nombres, telefono=t.telefono, ci=t.ci)
    db.add(tutor)
    db.flush()
    return tutor


def crear_deportista(db: Session, body: DeportistaCreate, *, org_id: uuid.UUID) -> Deportista:
    """Crea deportista + tutores + puente + consentimiento (+inscripción) (C5).

    La validación dura (≥1 tutor + consentimiento) la garantiza `DeportistaCreate`
    (Pydantic => 422 antes de llegar aquí). Devuelve el `Deportista` creado (ya con
    `id` tras el `flush`). El llamador es responsable de commitear la transacción.

    Dedup por CI (contrato S3): si `ci` ya existe en la org, el índice único parcial
    lanza `IntegrityError`; lo traducimos a `CIDuplicado` (-> 409, RNF-06: no se
    descarta el dato silenciosamente). Pre-chequeo proactivo dentro de la org para un
    mejor mensaje; el `IntegrityError` es el backstop (carrera).
    """
    if body.ci and buscar_deportista_por_ci(db, body.ci) is not None:
        raise CIDuplicado("Ya existe un deportista con ese CI en esta organización")

    # FK canónica al catálogo (S3): valida ANTES del INSERT para traducir un
    # `disciplina_id` inválido a 422 (no a un IntegrityError genérico de la FK -> 500,
    # ni confundible con la violación del índice único de CI del mismo flush).
    if body.disciplina_id is not None:
        _validar_disciplina_id(db, body.disciplina_id)

    deportista = Deportista(
        org_id=org_id,
        sucursal_id=body.sucursal_id,
        categoria_id=body.categoria_id,
        ap_paterno=body.ap_paterno,
        ap_materno=body.ap_materno,
        nombres=body.nombres,
        ci=body.ci,
        fecha_nac=body.fecha_nac,
        disciplina=body.disciplina,
        disciplina_id=body.disciplina_id,
        contacto_emergencia=body.contacto_emergencia,
        domicilio=body.domicilio,
        lugar_nacimiento=body.lugar_nacimiento,
        ficha_medica=(body.ficha_medica.model_dump() if body.ficha_medica else None),
    )
    db.add(deportista)
    try:
        db.flush()  # fuerza el INSERT para detectar la violación del índice único parcial
    except IntegrityError as exc:
        db.rollback()
        raise CIDuplicado("Ya existe un deportista con ese CI en esta organización") from exc

    # Tutores + puente. Consentimiento se ata al primer tutor (responsable).
    # Recuperar-por-CI: un tutor con CI ya existente se REUSA (no se duplica) y se le
    # actualiza el teléfono entrante (contrato #4).
    primer_tutor_id: uuid.UUID | None = None
    for t in body.tutores:
        tutor = _resolver_tutor(db, t, org_id=org_id)
        if primer_tutor_id is None:
            primer_tutor_id = tutor.id
        db.add(
            DeportistaTutor(
                org_id=org_id,
                deportista_id=deportista.id,
                tutor_id=tutor.id,
                parentesco=t.parentesco,
                responsable_pago=t.responsable_pago,
            )
        )

    assert primer_tutor_id is not None  # garantizado por min_length=1
    db.add(
        Consentimiento(
            org_id=org_id,
            tutor_id=primer_tutor_id,
            deportista_id=deportista.id,
            version_terminos=body.consentimiento.version_terminos,
            canal=body.consentimiento.canal,
            aceptado_en=datetime.now(UTC),
        )
    )

    if body.inscripcion is not None:
        ins = body.inscripcion
        db.add(
            Inscripcion(
                org_id=org_id,
                deportista_id=deportista.id,
                disciplina=ins.disciplina,
                fecha_inscripcion=ins.fecha_inscripcion,
                monto_mensual=ins.monto_mensual,
                modo_cobro=ins.modo_cobro,
                dia_corte=ins.dia_corte,
                estado=ins.estado,
            )
        )

    db.flush()
    return deportista


def _reconciliar_tutores(
    db: Session,
    deportista: Deportista,
    entrantes: list[TutorUpsert],
    *,
    org_id: uuid.UUID,
) -> None:
    """Reconcilia los tutores del deportista contra la lista entrante (C3, Fase 3).

    Semántica de la lista reconciliable por id:
      - Tutor con `id` que YA está vinculado -> se actualiza el tutor (nombres,
        teléfono, ci) y su vínculo `deportista_tutor` (parentesco, responsable_pago).
      - Tutor SIN `id` -> `_resolver_tutor` (recuperar-por-CI: si existe un tutor con
        ese CI en la org se reusa, si no se crea) y se vincula.
      - Vínculo previo cuyo tutor NO aparece en la lista entrante -> se **desvincula**
        (se borra SOLO el `deportista_tutor`; el registro `tutor` se conserva por si
        está compartido con otro deportista).

    Invariante de menores (SERVER-SIDE, RNF-02; no se confía en la UI):
      - La lista resultante no puede quedar vacía (≥1 tutor) -> `TutorInvarianteViolado`.
      - No se puede desvincular al tutor atado al `Consentimiento` existente (rompería
        la atadura) -> `TutorInvarianteViolado`.

    Atómico: valida ANTES de aplicar cambios; si el invariante falla no se persiste
    nada (el llamador no commitea hasta que esto retorna sin excepción).
    """
    # 1) Invariante: la lista resultante no puede quedar vacía.
    if not entrantes:
        raise TutorInvarianteViolado(
            "Un deportista debe tener al menos un tutor; no se pueden quitar todos"
        )

    # 2) Vínculos actuales (puente) indexados por tutor_id.
    vinculos_actuales = {
        link.tutor_id: link
        for link in db.execute(
            select(DeportistaTutor).where(DeportistaTutor.deportista_id == deportista.id)
        )
        .scalars()
        .all()
    }

    # 3) Tutor atado al Consentimiento existente (no se puede desvincular).
    tutor_consentimiento_id = db.execute(
        select(Consentimiento.tutor_id)
        .where(Consentimiento.deportista_id == deportista.id)
        .order_by(Consentimiento.aceptado_en.desc())
    ).scalar()

    # 4) Validar referencias por id: cada `id` entrante debe ser un vínculo actual de
    #    ESTE deportista (no aceptar editar un tutor no vinculado vía un id arbitrario).
    for t in entrantes:
        if t.id is not None and t.id not in vinculos_actuales:
            raise TutorInvarianteViolado(
                "Uno de los tutores indicados por id no está vinculado a este deportista"
            )

    # 5) Determinar qué vínculos quedarían tras la reconciliación. Solo los tutores
    #    con `id` presente en la lista entrante se conservan; los sin `id` se resuelven
    #    (alta/recupera). Calcular qué se desvincula ANTES de mutar para validar el
    #    invariante del consentimiento sin tocar la BD a medias.
    ids_entrantes_existentes = {t.id for t in entrantes if t.id is not None}
    a_desvincular = set(vinculos_actuales) - ids_entrantes_existentes

    if tutor_consentimiento_id is not None and tutor_consentimiento_id in a_desvincular:
        raise TutorInvarianteViolado(
            "No se puede quitar al tutor que firmó el consentimiento del deportista"
        )

    # --- A partir de aquí, el invariante está garantizado: aplicar los cambios. ---

    # 6) Altas / ediciones.
    for t in entrantes:
        if t.id is not None:
            # Editar tutor existente + su vínculo.
            link = vinculos_actuales[t.id]
            tutor = db.execute(select(Tutor).where(Tutor.id == t.id)).scalar_one()
            tutor.nombres = t.nombres
            tutor.telefono = t.telefono
            tutor.ci = t.ci
            link.parentesco = t.parentesco
            link.responsable_pago = t.responsable_pago
        else:
            # Alta / recuperar-por-CI + vincular (si aún no estuviera vinculado).
            tutor = _resolver_tutor(
                db,
                TutorIn(
                    nombres=t.nombres,
                    telefono=t.telefono,
                    ci=t.ci,
                    parentesco=t.parentesco,
                    responsable_pago=t.responsable_pago,
                ),
                org_id=org_id,
            )
            existente = vinculos_actuales.get(tutor.id)
            if existente is not None:
                # El tutor recuperado-por-CI ya estaba vinculado: actualizar el vínculo
                # y NO marcarlo para desvincular.
                existente.parentesco = t.parentesco
                existente.responsable_pago = t.responsable_pago
                a_desvincular.discard(tutor.id)
            else:
                db.add(
                    DeportistaTutor(
                        org_id=org_id,
                        deportista_id=deportista.id,
                        tutor_id=tutor.id,
                        parentesco=t.parentesco,
                        responsable_pago=t.responsable_pago,
                    )
                )

    # 7) Desvincular los que ya no aparecen (borra SOLO el puente, no el tutor).
    for tutor_id in a_desvincular:
        db.delete(vinculos_actuales[tutor_id])

    db.flush()


def _upsert_inscripcion(
    db: Session, deportista: Deportista, ins: InscripcionIn, *, org_id: uuid.UUID
) -> None:
    """Crea o actualiza la inscripción (cobro) del deportista y sincroniza sus cuotas.

    Sin inscripción previa -> la crea. Con una existente -> actualiza los campos
    obligatorios (monto, fecha, estado) y los opcionales SOLO si vienen no nulos
    (preserva `modo_cobro`/`dia_corte`/`disciplina` cuando el formulario simple no los
    envía).

    Cuotas (alta retroactiva + cambio de cuota "hacia adelante"): tras persistir la
    inscripción se **rellenan las cuotas** desde `fecha_inscripcion` hasta el período
    corriente (`generar_cuotas_historicas`, idempotente) — así un alumno inscrito en el
    pasado tiene sus cuotas mes a mes y se pueden cobrar. Además, las cuotas futuras sin
    pago se **reajustan** al monto vigente (`reajustar_monto_cuotas_futuras`, no-op salvo
    las que difieran); las pagadas/parciales y los períodos ya vencidos conservan su
    monto. Esto corre en la edición (ADMIN); el alta por `POST /deportistas` sigue
    delegando la generación al motor/cron.
    """
    existente = (
        db.execute(select(Inscripcion).where(Inscripcion.deportista_id == deportista.id))
        .scalars()
        .first()
    )
    if existente is None:
        nueva = Inscripcion(
            org_id=org_id,
            deportista_id=deportista.id,
            disciplina=ins.disciplina,
            fecha_inscripcion=ins.fecha_inscripcion,
            monto_mensual=ins.monto_mensual,
            modo_cobro=ins.modo_cobro,
            dia_corte=ins.dia_corte,
            estado=ins.estado,
        )
        db.add(nueva)
        db.flush()  # necesita id + estar persistida para generar cuotas
        generacion.generar_cuotas_historicas(db, inscripcion_id=nueva.id)
        return

    existente.fecha_inscripcion = ins.fecha_inscripcion
    existente.monto_mensual = ins.monto_mensual
    existente.estado = ins.estado
    if ins.disciplina is not None:
        existente.disciplina = ins.disciplina
    if ins.modo_cobro is not None:
        existente.modo_cobro = ins.modo_cobro
    if ins.dia_corte is not None:
        existente.dia_corte = ins.dia_corte
    db.flush()

    # Las cuotas futuras SIN pago siguen la cuota mensual vigente (el cambio de cuota
    # aplica "hacia adelante"). Es un no-op salvo para las que difieran del monto
    # actual; NO toca pagadas/parciales ni períodos ya vencidos.
    generacion.reajustar_monto_cuotas_futuras(
        db, inscripcion_id=existente.id, nuevo_monto=existente.monto_mensual
    )
    # Alta retroactiva: rellena las cuotas desde la fecha de inscripción (idempotente).
    generacion.generar_cuotas_historicas(db, inscripcion_id=existente.id)


def actualizar_deportista(
    db: Session, deportista: Deportista, body: DeportistaUpdate, *, org_id: uuid.UUID
) -> Deportista:
    """Actualiza los campos enviados del deportista, incluyendo tutores (C5 + C3).

    Solo aplica los campos presentes (`exclude_unset`). Si llega `disciplina_id` no nulo,
    se valida contra el catálogo global ANTES del flush (-> 422 si no existe/inactiva,
    evitando un FK colgante / 500). El `ci` no se valida aquí (el slice de edición no
    cambia el dedup; el índice único es el backstop si llegara a tocarse).

    `tutores` (C3, Fase 3): si NO viene en el body (`None`), NO se tocan los tutores
    (preserva el comportamiento previo). Si viene la lista, se **reconcilia** (alta /
    edición por id / desvinculación de los ausentes; recupera-por-CI) respetando el
    invariante de menores (≥1 tutor, no quitar el del consentimiento -> 422 vía
    `TutorInvarianteViolado`). Todo en la misma transacción: si el invariante falla, no
    se persiste nada.

    `deportista` debe estar ya cargado bajo el contexto de tenant (RLS). El llamador
    commitea la transacción.
    """
    data = body.model_dump(exclude_unset=True)

    if data.get("disciplina_id") is not None:
        _validar_disciplina_id(db, data["disciplina_id"])

    # Reconciliar tutores solo si la clave vino en el body (None vs ausente). El
    # invariante se valida ANTES de mutar el deportista para no persistir a medias.
    # Se usan los objetos Pydantic de `body.tutores` (model_dump los aplanaría a dict);
    # `data` los descarta para que el bucle de setattr no los toque.
    reconciliar = "tutores" in data
    data.pop("tutores", None)
    if reconciliar:
        assert body.tutores is not None
        _reconciliar_tutores(db, deportista, body.tutores, org_id=org_id)

    # Inscripción (cobro): UPSERT solo si vino en el body. Se descarta de `data` para
    # que el bucle de setattr no la trate como columna del deportista.
    inscribir = "inscripcion" in data
    data.pop("inscripcion", None)
    if inscribir and body.inscripcion is not None:
        _upsert_inscripcion(db, deportista, body.inscripcion, org_id=org_id)

    if "ficha_medica" in data:
        deportista.ficha_medica = data.pop("ficha_medica")  # dict (model_dump) o None
    for field_name, value in data.items():
        setattr(deportista, field_name, value)

    db.flush()
    return deportista
