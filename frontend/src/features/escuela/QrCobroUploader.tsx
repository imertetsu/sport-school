import { useEffect, useRef, useState } from 'react';
import { api, ApiError, resolveSignedUrl } from '@/api/client';
import { Button, Card, useToast } from '@/components/ui';
import type { QrCobroMeta } from '@/api/types';
import './QrCobroUploader.css';

// QR de cobro de la escuela (epic pagos-qr-comprobante, C6) — SOLO ADMIN. Se monta
// en Ajustes, cuya ruta ya está gateada con RoleRoute allow={['ADMIN']}; el backend
// además impone require_role("ADMIN") y scopea SIEMPRE al org del token (el cliente
// NUNCA manda org_id). 1 fila por org. El QR se sube como imagen y se reenvía tal
// cual en el recordatorio de cobro (no se decodifica). La imagen binaria se sirve
// por URL FIRMADA HMAC stateless: el meta trae `imagen_url` y el <img> la carga
// directo (resolveSignedUrl la hace absoluta si llega relativa). El token de la URL
// se renueva al recargar el meta (subir/cambiar/quitar); por eso no hace falta
// cache-buster. Aquí se gestiona subir/ver/cambiar/quitar.

// Límite de tamaño del archivo (~256 KB). El backend tiene la última palabra.
const MAX_BYTES = 256 * 1024;
const TIPOS_ACEPTADOS = ['image/png', 'image/jpeg'];
const ACCEPT_ATTR = 'image/png,image/jpeg';

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export function QrCobroUploader() {
  const toast = useToast();
  const [meta, setMeta] = useState<QrCobroMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Archivo elegido (aún sin subir) y su preview local (object URL).
  const [archivo, setArchivo] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const [subiendo, setSubiendo] = useState(false);
  const [quitando, setQuitando] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Modo "cambiar": muestra el input aunque ya haya un QR guardado.
  const [cambiando, setCambiando] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  // Carga inicial: GET /qr-cobro/meta.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(null);
    api
      .qrCobroMeta(controller.signal)
      .then((data) => {
        if (active) setMeta(data);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.isForbidden) {
          setLoadError('No tienes permiso para gestionar el QR de cobro.');
        } else {
          setLoadError(
            err instanceof ApiError ? err.message : 'No se pudo cargar el QR de cobro.',
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

  // Limpia el object URL del preview al reemplazarlo o desmontar (evita fugas).
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function elegirArchivo(file: File | null) {
    setActionError(null);
    setFileError(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (!file) {
      setArchivo(null);
      setPreviewUrl(null);
      return;
    }
    if (!TIPOS_ACEPTADOS.includes(file.type)) {
      setArchivo(null);
      setPreviewUrl(null);
      setFileError('Sube una imagen PNG o JPG.');
      return;
    }
    if (file.size > MAX_BYTES) {
      setArchivo(null);
      setPreviewUrl(null);
      setFileError(`La imagen supera el máximo de ${formatBytes(MAX_BYTES)}.`);
      return;
    }
    setArchivo(file);
    setPreviewUrl(URL.createObjectURL(file));
  }

  async function subir() {
    if (!archivo) return;
    setActionError(null);
    setSubiendo(true);
    try {
      const data = await api.subirQrCobro(archivo);
      // `data.imagen_url` ya trae el token renovado -> el <img> se recarga solo.
      setMeta(data);
      // Reset del selector: ya quedó guardado en el backend.
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setArchivo(null);
      setPreviewUrl(null);
      setFileError(null);
      setCambiando(false);
      if (inputRef.current) inputRef.current.value = '';
      toast.success('QR de cobro actualizado');
    } catch (err) {
      let msg: string;
      if (err instanceof ApiError) {
        if (err.isForbidden) {
          msg = 'No tienes permiso para subir el QR de cobro.';
        } else {
          msg = err.message;
        }
      } else {
        msg = 'No se pudo subir el QR. Inténtalo de nuevo.';
      }
      setActionError(msg);
      toast.error(msg);
    } finally {
      setSubiendo(false);
    }
  }

  async function quitar() {
    const ok = window.confirm(
      '¿Quitar el QR de cobro? Los recordatorios de cobro dejarán de adjuntar el QR y volverán al mensaje de texto hasta que subas uno nuevo.',
    );
    if (!ok) return;
    setActionError(null);
    setQuitando(true);
    try {
      const data = await api.eliminarQrCobro();
      setMeta(data);
      setCambiando(false);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setArchivo(null);
      setPreviewUrl(null);
      setFileError(null);
      toast.success('QR de cobro eliminado');
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.isForbidden
            ? 'No tienes permiso para quitar el QR de cobro.'
            : err.message
          : 'No se pudo quitar el QR. Inténtalo de nuevo.';
      setActionError(msg);
      toast.error(msg);
    } finally {
      setQuitando(false);
    }
  }

  function cancelarCambio() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setArchivo(null);
    setPreviewUrl(null);
    setFileError(null);
    setActionError(null);
    setCambiando(false);
    if (inputRef.current) inputRef.current.value = '';
  }

  const tieneQr = meta?.tiene_qr ?? false;
  // El selector se muestra si no hay QR aún, o si el admin pulsó "Cambiar".
  const mostrarSelector = !tieneQr || cambiando;

  const selector = (
    <div className="qr-cobro__uploader">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="qr-cobro__file"
        onChange={(e) => elegirArchivo(e.target.files?.[0] ?? null)}
        aria-label="Imagen del QR de cobro (PNG o JPG)"
      />
      {previewUrl && (
        <div className="qr-cobro__preview">
          <img
            src={previewUrl}
            alt="Vista previa del QR de cobro"
            className="qr-cobro__img"
            width={200}
            height={200}
          />
        </div>
      )}
      {fileError && (
        <p className="field__error" role="alert">
          {fileError}
        </p>
      )}
      <div className="qr-cobro__actions">
        <Button variant="primary" onClick={subir} disabled={!archivo || subiendo}>
          {subiendo ? 'Subiendo…' : 'Subir'}
        </Button>
        {cambiando && (
          <Button variant="ghost" onClick={cancelarCambio} disabled={subiendo}>
            Cancelar
          </Button>
        )}
      </div>
      {!fileError && (
        <p className="field__hint">PNG o JPG, máximo {formatBytes(MAX_BYTES)}.</p>
      )}
    </div>
  );

  return (
    <Card title="QR de cobro" className="qr-cobro">
      <p className="qr-cobro__intro">
        Sube el QR de tu banco o billetera. Se adjunta como imagen en los
        recordatorios de cobro por WhatsApp para que los tutores paguen directo a tu
        escuela. Sin QR, el recordatorio se envía como texto.
      </p>

      {loadError && (
        <div className="page-error" role="alert">
          {loadError}
        </div>
      )}

      {!loadError && loading && <p className="qr-cobro__loading">Cargando…</p>}

      {!loadError && !loading && (
        <div className="qr-cobro__body">
          {tieneQr && !cambiando && meta?.imagen_url && (
            <div className="qr-cobro__current">
              <div className="qr-cobro__preview">
                {/* Binario servido por URL FIRMADA (meta.imagen_url); el <img> la
                    carga directo. resolveSignedUrl la hace absoluta si llega relativa. */}
                <img
                  src={resolveSignedUrl(meta.imagen_url)}
                  alt="QR de cobro de la escuela"
                  className="qr-cobro__img"
                  width={200}
                  height={200}
                />
              </div>
              {meta?.tamano_bytes != null && (
                <p className="qr-cobro__meta">
                  {meta.mime === 'image/png' ? 'PNG' : 'JPG'} · {formatBytes(meta.tamano_bytes)}
                </p>
              )}
              <div className="qr-cobro__actions">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setCambiando(true);
                    setActionError(null);
                  }}
                  disabled={quitando}
                >
                  Cambiar
                </Button>
                <Button variant="danger" onClick={quitar} disabled={quitando}>
                  {quitando ? 'Quitando…' : 'Quitar'}
                </Button>
              </div>
            </div>
          )}

          {mostrarSelector && selector}

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
