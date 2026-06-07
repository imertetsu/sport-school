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

from sqlalchemy.orm import Session

from app.models.consentimiento import Consentimiento
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.tutor import Tutor
from app.schemas.deportista import DeportistaCreate


def crear_deportista(db: Session, body: DeportistaCreate, *, org_id: uuid.UUID) -> Deportista:
    """Crea deportista + tutores + puente + consentimiento (+inscripción) (C5).

    La validación dura (≥1 tutor + consentimiento) la garantiza `DeportistaCreate`
    (Pydantic => 422 antes de llegar aquí). Devuelve el `Deportista` creado (ya con
    `id` tras el `flush`). El llamador es responsable de commitear la transacción.
    """
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
        contacto_emergencia=body.contacto_emergencia,
        ficha_medica=(body.ficha_medica.model_dump() if body.ficha_medica else None),
    )
    db.add(deportista)
    db.flush()  # obtener deportista.id

    # Tutores + puente. Consentimiento se ata al primer tutor (responsable).
    primer_tutor_id: uuid.UUID | None = None
    for t in body.tutores:
        tutor = Tutor(org_id=org_id, nombres=t.nombres, telefono=t.telefono, ci=t.ci)
        db.add(tutor)
        db.flush()
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
