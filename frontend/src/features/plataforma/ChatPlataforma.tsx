import { useEffect, useMemo, useState } from 'react';
import { platformApi } from '@/api/client';
import type { Escuela } from '@/api/types';
import { ChatWhatsApp, type ChatApi, type EscuelaRef } from '@/features/chat/ChatWhatsApp';

// Chat de la consola de PLATAFORMA (epic chat-whatsapp).
//
// Ve TODOS los hilos, incluidos los de números que todavía no se sabe de qué
// escuela son (`org_id IS NULL`) — que son los que NINGUNA escuela ve. El trabajo
// de esta pantalla es justo ese: conversar con el número nuevo, averiguar a qué
// escuela pertenece y asignárselo con el selector de la cabecera. Desde ese
// momento la escuela lo ve en su propio chat con todo el historial.
export function ChatPlataforma() {
  const [escuelas, setEscuelas] = useState<EscuelaRef[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    platformApi
      .escuelas(controller.signal)
      .then((lista: Escuela[]) =>
        setEscuelas(lista.map((e) => ({ id: e.id, nombre: e.nombre }))),
      )
      // Sin la lista, el chat sigue sirviendo para leer y responder; solo queda
      // sin selector de escuela. No vale la pena romper la pantalla por esto.
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const chatApi = useMemo<ChatApi>(
    () => ({
      conversaciones: (params, signal) => platformApi.chatConversaciones(params, signal),
      hilo: (id, signal) => platformApi.chatHilo(id, signal),
      responder: (id, texto, signal) => platformApi.chatResponder(id, texto, signal),
      media: (id, signal) => platformApi.chatMedia(id, signal),
      asignar: (id, orgId, signal) => platformApi.chatAsignar(id, orgId, signal),
    }),
    [],
  );

  return (
    <ChatWhatsApp
      chatApi={chatApi}
      escuelas={escuelas}
      titulo="Chat"
      vacio="Todavía no hay conversaciones."
    />
  );
}
