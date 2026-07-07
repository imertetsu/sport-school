import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import { Button, Card, useToast } from '@/components/ui';
import { formatDate } from '@/lib/format';
import type { WhatsAppEstado } from '@/api/types';
import './WhatsAppVinculacion.css';

// WhatsApp de la escuela (epic whatsapp-multitenant) — SOLO ADMIN. Se monta en
// Ajustes, cuya ruta ya está gateada con RoleRoute allow={['ADMIN']}; el backend
// además impone require_role("ADMIN") y scopea SIEMPRE a user.org_id (el cliente
// NUNCA manda org_id). El QR (data-url) viaja browser<-backend<-sidecar: el
// browser nunca ve el token ni la URL del sidecar.
//
// Flujo:
//  - DESVINCULADA: "Vincular WhatsApp" -> POST /vincular.
//  - PENDIENTE_QR: muestra el QR (img del data-url). Si qr:null, reintenta
//    GET /qr cada ~2s hasta tener el data-url. Polling de GET /estado cada ~3s
//    hasta CONECTADA (timeout ~2min -> "el QR expiró, reintenta").
//  - CONECTADA: "Conectado como +<numero>" + Desvincular (con confirmación).
// Todos los intervalos/timeouts se limpian al desmontar (cleanup en useEffect).

const QR_REFETCH_MS = 2000; // reintento de GET /qr cuando qr:null
const ESTADO_POLL_MS = 3000; // polling de GET /estado mientras PENDIENTE_QR
const QR_TIMEOUT_MS = 120000; // ~2min: el QR expira -> pedir reintento

