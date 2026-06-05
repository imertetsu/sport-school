"""Engine, sessionmaker y dependencia de sesión (contrato C3).

SQLAlchemy 2.0 **sync** + psycopg v3. `get_db` abre una transacción por request;
la fijación del contexto de tenant (`SET LOCAL app.current_org`) ocurre en
`app.core.tenant` dentro de **esta misma** transacción (fail-closed).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# pool_pre_ping evita conexiones muertas; future=True -> API 2.0.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión/transacción por request.

    Commit al terminar sin error, rollback ante excepción, y cierre siempre.
    El contexto de tenant se setea *después* de autenticar mediante la
    dependencia `set_tenant_context` (misma transacción), de modo que cualquier
    query corre con `app.current_org` ya fijado o, si no, RLS devuelve 0 filas.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
