import { api } from '@/api/client';
import type { EnviarComprobanteOut } from '@/api/types';

// Envío del comprobante por WhatsApp, compartido por las TRES pantallas que lo
// ofrecen (Registrar pago, historial de pagos y perfil del deportista).
//
// Existe por una razón concreta: el comprobante también sale SOLO al confirmar el
// pago, así que apretar el botón después mandaba el mismo mensaje dos veces. Y una
// vez entregado no hay vuelta atrás — la API de WhatsApp no permite eliminar un
// mensaje enviado, así que el duplicado se queda en el teléfono del tutor.
//
// El backend corta el segundo envío (`motivo: "ya_enviado"`) y acá se convierte en
// una pregunta explícita, en vez de un error que no se entiende. Reenviar sigue
// siendo posible: es el caso de "el tutor dice que no le llegó".

// `motivo` propio (no viene del backend) para cuando se ofreció reenviar y la
// persona dijo que no. La pantalla no debe mostrar ni éxito ni error.
export const MOTIVO_CANCELADO = 'cancelado';

function cuandoLegible(iso: string | null): string {
  if (!iso) return 'antes';
  const d = new Date(iso);
  return d.toLocaleString('es-BO', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export async function enviarComprobanteConfirmando(
  pagoId: string,
  signal?: AbortSignal,
): Promise<EnviarComprobanteOut> {
  const res = await api.enviarComprobanteWhatsapp(pagoId, false, signal);
  if (res.motivo !== 'ya_enviado') return res;

  const ok = window.confirm(
    `Este comprobante ya se le envió al tutor el ${cuandoLegible(res.enviado_en)}.\n\n` +
      'Si lo mandás de nuevo va a recibir el mismo mensaje dos veces, y WhatsApp no ' +
      'permite borrarlo después.\n\n¿Reenviar igual?',
  );
  if (!ok) return { ...res, motivo: MOTIVO_CANCELADO };

  return api.enviarComprobanteWhatsapp(pagoId, true, signal);
}