export function WhatsAppVinculacion() {
  const toast = useToast();
  const [estado, setEstado] = useState<WhatsAppEstado | null>(null);
  const [numero, setNumero] = useState<string | null>(null);
  const [vinculadoEn, setVinculadoEn] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [vinculando, setVinculando] = useState(false);
  const [desvinculando, setDesvinculando] = useState(false);
  // El QR expiró sin parear (timeout): se muestra el aviso y se ofrece reintentar.
  const [qrExpirado, setQrExpirado] = useState(false);

  // Refs vivos para los efectos de polling: evitan recrear los intervalos en cada
  // render y permiten un cleanup fiable al desmontar.
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  function aplicarEstado(data: {
    estado: WhatsAppEstado;
    numero: string | null;
    vinculado_en?: string | null;
  }) {
    setEstado(data.estado);
    setNumero(data.numero);
    if (data.vinculado_en !== undefined) setVinculadoEn(data.vinculado_en);
    if (data.estado === 'CONECTADA') {
      setQr(null);
      setQrExpirado(false);
    }
    if (data.estado === 'DESVINCULADA') {
      setQr(null);
      setVinculadoEn(null);
    }
  }

  // Carga inicial: GET /estado.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(null);
    api
      .whatsappEstado(controller.signal)
      .then((data) => {
        if (!active) return;
        aplicarEstado(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.isForbidden) {
          setLoadError('No tienes permiso para gestionar el WhatsApp de la escuela.');
        } else {
          setLoadError(
            err instanceof ApiError
              ? err.message
              : 'No se pudo cargar el estado del WhatsApp.',
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const empezarVinculacion = useCallback(async () => {
    setActionError(null);
    setQrExpirado(false);
    setQr(null);
    setVinculando(true);
    try {
      const data = await api.whatsappVincular();
      if (!mountedRef.current) return;
      if (data.estado === 'CONECTADA') {
        aplicarEstado({ estado: 'CONECTADA', numero: data.numero });
      } else {
        setEstado('PENDIENTE_QR');
        setQr(data.qr); // puede ser null: el efecto de PENDIENTE_QR lo reintenta
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setActionError(
        err instanceof ApiError ? err.message : 'No se pudo iniciar la vinculación.',
      );
    } finally {
      if (mountedRef.current) setVinculando(false);
    }
  }, []);

  // Mientras PENDIENTE_QR: (1) si falta el QR, reintenta GET /qr cada ~2s; (2)
  // hace polling de GET /estado cada ~3s hasta CONECTADA; (3) corta a ~2min con
  // un aviso de expiración. Todos los timers se limpian al salir del estado o al
  // desmontar (cleanup del efecto).
  useEffect(() => {
    if (estado !== 'PENDIENTE_QR' || qrExpirado) return;

    const controller = new AbortController();
    let qrTimer: ReturnType<typeof setInterval> | null = null;
    let estadoTimer: ReturnType<typeof setInterval> | null = null;
    let expiracion: ReturnType<typeof setTimeout> | null = null;
    let qrEnVuelo = false;
    let estadoEnVuelo = false;

    const limpiar = () => {
      if (qrTimer) clearInterval(qrTimer);
      if (estadoTimer) clearInterval(estadoTimer);
      if (expiracion) clearTimeout(expiracion);
      controller.abort();
    };

    const refetchQr = async () => {
      if (qrEnVuelo) return;
      qrEnVuelo = true;
      try {
        const data = await api.whatsappQr(controller.signal);
        if (!mountedRef.current) return;
        if (data.estado === 'CONECTADA') {
          aplicarEstado({ estado: 'CONECTADA', numero: data.numero });
        } else if (data.qr) {
          setQr(data.qr);
        }
      } catch {
        /* reintento silencioso: el siguiente tick lo vuelve a intentar */
      } finally {
        qrEnVuelo = false;
      }
    };

    const pollEstado = async () => {
      if (estadoEnVuelo) return;
      estadoEnVuelo = true;
      try {
        const data = await api.whatsappEstado(controller.signal);
        if (!mountedRef.current) return;
        if (data.estado === 'CONECTADA' || data.estado === 'DESVINCULADA') {
          aplicarEstado(data);
        }
      } catch {
        /* reintento silencioso en el siguiente tick */
      } finally {
        estadoEnVuelo = false;
      }
    };

    // Si aún no hay QR, pídelo de inmediato y sigue reintentando.
    if (!qr) {
      void refetchQr();
      qrTimer = setInterval(refetchQr, QR_REFETCH_MS);
    }
    estadoTimer = setInterval(pollEstado, ESTADO_POLL_MS);
    expiracion = setTimeout(() => {
      if (!mountedRef.current) return;
      setQrExpirado(true);
      setQr(null);
    }, QR_TIMEOUT_MS);

    return limpiar;
    // qr entra en deps para arrancar/parar el reintento de QR según haya o no
    // data-url; estado/qrExpirado para montar el efecto solo en PENDIENTE_QR vivo.
  }, [estado, qr, qrExpirado]);

  async function desvincular() {
    const ok = window.confirm(
      '¿Desvincular el WhatsApp de la escuela? Dejarás de enviar recordatorios y avisos desde este número hasta volver a vincularlo.',
    );
    if (!ok) return;
    setActionError(null);
    setDesvinculando(true);
    try {
      const data = await api.whatsappDesvincular();
      if (!mountedRef.current) return;
      aplicarEstado({ estado: data.estado, numero: null, vinculado_en: null });
      toast.success('WhatsApp desvinculado');
    } catch (err) {
      if (!mountedRef.current) return;
      const msg =
        err instanceof ApiError ? err.message : 'No se pudo desvincular el WhatsApp.';
      setActionError(msg);
      toast.error(msg);
    } finally {
      if (mountedRef.current) setDesvinculando(false);
    }
  }

  return (
    <Card
      title="WhatsApp de la escuela"
      className="whatsapp-vinc"
    >
      <p className="whatsapp-vinc__intro">
        Vincula el WhatsApp de tu escuela para enviar recordatorios de cobro, recibos
        y avisos desde tu propio número.
      </p>

      {loadError && (
        <div className="page-error" role="alert">
          {loadError}
        </div>
      )}

      {!loadError && loading && (
        <p className="whatsapp-vinc__loading">Cargando…</p>
      )}

      {!loadError && !loading && (
        <div className="whatsapp-vinc__body">
          {estado === 'DESVINCULADA' && (
            <div className="whatsapp-vinc__estado">
              <div className="whatsapp-vinc__estado-row">
                <span className="whatsapp-vinc__dot whatsapp-vinc__dot--off" aria-hidden="true" />
                <span className="whatsapp-vinc__estado-text">
                  No hay número vinculado.
                </span>
              </div>
              <Button
                variant="primary"
                onClick={empezarVinculacion}
                disabled={vinculando}
              >
                {vinculando ? 'Generando QR…' : 'Vincular WhatsApp'}
              </Button>
            </div>
          )}

          {estado === 'PENDIENTE_QR' && (
            <div className="whatsapp-vinc__pending">
              {qrExpirado ? (
                <div className="whatsapp-vinc__expired" role="status">
                  <p>El QR expiró. Vuelve a generarlo para reintentar.</p>
                  <Button
                    variant="primary"
                    onClick={empezarVinculacion}
                    disabled={vinculando}
                  >
                    {vinculando ? 'Generando QR…' : 'Generar nuevo QR'}
                  </Button>
                </div>
              ) : (
                <>
                  <ol className="whatsapp-vinc__steps">
                    <li>Abre WhatsApp en el teléfono de la escuela.</li>
                    <li>
                      Ve a <strong>Dispositivos vinculados</strong> →{' '}
                      <strong>Vincular un dispositivo</strong>.
                    </li>
                    <li>Escanea este código QR.</li>
                  </ol>
                  <div className="whatsapp-vinc__qr">
                    {qr ? (
                      <img
                        src={qr}
                        alt="Código QR para vincular WhatsApp"
                        className="whatsapp-vinc__qr-img"
                        width={240}
                        height={240}
                      />
                    ) : (
                      <div className="whatsapp-vinc__qr-placeholder" role="status">
                        Generando código QR…
                      </div>
                    )}
                  </div>
                  <p className="whatsapp-vinc__hint">
                    Esperando a que escanees el código…
                  </p>
                </>
              )}
            </div>
          )}

          {estado === 'CONECTADA' && (
            <div className="whatsapp-vinc__estado">
              <div className="whatsapp-vinc__estado-row">
                <span className="whatsapp-vinc__dot whatsapp-vinc__dot--on" aria-hidden="true" />
                <span className="whatsapp-vinc__estado-text">
                  Conectado como{' '}
                  <strong className="whatsapp-vinc__numero">
                    {numero ? `+${numero}` : '—'}
                  </strong>
                </span>
              </div>
              {vinculadoEn && (
                <p className="whatsapp-vinc__meta">
                  Vinculado el {formatDate(vinculadoEn)}.
                </p>
              )}
              <Button
                variant="danger"
                onClick={desvincular}
                disabled={desvinculando}
              >
                {desvinculando ? 'Desvinculando…' : 'Desvincular'}
              </Button>
            </div>
          )}

          {actionError && (
            <div className="page-error" role="alert">
              {actionError}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
