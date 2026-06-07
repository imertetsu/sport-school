"""Router agregado de la API v1. Se monta en `/api/v1` desde `app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    asistencia,
    auth,
    avisos,
    catalogo,
    categorias,
    cobranza,
    deportistas,
    egresos,
    entrenadores,
    horarios,
    plataforma,
    recibos,
    reportes,
    solicitudes,
    sucursales,
    tutores,
)
from app.api.v1.webhooks import openbcb as openbcb_webhook
from app.api.v1.webhooks import whatsapp as whatsapp_webhook

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(sucursales.router)
api_router.include_router(catalogo.router)
api_router.include_router(categorias.router)
api_router.include_router(deportistas.router)
api_router.include_router(tutores.router)
api_router.include_router(cobranza.router)
api_router.include_router(asistencia.router)
api_router.include_router(egresos.router)
api_router.include_router(reportes.router)
api_router.include_router(avisos.router)
api_router.include_router(entrenadores.router)
api_router.include_router(horarios.router)
api_router.include_router(recibos.router)
api_router.include_router(solicitudes.router)
api_router.include_router(plataforma.router)
api_router.include_router(openbcb_webhook.router)
api_router.include_router(whatsapp_webhook.router)
