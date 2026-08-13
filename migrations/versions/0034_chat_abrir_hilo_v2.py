"""chat_abrir_hilo_v2: abrir el hilo de un tutor deja de rechazar por "es de otra escuela"

Migracion del epic `chat-whatsapp`. Reemplaza el cuerpo de
`whatsapp_abrir_conversacion` (0029) para el modelo de 0033: un hilo por
(telefono, escuela). Escrita A MANO. `down_revision = "0033"`.

Antes la funcion devolvia NULL cuando el numero ya tenia hilo con OTRA escuela, y el
endpoint lo traducia a un 409. Con hilos por escuela ese caso ya no existe: cada escuela
abre el suyo, con sus propios mensajes, sin ver los de la otra. NULL queda solo para los
argumentos invalidos.

El orden importa:
  1. ¿La escuela ya tiene hilo con ese numero? -> se devuelve.
  2. ¿Hay un hilo SIN clasificar de ese numero? -> se ADOPTA (con su historial). Es el
     caso de "el numero escribio primero, el superadmin no llego a clasificarlo y la
     escuela le escribe desde la agenda". Adoptar en vez de crear uno nuevo evita
     partir la conversacion en dos.
  3. Si no, se crea uno nuevo para (telefono, escuela).

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CUERPO_V2 = """
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
    v_id uuid;
BEGIN
    IF p_org IS NULL OR p_telefono IS NULL OR btrim(p_telefono) = '' THEN
        RETURN NULL;
    END IF;

    -- 1) La escuela ya tiene su hilo con este numero.
    SELECT id INTO v_id
    FROM public.conversacion_whatsapp
    WHERE telefono = p_telefono AND org_id = p_org;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;

    -- 2) Hay un hilo SIN clasificar: se adopta con todo su historial, en vez de
    --    abrir uno nuevo y partir la conversacion en dos.
    SELECT id INTO v_id
    FROM public.conversacion_whatsapp
    WHERE telefono = p_telefono AND org_id IS NULL;
    IF v_id IS NOT NULL THEN
        UPDATE public.conversacion_whatsapp SET org_id = p_org WHERE id = v_id;
        UPDATE public.mensaje_whatsapp
           SET org_id = p_org
         WHERE conversacion_id = v_id AND org_id IS NULL;
        RETURN v_id;
    END IF;

    -- 3) Hilo nuevo para esta escuela. Que otra escuela ya tenga el suyo con el mismo
    --    numero es NORMAL (una madre con hijas en dos escuelas) y no estorba.
    INSERT INTO public.conversacion_whatsapp
        (org_id, telefono, ultimo_mensaje_at, no_leidos)
    VALUES (p_org, p_telefono, now(), 0)
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_id;

    -- Carrera: otro request lo creo entre el SELECT y el INSERT.
    IF v_id IS NULL THEN
        SELECT id INTO v_id
        FROM public.conversacion_whatsapp
        WHERE telefono = p_telefono AND org_id = p_org;
    END IF;

    RETURN v_id;
END;
$$;
"""

# El de 0029: rechazaba (NULL) si el numero era de otra escuela.
_CUERPO_V1 = """
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

    IF v_id IS NULL THEN
        INSERT INTO public.conversacion_whatsapp
            (org_id, telefono, ultimo_mensaje_at, no_leidos)
        VALUES (p_org, p_telefono, now(), 0)
        ON CONFLICT (telefono) DO NOTHING
        RETURNING id INTO v_id;

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

    IF v_org IS NOT NULL AND v_org <> p_org THEN
        RETURN NULL;
    END IF;

    IF v_org IS NULL THEN
        UPDATE public.conversacion_whatsapp SET org_id = p_org WHERE id = v_id;
        UPDATE public.mensaje_whatsapp
           SET org_id = p_org
         WHERE conversacion_id = v_id AND org_id IS NULL;
    END IF;

    RETURN v_id;
END;
$$;
"""


def upgrade() -> None:
    op.execute(_CUERPO_V2)


def downgrade() -> None:
    op.execute(_CUERPO_V1)
