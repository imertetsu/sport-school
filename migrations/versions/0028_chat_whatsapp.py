"""chat_whatsapp: bandeja de conversaciones (`conversacion_whatsapp` +
`mensaje_whatsapp`) con org_id NULLABLE, RLS de doble via y resolver de escuela por
telefono de tutor

Migracion del epic `chat-whatsapp`. Materializa los modelos `ConversacionWhatsApp`
(`backend/app/models/conversacion_whatsapp.py`) y `MensajeWhatsApp`
(`backend/app/models/mensaje_whatsapp.py`). Escrita A MANO (no autogenerada): RLS,
GRANTs y funciones SECURITY DEFINER no los detecta `--autogenerate`, y los CHECK
enum-like el modelo los delega EXPRESAMENTE a la migracion (patron del repo).

`down_revision = "0027"` (head actual).

## Por que `org_id` es NULLABLE aqui (unica excepcion del esquema)

Todas las demas tablas tenant heredan `OrgScoped` (org_id NOT NULL). Estas dos NO,
y esa es justo la funcionalidad: cuando un numero DESCONOCIDO escribe al WhatsApp
oficial, todavia no se sabe de que escuela es. Esa conversacion nace con
`org_id IS NULL`, queda **invisible para toda escuela** y solo la ve el superadmin,
que conversa con la persona y despues la **asigna** a una escuela (UPDATE del
`org_id` en la conversacion y en todos sus mensajes).

Que `NULL` sea invisible para la escuela NO depende de la app: sale de la propia
policy. `org_id = <org actual>` con `org_id IS NULL` evalua a NULL, y una policy
solo deja pasar la fila cuando la expresion es TRUE. Fail-closed por construccion.

## RLS de doble via (fail-closed en las dos)

  1. **Escuela** — el patron de siempre (0003/0005/0011/0021/0022/0023):
     `org_id = NULLIF(current_setting('app.current_org', true), '')::uuid`
     Sin contexto o con el GUC reseteado a '' -> NULL -> 0 filas.
  2. **Consola de plataforma y webhook** — GUC PROPIO
     `NULLIF(current_setting('app.whatsapp_inbox', true), '') = 'ALL'`
     El superadmin NUNCA fija `app.current_org` (ver `require_superadmin`), asi que
     sin esta segunda via no podria leer su propia bandeja; y el webhook de Meta
     escribe mensajes de numeros que aun no tienen org. El GUC es EXCLUSIVO de estas
     dos tablas: ninguna otra policy del esquema lo menciona, de modo que abrir la
     bandeja NO abre `pago`, `deportista` ni ninguna tabla tenant.

## Resolver de escuela por telefono (SECURITY DEFINER)

`public.whatsapp_tutores_telefonos()` devuelve `(org_id, telefono, nombres)` de TODOS
los tutores con telefono, saltando RLS de forma controlada (mismo patron que
`login_lookup`, el huevo-gallina del /login). Hace falta porque el webhook recibe un
numero y aun no sabe en que escuela buscarlo, y `tutor` esta bajo RLS.

La NORMALIZACION del telefono se hace en Python (`normalize_bo_phone`), no en SQL: es
la misma funcion que ya usa el resto del sistema (adaptadores, comprobantes) y
duplicarla en SQL abriria la puerta a que un numero casara en un lado y no en el otro.
La funcion devuelve las filas crudas y el servicio compara ya normalizado.

Alcance acotado: NO toca el RLS de ninguna tabla preexistente; solo crea las dos
tablas nuevas con su RLS propia y la funcion resolver.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas nuevas de este epic. Llevan RLS habilitada + forzada y GRANT de DML.
CHAT_TABLES: tuple[str, ...] = ("conversacion_whatsapp", "mensaje_whatsapp")

# Via 1 (escuela): patron fail-closed NULLIF de siempre. Con org_id NULL la
# comparacion da NULL -> la fila NO pasa (una policy exige TRUE), que es
# exactamente lo que queremos para los numeros sin clasificar.
_EXPR_ORG = "org_id = NULLIF(current_setting('app.current_org', true), '')::uuid"
# Via 2 (consola de plataforma / webhook): GUC propio, exclusivo de estas tablas.
_EXPR_INBOX = "NULLIF(current_setting('app.whatsapp_inbox', true), '') = 'ALL'"
_EXPR = f"({_EXPR_ORG} OR {_EXPR_INBOX})"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) `conversacion_whatsapp` -- UN hilo por numero (UNIQUE global de
    #    telefono: el WABA tiene un unico chat con cada numero, igual que la app
    #    de WhatsApp). org_id NULLABLE -> organizacion CASCADE.
    # ------------------------------------------------------------------ #
    op.create_table(
        "conversacion_whatsapp",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizacion.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("telefono", sa.String(), nullable=False),
        sa.Column("nombre_contacto", sa.String(), nullable=True),
        sa.Column("ultimo_mensaje_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ultimo_mensaje_texto", sa.Text(), nullable=True),
        sa.Column("ultimo_entrante_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("no_leidos", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("telefono", name="uq_conversacion_whatsapp_telefono"),
    )
    op.create_index("ix_conversacion_whatsapp_org_id", "conversacion_whatsapp", ["org_id"])
    # Orden de la bandeja (mas reciente primero), tanto en la escuela como en la consola.
    op.create_index(
        "ix_conversacion_whatsapp_ultimo",
        "conversacion_whatsapp",
        [sa.text("ultimo_mensaje_at DESC")],
    )

    # ------------------------------------------------------------------ #
    # 2) `mensaje_whatsapp` -- una burbuja del hilo. org_id denormalizado de la
    #    conversacion (columna de RLS; se propaga al asignar la escuela).
    #    provider_message_id UNIQUE = idempotencia del webhook de Meta (reintenta
    #    si no recibe 200) y clave por la que los eventos de estado encuentran su
    #    mensaje saliente.
    # ------------------------------------------------------------------ #
    op.create_table(
        "mensaje_whatsapp",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizacion.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "conversacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversacion_whatsapp.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direccion", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=True),
        sa.Column("media", sa.LargeBinary(), nullable=True),
        sa.Column("media_mime", sa.String(), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("estado", sa.String(), nullable=True),
        sa.Column("error_detalle", sa.Text(), nullable=True),
        sa.Column("enviado_por_nombre", sa.String(), nullable=True),
        sa.Column("ocurrido_en", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CHECK enum-like A MANO (patron repo: viven solo en la migracion).
        sa.CheckConstraint("direccion IN ('IN','OUT')", name="ck_mensaje_whatsapp_direccion"),
        sa.CheckConstraint(
            "tipo IN ('TEXTO','IMAGEN','PLANTILLA','OTRO')",
            name="ck_mensaje_whatsapp_tipo",
        ),
        sa.CheckConstraint(
            "estado IS NULL OR estado IN ('ENVIADO','ENTREGADO','LEIDO','FALLIDO')",
            name="ck_mensaje_whatsapp_estado",
        ),
        sa.UniqueConstraint("provider_message_id", name="uq_mensaje_whatsapp_provider"),
    )
    op.create_index("ix_mensaje_whatsapp_org_id", "mensaje_whatsapp", ["org_id"])
    # Hilo en orden cronologico (el `ocurrido_en` de Meta, no created_at: el
    # webhook puede llegar tarde o desordenado).
    op.create_index(
        "ix_mensaje_whatsapp_conversacion",
        "mensaje_whatsapp",
        ["conversacion_id", "ocurrido_en"],
    )

    # ------------------------------------------------------------------ #
    # 3) RLS de doble via (ver docstring): ENABLE + FORCE + policy `org_isolation`.
    #    Sin `TO rol`, como el resto del esquema.
    # ------------------------------------------------------------------ #
    for table in CHAT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            f"USING ({_EXPR}) WITH CHECK ({_EXPR});"
        )

    # ------------------------------------------------------------------ #
    # 4) GRANTs explicitos a latinosport_app (0001 ya fijo ALTER DEFAULT
    #    PRIVILEGES; se hacen explicitos para no depender de ello, como 0022/0023).
    # ------------------------------------------------------------------ #
    for table in CHAT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO latinosport_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO latinosport_app;")

    # ------------------------------------------------------------------ #
    # 5) Resolver de escuela por telefono (SECURITY DEFINER, patron login_lookup).
    #    Devuelve las filas CRUDAS: la normalizacion la hace `normalize_bo_phone`
    #    en Python, una sola implementacion para todo el sistema (ver docstring).
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.whatsapp_tutores_telefonos()
        RETURNS TABLE (
            org_id uuid,
            telefono text,
            nombres text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT t.org_id, t.telefono, t.nombres
            FROM public.tutor t
            WHERE t.telefono IS NOT NULL AND btrim(t.telefono) <> '';
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.whatsapp_tutores_telefonos() FROM PUBLIC;")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.whatsapp_tutores_telefonos() TO latinosport_app;"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.whatsapp_tutores_telefonos();")

    for table in reversed(CHAT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # mensaje_whatsapp primero (referencia a conversacion_whatsapp).
    op.drop_table("mensaje_whatsapp")
    op.drop_table("conversacion_whatsapp")
