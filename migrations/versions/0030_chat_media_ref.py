"""chat_media_ref: `mensaje_whatsapp.media_ref` + resolver SECURITY DEFINER del QR de
cobro, para MOSTRAR la imagen que salió sin duplicar sus bytes

Migracion del epic `chat-whatsapp`. Escrita A MANO (la funcion SECURITY DEFINER no la
detecta `--autogenerate`). `down_revision = "0029"`.

## El problema

Los recordatorios salen con el QR de cobro de la escuela en la cabecera, pero en el chat
la burbuja mostraba solo el texto: no se veia lo que el tutor recibio.

La salida obvia —copiar la imagen en cada mensaje— es la mala. Todos los recordatorios de
una escuela mandan EL MISMO QR: con 116 burbujas y 52 kB por QR serian ~6 MB de copias
identicas (tres veces la base entera de hoy), creciendo con cada corrida del cron y para
siempre.

## La solucion: referenciar, no copiar

`media_ref` guarda QUE imagen es, no la imagen:

  - `'qr'`  -> el QR de cobro de la escuela del mensaje (`qr_cobro`, una fila por org).
  - NULL    -> el mensaje no tiene imagen referenciada. Puede tener bytes propios en
               `media` (imagenes ENTRANTES, y el recibo del comprobante, que si se
               guarda: es UNICO por pago y ahi la fidelidad importa mas que el espacio).

El endpoint `/mensajes/{id}/media` sirve `media` si lo hay y si no resuelve `media_ref`.
Coste de almacenamiento: CERO.

## Por que hace falta una funcion SECURITY DEFINER

`qr_cobro` tiene RLS por `app.current_org`. La consola de PLATAFORMA nunca fija ese GUC
(ver `require_superadmin`), asi que al abrir el hilo de una escuela no podria leer su QR
y la burbuja quedaria rota justo en la consola. `whatsapp_qr_de_org(uuid)` devuelve la
imagen de UNA org saltando RLS de forma controlada — mismo patron que `login_lookup`
(0001), `whatsapp_tutores_telefonos` (0028) y `whatsapp_abrir_conversacion` (0029).

Devuelve solo `(imagen, mime)`: no expone ninguna otra columna ni ninguna otra tabla.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Referencia a una imagen que vive en otro lado (hoy solo 'qr'). NULL = sin
    # referencia; los bytes propios, si los hay, siguen en `media`.
    op.add_column("mensaje_whatsapp", sa.Column("media_ref", sa.String(), nullable=True))

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.whatsapp_qr_de_org(p_org uuid)
        RETURNS TABLE (imagen bytea, mime text)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT q.imagen, q.mime
            FROM public.qr_cobro q
            WHERE q.org_id = p_org
            LIMIT 1;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.whatsapp_qr_de_org(uuid) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION public.whatsapp_qr_de_org(uuid) TO latinosport_app;")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.whatsapp_qr_de_org(uuid);")
    op.drop_column("mensaje_whatsapp", "media_ref")
