"""Trae al chat los recordatorios de cuota YA enviados (epic chat-whatsapp).

Por qué hace falta: los recordatorios se vienen mandando desde junio y quedaron
registrados en `recordatorio_pago`, que es una tabla de control — no aparecen en la
conversación. El resultado es un chat que miente por omisión: el tutor responde "ya
pagué" y arriba no hay nada a lo que esté respondiendo.

**Reconstrucción, no copia.** El texto exacto del mensaje no se guardó nunca, así que la
burbuja se arma con lo que sí quedó: tipo (mora / próximo vencimiento), deportista, mes
de la cuota, monto y estado de entrega. Se marca con `(histórico)` en el autor para que
nadie la confunda con una transcripción literal.

Es **idempotente**: se puede correr dos veces sin duplicar. Los envíos con id de Meta se
detectan por ese id; los fallidos (que no tienen) por la terna hilo + instante + autor.

Uso:
    docker compose -f infra/docker-compose.yml run --rm --no-deps \\
        -v /opt/latinosport/infra:/app/infra -w /app api \\
        python infra/backfill-chat-recordatorios.py [--aplicar]

Sin `--aplicar` hace un ENSAYO: cuenta y muestra qué crearía, sin escribir nada.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.db import SessionLocal
from app.services import chat_whatsapp as chat_svc
from app.services.pagos import _MESES_LARGO

APLICAR = "--aplicar" in sys.argv

# Autor de las burbujas reconstruidas. Distinto del de los recordatorios nuevos: estos
# no son el mensaje que se envió, son lo que se pudo reconstruir de él.
AUTOR = f"{chat_svc.AUTOR_RECORDATORIO} (histórico)"

ETIQUETA_TIPO = {
    "MOROSIDAD": "Recordatorio de cuota vencida",
    "PROXIMO_VENCIMIENTO": "Aviso de próximo vencimiento",
}

# Los recordatorios de cada escuela, con el deportista y la cuota a los que se referían.
# Corre bajo el `app.current_org` de cada org (RLS), por eso se pide org por org.
CONSULTA = text(
    """
    SELECT r.id,
           r.destino,
           r.tipo,
           r.estado,
           r.enviado_en,
           r.provider_message_id,
           c.vence_el,
           c.monto,
           d.ap_paterno,
           d.ap_materno,
           d.nombres
      FROM recordatorio_pago r
      LEFT JOIN cuota c       ON c.id = r.cuota_id
      LEFT JOIN inscripcion i ON i.id = c.inscripcion_id
      LEFT JOIN deportista d  ON d.id = i.deportista_id
     WHERE r.destino IS NOT NULL AND btrim(r.destino) <> ''
     ORDER BY r.enviado_en
    """
)

# ¿Ya existe la burbuja de un envío SIN id de Meta? (los fallidos no tienen ninguno).
#
# El TEXTO forma parte de la clave, y no es un detalle: el cron manda todos los
# recordatorios de una corrida en UNA transacción, y el `now()` de Postgres es el mismo
# para toda la transacción — así que un tutor con dos hijos tiene DOS filas con el
# instante idéntico. Sin el texto, la segunda (la del otro hijo) se descartaba como
# duplicada y ese recordatorio desaparecía del historial.
YA_ESTA = text(
    """
    SELECT 1
      FROM mensaje_whatsapp m
      JOIN conversacion_whatsapp c ON c.id = m.conversacion_id
     WHERE c.telefono = :tel
       AND m.ocurrido_en = :cuando
       AND m.enviado_por_nombre = :autor
       AND m.texto IS NOT DISTINCT FROM :texto
     LIMIT 1
    """
)


def _texto(fila) -> str:
    """La burbuja reconstruida con los datos que sí sobrevivieron."""
    partes = [ETIQUETA_TIPO.get(fila.tipo, fila.tipo)]
    nombre = " ".join(p for p in (fila.ap_paterno, fila.ap_materno, fila.nombres) if p)
    if nombre:
        partes.append(nombre)
    if fila.vence_el is not None:
        partes.append(f"cuota de {_MESES_LARGO[fila.vence_el.month].upper()} {fila.vence_el.year}")
    if fila.monto is not None:
        partes.append(f"Bs {fila.monto}")
    return " · ".join(partes)


def _reparar_cabeceras(db, org_id) -> int:
    """Recalcula fecha, vista previa y nombre de cada hilo desde sus mensajes reales.

    Hace falta porque el hilo se crea con `ultimo_mensaje_at = now()` y la cabecera solo
    avanza hacia adelante: al insertar mensajes ANTIGUOS (este backfill), la bandeja
    quedaba con todos los hilos fechados hoy y sin vista previa — inservible para
    ordenar o reconocer nada.

    Devuelve cuántos hilos se corrigieron. Idempotente: correrlo de nuevo no cambia nada.
    """
    hilos = db.execute(
        text("SELECT id, telefono, nombre_contacto FROM conversacion_whatsapp")
    ).all()
    corregidos = 0
    for hilo in hilos:
        ultimo = db.execute(
            text(
                "SELECT ocurrido_en, texto, tipo FROM mensaje_whatsapp "
                "WHERE conversacion_id = :c "
                "ORDER BY ocurrido_en DESC, created_at DESC LIMIT 1"
            ),
            {"c": str(hilo.id)},
        ).first()
        if ultimo is None:
            continue

        # Vista previa con la MISMA regla que el envío en vivo (una imagen sin texto no
        # puede dejar la bandeja en blanco).
        preview = chat_svc._preview(ultimo.tipo, ultimo.texto)[:200]
        nombre = hilo.nombre_contacto or chat_svc.nombre_tutor_local(db, hilo.telefono)

        res = db.execute(
            text(
                "UPDATE conversacion_whatsapp "
                "SET ultimo_mensaje_at = :cuando, ultimo_mensaje_texto = :preview, "
                "    nombre_contacto = :nombre "
                "WHERE id = :id AND (ultimo_mensaje_at <> :cuando "
                "   OR ultimo_mensaje_texto IS DISTINCT FROM :preview "
                "   OR nombre_contacto IS DISTINCT FROM :nombre)"
            ),
            {
                "id": str(hilo.id),
                "cuando": ultimo.ocurrido_en,
                "preview": preview,
                "nombre": nombre,
            },
        )
        corregidos += res.rowcount or 0
    return corregidos


def main() -> int:
    with SessionLocal() as db:
        orgs = db.execute(text("SELECT id, nombre FROM organizacion ORDER BY nombre")).all()

    total_creadas = total_saltadas = total_sin_hilo = 0

    for org_id, nombre in orgs:
        creadas = saltadas = sin_hilo = 0
        with SessionLocal() as db:
            db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_id)})
            filas = db.execute(CONSULTA).all()
            tiene_qr = (
                db.execute(text("SELECT 1 FROM qr_cobro LIMIT 1")).first() is not None
            )

            # Burbujas históricas creadas por una corrida ANTERIOR (antes de que
            # existiera `media_ref`): se les pone la referencia al QR para que también
            # muestren la imagen, en vez de tener que borrarlas y rehacerlas.
            if APLICAR and tiene_qr:
                db.execute(
                    text(
                        "UPDATE mensaje_whatsapp SET media_ref = :ref "
                        "WHERE enviado_por_nombre = :autor AND media_ref IS NULL "
                        "AND media IS NULL"
                    ),
                    {"ref": chat_svc.MEDIA_REF_QR, "autor": AUTOR},
                )

            for fila in filas:
                telefono_norm = chat_svc.normalize_bo_phone(fila.destino)
                if telefono_norm is None:
                    sin_hilo += 1
                    continue

                cuerpo = _texto(fila)

                # Idempotencia: por id de Meta si lo hay; si no, por
                # (hilo, instante, autor, texto) — ver el comentario de YA_ESTA.
                if fila.provider_message_id:
                    existe = db.execute(
                        text(
                            "SELECT 1 FROM mensaje_whatsapp "
                            "WHERE provider_message_id = :m LIMIT 1"
                        ),
                        {"m": fila.provider_message_id},
                    ).first()
                else:
                    existe = db.execute(
                        YA_ESTA,
                        {
                            "tel": telefono_norm,
                            "cuando": fila.enviado_en,
                            "autor": AUTOR,
                            "texto": cuerpo,
                        },
                    ).first()
                if existe:
                    saltadas += 1
                    continue

                if not APLICAR:
                    creadas += 1
                    continue

                msg = chat_svc.registrar_automatico(
                    db,
                    org_id=org_id,
                    telefono=telefono_norm,
                    tipo="PLANTILLA",
                    texto=cuerpo,
                    estado="ENVIADO" if fila.estado == "ENVIADO" else "FALLIDO",
                    provider_message_id=fila.provider_message_id,
                    autor=AUTOR,
                    ocurrido_en=fila.enviado_en,
                    # El recordatorio salió con el QR de cobro de la escuela; se
                    # referencia (no se copia) igual que los nuevos. Si la escuela no
                    # tiene QR cargado, la referencia simplemente no resuelve.
                    media_ref=chat_svc.MEDIA_REF_QR if tiene_qr else None,
                )
                if msg is None:
                    sin_hilo += 1
                else:
                    creadas += 1

            reparados = _reparar_cabeceras(db, org_id) if APLICAR else 0
            if APLICAR:
                db.commit()

        print(
            f"{nombre[:34]:36} {creadas:4} burbuja(s)"
            f"   {saltadas:3} ya estaban   {sin_hilo:3} sin hilo"
            f"   {reparados:3} cabecera(s) corregida(s)"
        )
        total_creadas += creadas
        total_saltadas += saltadas
        total_sin_hilo += sin_hilo

    modo = "CREADAS" if APLICAR else "SE CREARÍAN (ensayo, no se escribió nada)"
    print(
        f"\n{modo}: {total_creadas} · ya estaban: {total_saltadas} · sin hilo: {total_sin_hilo}"
    )
    if not APLICAR:
        print("Volvé a correrlo con --aplicar para escribirlas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
