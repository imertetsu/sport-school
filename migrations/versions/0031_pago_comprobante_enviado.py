"""pago.comprobante_enviado_en — candado contra el comprobante duplicado por WhatsApp

Migracion del epic `chat-whatsapp` (secuela). Escrita A MANO (una columna; no hace falta
autogenerar). `down_revision = "0030"`.

## Que problema resuelve

El comprobante al tutor sale por DOS caminos que hasta ahora no se conocian:

  1. automatico, al confirmar el pago (`pagos._enviar_recibo_por_whatsapp`);
  2. manual, con el boton "Enviar por WhatsApp" de Registrar pago / historial / perfil.

El resultado fue un tutor recibiendo el MISMO comprobante dos veces con 6 segundos de
diferencia. Y una vez enviado no hay vuelta atras: la Cloud API de Meta **no tiene**
endpoint para eliminar un mensaje ya entregado, asi que un duplicado se queda en el
telefono del padre para siempre. La unica defensa posible es no mandarlo dos veces.

`comprobante_enviado_en` marca el instante del primer envio ACEPTADO por el proveedor.
Con eso el servicio corta el segundo (`motivo="ya_enviado"`) salvo que se pida
explicitamente `forzar=True` — el caso legitimo de "el tutor dice que no le llego".

NULL = todavia no se envio. Los pagos historicos quedan en NULL, que es correcto: no
sabemos si su comprobante salio, y ante la duda es mejor permitir el envio que
bloquearlo (un comprobante de mas es molesto; ninguno, es un problema de verdad).

Tambien cubre el doble clic y el reintento nervioso, que son las otras dos formas
habituales de duplicar.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pago",
        sa.Column("comprobante_enviado_en", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pago", "comprobante_enviado_en")
