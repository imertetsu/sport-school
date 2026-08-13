"""chat_documentos: el chat acepta PDF y notas de voz, no solo imagenes

Migracion del epic `chat-whatsapp`. Escrita A MANO (cambio de CHECK + columna).
`down_revision = "0031"`.

## Que problema resuelve

Una tutora mando el comprobante de su banco **en PDF** y en el chat aparecio
`[document]`, sin contenido: el webhook solo sabia descargar imagenes y todo lo demas
lo registraba con una etiqueta y nada mas. La escuela veia que algo habia llegado pero
no podia abrirlo — que es peor que no mostrarlo, porque parece un fallo.

Y no es un caso raro: los bancos bolivianos generan el comprobante como PDF tanto como
captura, asi que la mitad de las pruebas de pago llegaban muertas.

Dos cambios:

  - `tipo` admite ahora **DOCUMENTO** y **AUDIO** ademas de TEXTO/IMAGEN/PLANTILLA/OTRO.
    Son tipos distintos de verdad, no un IMAGEN forzado: se muestran distinto (un PDF
    se abre, una nota de voz se escucha) y conviene poder distinguirlos en consultas.
    OTRO se queda para lo que Meta ni siquiera nos deja descargar (`unsupported`).
  - `media_nombre` guarda el nombre original del archivo (`comprobante-agosto.pdf`).
    Sin el, la burbuja solo podria decir "documento", y en un hilo con varios adjuntos
    el nombre es lo unico que los distingue.

Los bytes siguen en `media` (bytea, tope de 8 MB en el adaptador), igual que las
imagenes entrantes.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIPOS_NUEVOS = "'TEXTO','IMAGEN','DOCUMENTO','AUDIO','PLANTILLA','OTRO'"
_TIPOS_VIEJOS = "'TEXTO','IMAGEN','PLANTILLA','OTRO'"


def upgrade() -> None:
    op.add_column("mensaje_whatsapp", sa.Column("media_nombre", sa.String(), nullable=True))
    op.drop_constraint("ck_mensaje_whatsapp_tipo", "mensaje_whatsapp", type_="check")
    op.create_check_constraint(
        "ck_mensaje_whatsapp_tipo", "mensaje_whatsapp", f"tipo IN ({_TIPOS_NUEVOS})"
    )


def downgrade() -> None:
    # Los mensajes que ya usen los tipos nuevos volverian a violar el CHECK viejo; se
    # reetiquetan como OTRO (que es exactamente lo que eran antes de esta migracion).
    op.execute("UPDATE mensaje_whatsapp SET tipo = 'OTRO' WHERE tipo IN ('DOCUMENTO','AUDIO')")
    op.drop_constraint("ck_mensaje_whatsapp_tipo", "mensaje_whatsapp", type_="check")
    op.create_check_constraint(
        "ck_mensaje_whatsapp_tipo", "mensaje_whatsapp", f"tipo IN ({_TIPOS_VIEJOS})"
    )
    op.drop_column("mensaje_whatsapp", "media_nombre")
