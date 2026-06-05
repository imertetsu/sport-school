"""Router agregado de la API v1. Se monta en `/api/v1` desde `app.main`."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import alumnos, auth, categorias, sucursales

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(sucursales.router)
api_router.include_router(categorias.router)
api_router.include_router(alumnos.router)
