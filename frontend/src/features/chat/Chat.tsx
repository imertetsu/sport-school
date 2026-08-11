import { useMemo } from 'react';
import { api } from '@/api/client';
import { ChatWhatsApp, type ChatAgenda, type ChatApi } from './ChatWhatsApp';

// Chat de la ESCUELA (epic chat-whatsapp). Solo ADMIN: la ruta lleva gate de rol
// y el backend exige `require_role("ADMIN")`.
//
// La escuela ve únicamente los hilos de SUS tutores — no por un filtro de esta
// pantalla, sino por RLS. Un número que todavía no se sabe de qué escuela es no le
// llega: lo atiende la consola de plataforma hasta que alguien lo categoriza.
export function Chat() {
  // El objeto de endpoints es estable: si se recreara en cada render, los
  // `useEffect` del chat (que dependen de él) reprogramarían el sondeo sin parar.
  const chatApi = useMemo<ChatApi>(
    () => ({
      conversaciones: (params, signal) =>
        api.chatConversaciones(
          { buscar: params.buscar, cursorAt: params.cursorAt, cursorId: params.cursorId },
          signal,
        ),
      hilo: (id, signal) => api.chatHilo(id, signal),
      responder: (id, texto, signal) => api.chatResponder(id, texto, signal),
      media: (id, signal) => api.chatMedia(id, signal),
    }),
    [],
  );

  // Agenda: la escuela puede ESCRIBIR PRIMERO a cualquiera de sus tutores, no solo
  // responder a quien escribió. El backend valida que el número sea de un tutor suyo.
  const agenda = useMemo<ChatAgenda>(
    () => ({
      tutores: (buscar, signal) => api.chatTutores(buscar, signal),
      abrir: (telefono, signal) => api.chatAbrir(telefono, signal),
    }),
    [],
  );

  return (
    <ChatWhatsApp
      chatApi={chatApi}
      agenda={agenda}
      titulo="Chat"
      vacio='Todavía no hay conversaciones. Usá "Nuevo mensaje" para escribirle a un tutor, o esperá a que escriban al WhatsApp de la escuela.'
    />
  );
}
