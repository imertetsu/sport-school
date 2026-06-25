"""Router del QR de cobro estático por escuela (C6, epic pagos-qr-comprobante).

El ADMIN sube **su** QR (imagen del banco/billetera) en Ajustes; el sistema lo
**reenvía tal cual** (no se decodifica) como adjunto del recordatorio de cobro. 1 fila
por org (UNIQUE org_id) → subir cuando ya hay uno **reemplaza**.

Endpoints ADMIN (Bearer + contexto de tenant, RLS):
  - `POST   /qr-cobro`        (multipart `file`) → `QrCobroMetaOut` (sube/reemplaza)
  - `GET    /qr-cobro/meta`   → `QrCobroMetaOut` (con `imagen_url` firmada si hay QR)
  - `DELETE /qr-cobro`        → `QrCobroMetaOut {tiene_qr:false}`

Endpoints binarios (SIN Bearer, URL firmada HMAC stateless — el `<img>` del navegador
NO manda `Authorization`; mismo mecanismo que el recibo PDF):
  - `GET /qr-cobro` y `GET /qr-cobro/imagen` → imagen del QR del usuario (ADMIN, Bearer)
  - `GET /qr-cobro/{org_id}/{token}.img`     → imagen del QR (token firmado, sin Bearer)

`GET /qr-cobro/meta` devuelve `imagen_url` = la URL FIRMADA del binario, que el front
incrusta en un `<img src>`. El endpoint `.img` valida el token (no el Bearer).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.tenant import CurrentUser, require_role
from app.models.qr_cobro import QrCobro
from app.schemas.qr_cobro import QrCobroMetaOut
from app.services import imagen_token

router = APIRouter(prefix="/qr-cobro", tags=["qr-cobro"])

# Tamaño máximo del QR subido (4 MB, alineado con el límite del body del sidecar).
_MAX_BYTES = 4 * 1024 * 1024
_MIMES_OK = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

_NO_ENCONTRADO = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="QR de cobro no encontrado"
)


def _meta_out(org_id: uuid.UUID, qr: QrCobro | None) -> QrCobroMetaOut:
    """`QrCobroMetaOut` con `imagen_url` firmada cuando hay QR."""
    if qr is None:
        return QrCobroMetaOut(tiene_qr=False)
    return QrCobroMetaOut(
        tiene_qr=True,
        mime=qr.mime,
        tamano_bytes=qr.tamano_bytes,
        imagen_url=imagen_token.url_qr(org_id),
    )


def _qr_de_org(db: Session, org_id: uuid.UUID) -> QrCobro | None:
    return db.execute(select(QrCobro).where(QrCobro.org_id == org_id)).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# POST /qr-cobro  (multipart)  — sube/reemplaza
# --------------------------------------------------------------------------- #
@router.post("", response_model=QrCobroMetaOut)
async def subir_qr(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> QrCobroMetaOut:
    """Sube (o reemplaza) el QR de cobro de la escuela. Valida tipo y tamaño."""
    if file.content_type not in _MIMES_OK:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tipo no permitido ({file.content_type}); use PNG/JPEG/WEBP",
        )
    contenido = await file.read()
    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Archivo vacío"
        )
    if len(contenido) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen excede 4 MB",
        )

    org_id = uuid.UUID(user.org_id)
    mime = "image/jpeg" if file.content_type == "image/jpg" else file.content_type
    qr = _qr_de_org(db, org_id)
    if qr is None:
        qr = QrCobro(org_id=org_id, imagen=contenido, mime=mime, tamano_bytes=len(contenido))
        db.add(qr)
    else:
        qr.imagen = contenido
        qr.mime = mime
        qr.tamano_bytes = len(contenido)
    db.flush()
    return _meta_out(org_id, qr)


# --------------------------------------------------------------------------- #
# GET /qr-cobro/meta
# --------------------------------------------------------------------------- #
@router.get("/meta", response_model=QrCobroMetaOut)
def meta_qr(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> QrCobroMetaOut:
    """Metadata del QR (existe? mime/tamaño) + `imagen_url` firmada si hay."""
    org_id = uuid.UUID(user.org_id)
    return _meta_out(org_id, _qr_de_org(db, org_id))


# --------------------------------------------------------------------------- #
# DELETE /qr-cobro
# --------------------------------------------------------------------------- #
@router.delete("", response_model=QrCobroMetaOut)
def borrar_qr(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> QrCobroMetaOut:
    """Borra el QR de cobro de la escuela (idempotente: sin QR ⇒ `tiene_qr:false`)."""
    org_id = uuid.UUID(user.org_id)
    qr = _qr_de_org(db, org_id)
    if qr is not None:
        db.delete(qr)
        db.flush()
    return QrCobroMetaOut(tiene_qr=False)


# --------------------------------------------------------------------------- #
# GET /qr-cobro  y  /qr-cobro/imagen  (binario, ADMIN con Bearer)
# --------------------------------------------------------------------------- #
@router.get("", response_class=Response)
@router.get("/imagen", response_class=Response)
def imagen_qr_admin(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Devuelve la imagen del QR del usuario (ADMIN). 404 si no tiene QR.

    Útil para descargas autenticadas; para incrustar en un `<img>` el front usa la URL
    firmada de `imagen_url` (que pega al endpoint `.img` sin Bearer).
    """
    qr = _qr_de_org(db, uuid.UUID(user.org_id))
    if qr is None:
        raise _NO_ENCONTRADO
    return Response(content=qr.imagen, media_type=qr.mime)


# --------------------------------------------------------------------------- #
# GET /qr-cobro/{org_id}/{token}.img  (binario, SIN Bearer, token firmado)
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/{token}.img", response_class=Response)
def imagen_qr_publica(org_id: uuid.UUID, token: str) -> Response:
    """Imagen del QR por URL firmada (sin Bearer). La consume el `<img>` del navegador.

    Valida el token HMAC ANTES de tocar la BD; fija `app.current_org` y lee bajo RLS
    (no salta el aislamiento). 404 indistinguible si el token no valida o no hay QR.
    """
    if not imagen_token.token_valido(imagen_token.KIND_QR, org_id, org_id, token):
        raise _NO_ENCONTRADO

    db: Session = SessionLocal()
    try:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_id)})
        qr = _qr_de_org(db, org_id)
        if qr is None:
            raise _NO_ENCONTRADO
        imagen, mime = qr.imagen, qr.mime
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return Response(content=imagen, media_type=mime)
