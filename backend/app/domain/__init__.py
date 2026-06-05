"""Núcleo de dominio.

NO importa adaptadores concretos, `app.api`, FastAPI ni SQLAlchemy. El contrato
lo verifica import-linter (`lint-imports`). Aquí viven los **puertos** (Protocols)
que los adaptadores en `app.adapters` implementan.
"""
