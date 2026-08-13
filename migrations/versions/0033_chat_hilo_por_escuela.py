"""chat_hilo_por_escuela: un hilo por (telefono, escuela), no uno por telefono

Migracion del epic `chat-whatsapp`. Escrita A MANO (indices parciales).
`down_revision = "0032"`.

## La suposicion equivocada

0028 modelo la conversacion como "un numero, un hilo", copiando lo que hace la app de
WhatsApp: el WABA tiene un unico chat con cada numero. Es cierto del lado del TUTOR, y
por eso parecia correcto.

Pero del lado de la escuela no lo es. **Una madre puede tener hijas en dos escuelas
distintas** — y pasa de verdad: la misma mamá (61622345) tiene una hija en Halcones y
otra en Aguilas del Sur. Con un hilo unico, la primera escuela que le escribia se
quedaba con la conversacion y la segunda:

  - no podia abrir el chat (409 "ese numero ya tiene una conversacion asignada a otra
    escuela"), y
  - sus recordatorios SI salian por WhatsApp pero no dejaban burbuja, porque el hilo
    era ajeno. La escuela veia que "no paso nada", lo reintentaba, y se topaba con el
    "ya se habia enviado este recordatorio" del control de idempotencia. Dos sintomas,
    una causa.

Peor aun: habria sido un problema de PRIVACIDAD si lo hubieramos resuelto al reves
(dejar que las dos vean el mismo hilo), porque cada escuela leeria los mensajes que la
familia le escribio a la otra.

## El modelo correcto

La conversacion es de la escuela CON el tutor, no del numero. Dos indices parciales en
vez del UNIQUE simple:

  - `uq_conversacion_whatsapp_tel_org`  (telefono, org_id) WHERE org_id IS NOT NULL
    -> cada escuela tiene, como mucho, UN hilo con ese numero. Los suyos, separados.
  - `uq_conversacion_whatsapp_tel_libre` (telefono) WHERE org_id IS NULL
    -> y como mucho UN hilo sin clasificar por numero, que es la cola del superadmin.

El tutor sigue viendo UNA sola conversacion en su telefono (el numero oficial es uno
solo); son las escuelas las que ven cada una la suya. Que es exactamente como funciona
hoy fuera del sistema, cuando la secretaria de cada escuela escribe desde su celular.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_conversacion_whatsapp_telefono", "conversacion_whatsapp", type_="unique"
    )
    op.create_index(
        "uq_conversacion_whatsapp_tel_org",
        "conversacion_whatsapp",
        ["telefono", "org_id"],
        unique=True,
        postgresql_where=sa.text("org_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversacion_whatsapp_tel_libre",
        "conversacion_whatsapp",
        ["telefono"],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
    )


def downgrade() -> None:
    # Volver al UNIQUE simple exige que no queden DOS hilos del mismo numero. Se
    # conserva el mas activo de cada telefono y sus mensajes se juntan ahi: perder
    # conversaciones en un downgrade seria mucho peor que juntarlas.
    op.execute(
        """
        WITH ganador AS (
            SELECT DISTINCT ON (telefono) telefono, id
            FROM conversacion_whatsapp
            ORDER BY telefono, ultimo_mensaje_at DESC, id
        )
        UPDATE mensaje_whatsapp m
           SET conversacion_id = g.id
          FROM conversacion_whatsapp c
          JOIN ganador g ON g.telefono = c.telefono
         WHERE m.conversacion_id = c.id AND c.id <> g.id
        """
    )
    op.execute(
        """
        DELETE FROM conversacion_whatsapp c
        USING (
            SELECT DISTINCT ON (telefono) telefono, id
            FROM conversacion_whatsapp
            ORDER BY telefono, ultimo_mensaje_at DESC, id
        ) g
        WHERE c.telefono = g.telefono AND c.id <> g.id
        """
    )
    op.drop_index("uq_conversacion_whatsapp_tel_libre", table_name="conversacion_whatsapp")
    op.drop_index("uq_conversacion_whatsapp_tel_org", table_name="conversacion_whatsapp")
    op.create_unique_constraint(
        "uq_conversacion_whatsapp_telefono", "conversacion_whatsapp", ["telefono"]
    )
