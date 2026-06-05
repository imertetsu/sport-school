"""Servicios de aplicación (con I/O).

A diferencia de `app.domain` (puro, sin SQLAlchemy/FastAPI), aquí vive la lógica
que orquesta el dominio con la BD y los adaptadores: generación de cuotas,
pagos/conciliación y comprobantes. Los routers (`app.api`) delegan aquí.
"""
