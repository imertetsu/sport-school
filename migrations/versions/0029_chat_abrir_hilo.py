"""chat_abrir_hilo: funcion SECURITY DEFINER para que una ESCUELA abra el hilo de un
tutor suyo (crear si no existe, adoptar si estaba sin clasificar, rechazar si es de otra)

Migracion del epic `chat-whatsapp` (fase 2: la escuela INICIA la conversacion).
Escrita A MANO: las funciones SECURITY DEFINER no las detecta `--autogenerate`.
`down_revision = "0028"`.

## El problema que resuelve

Hasta 0028 los hilos solo nacian en el webhook, que corre SIN usuario y abre la bandeja
completa (`app.whatsapp_inbox`). Ahora la escuela tambien crea hilos, y lo hace dentro de
su propio contexto de tenant (`app.current_org`) — donde la policy la deja ver SOLO lo
suyo. Eso rompe el patron "busca y si no esta, inserta":

  - el hilo del tutor existe pero esta SIN CLASIFICAR (`org_id IS NULL`) => la escuela no
    lo ve => intentaria INSERTar => choca con `uq_conversacion_whatsapp_telefono`;
  - el hilo existe y es de OTRA escuela => misma colision, y ademas no debe verlo.

Subir el GUC de la bandeja en el request de una escuela seria la solucion facil y la
equivocada: abriria TODOS los hilos de TODAS las escuelas durante esa transaccion. En vez
de eso, la unica operacion que necesita saltar RLS se encapsula aqui, igual que
`login_lookup` (0001) y `whatsapp_tutores_telefonos` (0028).

## Contrato de `whatsapp_abrir_conversacion(p_telefono text, p_org uuid) -> uuid`

Devuelve el id del hilo, o **NULL** si el numero ya pertenece a OTRA escuela (el llamador
lo traduce a un 409 explicito; ver `api/v1/chat.py`). Casos:

  1. No existe        -> lo CREA con `org_id = p_org` y devuelve su id.
  2. Existe sin org   -> lo ADOPTA: `org_id = p_org` y propaga el org a sus mensajes
                         (mismo efecto que la asignacion manual del superadmin). Es
                         legitimo porque el endpoint ya verifico —bajo RLS— que el
                         telefono es de un tutor de esa escuela.
  3. Existe con org = p_org -> devuelve su id (no toca nada).
  4. Existe con OTRO org    -> devuelve NULL (no filtra ni un dato del hilo ajeno).

`p_org` NO puede ser NULL: esta funcion es el camino de la ESCUELA. El superadmin no la
necesita, porque su GUC ya le da la bandeja entera.

La normalizacion del telefono se hace ANTES, en Python (`normalize_bo_phone`): la funcion
recibe el numero ya en E.164 y solo compara. Una segunda implementacion en SQL acabaria
casando distinto que el resto del sistema.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.whatsapp_abrir_conversacion(
            p_telefono text,
            p_org uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_id  uuid;
            v_org uuid;
        BEGIN
            IF p_org IS NULL OR p_telefono IS NULL OR btrim(p_telefono) = '' THEN
                RETURN NULL;
            END IF;

            SELECT id, org_id INTO v_id, v_org
            FROM public.conversacion_whatsapp
            WHERE telefono = p_telefono;

            -- 1) No existe: se crea ya asignado a la escuela que lo abre.
            IF v_id IS NULL THEN
                INSERT INTO public.conversacion_whatsapp
                    (org_id, telefono, ultimo_mensaje_at, no_leidos)
                VALUES (p_org, p_telefono, now(), 0)
                ON CONFLICT (telefono) DO NOTHING
                RETURNING id INTO v_id;

                -- Carrera: otro request lo creo entre el SELECT y el INSERT.
                IF v_id IS NULL THEN
                    SELECT id, org_id INTO v_id, v_org
                    FROM public.conversacion_whatsapp
                    WHERE telefono = p_telefono;
                    IF v_org IS NOT NULL AND v_org <> p_org THEN
                        RETURN NULL;
                    END IF;
                END IF;

                RETURN v_id;
            END IF;

            -- 4) Es de otra escuela: no se toca ni se revela.
            IF v_org IS NOT NULL AND v_org <> p_org THEN
                RETURN NULL;
            END IF;

            -- 2) Estaba sin clasificar: la escuela lo adopta y se lleva el historial.
            IF v_org IS NULL THEN
                UPDATE public.conversacion_whatsapp SET org_id = p_org WHERE id = v_id;
                UPDATE public.mensaje_whatsapp
                   SET org_id = p_org
                 WHERE conversacion_id = v_id AND org_id IS NULL;
            END IF;

            -- 3) Ya era suyo (o acaba de serlo).
            RETURN v_id;
        END;
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.whatsapp_abrir_conversacion(text, uuid) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.whatsapp_abrir_conversacion(text, uuid) "
        "TO latinosport_app;"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.whatsapp_abrir_conversacion(text, uuid);")
