import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type {
  CuotaListItem,
  PagoOut,
  RegistrarPagoEfectivoBody,
  WhatsAppEstado,
} from '@/api/types';
import { useAuth } from '@/auth/useAuth';
import { Badge, Button, Card, EstadoBadge, Field, useToast } from '@/components/ui';
import { formatDate, formatMoney, mesLargo } from '@/lib/format';
import './RegistrarPago.css';

// Fecha de HOY en formato YYYY-MM-DD (local): default del campo "Fecha de pago".
function hoyISO(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export interface RegistrarPagoProps {
  // Cuota preseleccionada al abrir desde una fila; null = elegir deportista + cuota(s).
  cuotaInicial?: CuotaListItem | null;
  onClose: () => void;
  // Se invoca cuando un pago queda CONFIRMADO (refresca panel/tabla).
  onConfirmado?: () => void;
}

export function RegistrarPago({ cuotaInicial, onClose, onConfirmado }: RegistrarPagoProps) {
  // Nombre de la escuela (login C1) para el mensaje de WhatsApp del comprobante.
  const { org } = useAuth();
  // --- Selección de deportista + cuotas ---
  const [busqueda, setBusqueda] = useState('');
  const [cuotasDeportista, setCuotasDeportista] = useState<CuotaListItem[]>([]);
  const [cargandoCuotas, setCargandoCuotas] = useState(false);
  // Cuota(s) elegida(s) para cobrar (ids).
  const [seleccion, setSeleccion] = useState<string[]>(
    cuotaInicial ? [cuotaInicial.id] : [],
  );
  // Catálogo de cuotas conocidas (para resolver monto/etiqueta por id).
  const [catalogo, setCatalogo] = useState<CuotaListItem[]>(
    cuotaInicial ? [cuotaInicial] : [],
  );
  // Fuerza recargar la lista de cuotas tras un pago (para que las ya cobradas
  // desaparezcan) y remontar el formulario de pago para "Registrar otro pago".
  const [reloadKey, setReloadKey] = useState(0);
  const [formKey, setFormKey] = useState(0);

  // "Registrar otro pago": vuelve del comprobante al formulario SIN cerrar el
  // modal. Limpia la selección, refresca la lista (quita lo ya cobrado) y remonta
  // PagoManual (con key) para descartar el comprobante y resetear su formulario.
  function reiniciarParaOtroPago() {
    setSeleccion([]);
    setReloadKey((k) => k + 1);
    setFormKey((k) => k + 1);
  }

  // Cargar cuotas pendientes del deportista de la cuota inicial (para multi-cuota).
  useEffect(() => {
    if (!cuotaInicial) return;
    const controller = new AbortController();
    let active = true;
    setCargandoCuotas(true);
    api
      .cuotas(
        { deportista_id: cuotaInicial.deportista.id, page: 1, page_size: 50 },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        // Solo cobrables (no PAGADO). Mantén la inicial aunque venga filtrada,
        // salvo tras un pago (reloadKey>0): ahí, si ya quedó pagada, no la
        // re-agregamos (evita mostrar como cobrable una cuota ya saldada).
        const cobrables = res.items.filter((c) => c.estado !== 'PAGADO');
        const inicialSaldada = res.items.some(
          (c) => c.id === cuotaInicial.id && c.estado === 'PAGADO',
        );
        const merged =
          cobrables.some((c) => c.id === cuotaInicial.id) || (reloadKey > 0 && inicialSaldada)
            ? cobrables
            : [cuotaInicial, ...cobrables];
        setCuotasDeportista(merged);
        setCatalogo(merged);
      })
      .catch(() => {
        if (active) setCuotasDeportista(reloadKey > 0 ? [] : [cuotaInicial]);
      })
      .finally(() => {
        if (active) setCargandoCuotas(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [cuotaInicial, reloadKey]);

  // Búsqueda de cuotas por nombre de deportista cuando se abre sin cuota inicial.
  useEffect(() => {
    if (cuotaInicial) return;
    const q = busqueda.trim();
    if (!q) {
      setCuotasDeportista([]);
      return;
    }
    const controller = new AbortController();
    let active = true;
    const t = setTimeout(() => {
      setCargandoCuotas(true);
      api
        .cuotas({ page: 1, page_size: 100 }, controller.signal)
        .then((res) => {
          if (!active) return;
          const cobrables = res.items.filter(
            (c) =>
              c.estado !== 'PAGADO' &&
              c.deportista.nombre_completo.toLowerCase().includes(q.toLowerCase()),
          );
          setCuotasDeportista(cobrables);
          setCatalogo((prev) => {
            const byId = new Map(prev.map((c) => [c.id, c]));
            for (const c of cobrables) byId.set(c.id, c);
            return [...byId.values()];
          });
        })
        .catch(() => {
          if (active) setCuotasDeportista([]);
        })
        .finally(() => {
          if (active) setCargandoCuotas(false);
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(t);
      controller.abort();
    };
  }, [busqueda, cuotaInicial, reloadKey]);

  const catalogoById = useMemo(
    () => new Map(catalogo.map((c) => [c.id, c])),
    [catalogo],
  );

  // RF-ABO-11: un pago aplica a cuotas de UNA sola inscripción/deportista (el crédito
  // es por inscripción). El deportista de la selección actual ancla qué se puede sumar.
  const deportistaSeleccionadoId = useMemo(() => {
    for (const id of seleccion) {
      const c = catalogoById.get(id);
      if (c) return c.deportista.id;
    }
    return null;
  }, [seleccion, catalogoById]);

  const toggleCuota = useCallback(
    (cuota: CuotaListItem) => {
      setSeleccion((prev) => {
        if (prev.includes(cuota.id)) {
          return prev.filter((x) => x !== cuota.id);
        }
        // Si ya hay selección de otro deportista, la reemplazamos (no se mezclan deportistas).
        const ancla = prev
          .map((id) => catalogoById.get(id))
          .find((c): c is CuotaListItem => c != null);
        if (ancla && ancla.deportista.id !== cuota.deportista.id) {
          return [cuota.id];
        }
        return [...prev, cuota.id];
      });
    },
    [catalogoById],
  );

  // Total a cobrar = Σ SALDO de lo seleccionado (Abonos: el saldo es lo que falta).
  const saldoTotal = useMemo(() => {
    return seleccion.reduce((sum, id) => {
      const c = catalogoById.get(id);
      return sum + (c ? Number(c.saldo) : 0);
    }, 0);
  }, [seleccion, catalogoById]);

  const listaCuotas = cuotasDeportista;

  // Cuotas efectivamente seleccionadas (para el comprobante / mensaje de WhatsApp).
  const cuotasSeleccionadas = seleccion
    .map((id) => catalogoById.get(id))
    .filter((c): c is CuotaListItem => c != null);
  const deportistaNombre =
    cuotasSeleccionadas[0]?.deportista.nombre_completo ?? cuotaInicial?.deportista.nombre_completo ?? null;
  const deportistaId =
    cuotasSeleccionadas[0]?.deportista.id ?? cuotaInicial?.deportista.id ?? null;

  const selector = (
    <div className="rp-selector">
      {!cuotaInicial && (
        <label className="rp-search">
          <span className="rp-search__label">Deportista</span>
          <input
            className="field__input"
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar deportista…"
            autoFocus
          />
        </label>
      )}
      {cuotaInicial && (
        <p className="rp-deportista">
          <strong>{cuotaInicial.deportista.nombre_completo}</strong>
          <span className="rp-deportista__meta">
            {cuotaInicial.categoria?.nombre ?? 'Sin categoría'} · {cuotaInicial.sucursal?.nombre ?? '—'}
          </span>
        </p>
      )}

      <span className="rp-section-label">Cuota(s) a cobrar</span>
      {cargandoCuotas ? (
        <p className="rp-empty">Buscando…</p>
      ) : listaCuotas.length === 0 ? (
        <p className="rp-empty">
          {cuotaInicial || busqueda.trim()
            ? 'Sin cuotas por cobrar.'
            : 'Escribe el nombre de un deportista.'}
        </p>
      ) : (
        <ul className="rp-cuotas">
          {listaCuotas.map((c) => {
            // RF-ABO-11: solo cuotas del deportista ya anclado son combinables.
            const bloqueada =
              deportistaSeleccionadoId != null && c.deportista.id !== deportistaSeleccionadoId;
            return (
              <li key={c.id}>
                <label
                  className={`rp-cuota${bloqueada ? ' rp-cuota--disabled' : ''}`}
                  title={
                    bloqueada
                      ? 'Solo puedes cobrar cuotas de un mismo deportista por pago.'
                      : undefined
                  }
                >
                  <input
                    type="checkbox"
                    checked={seleccion.includes(c.id)}
                    onChange={() => toggleCuota(c)}
                    disabled={bloqueada}
                  />
                  <span className="rp-cuota__body">
                    <span className="rp-cuota__top">
                      {!cuotaInicial && (
                        <span className="rp-cuota__deportista">{c.deportista.nombre_completo}</span>
                      )}
                      <EstadoBadge estado={c.estado} />
                    </span>
                    {/* La cuota se etiqueta por el MES en que vence (DICIEMBRE 2025),
                        junto a la fecha exacta de vencimiento. La disciplina distingue
                        cuotas del mismo mes de un deportista multi-disciplina. */}
                    <span className="rp-cuota__meta">
                      Cuota {mesLargo(c.vence_el)} {c.vence_el.slice(0, 4)} | Vence{' '}
                      {formatDate(c.vence_el)}
                      {c.disciplina ? ` | ${c.disciplina}` : ''}
                    </span>
                  </span>
                  <span className="rp-cuota__monto tabular">{formatMoney(c.saldo)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}

      <div className="rp-total">
        <span>Total a cobrar</span>
        <span className="rp-total__monto tabular">{formatMoney(saldoTotal)}</span>
      </div>
    </div>
  );

  return (
    <div className="rp-overlay" role="dialog" aria-modal="true" aria-label="Registrar pago">
      <div className="rp-modal">
        <header className="rp-modal__head">
          <h2 className="rp-modal__title">Registrar pago</h2>
          <button
            type="button"
            className="rp-modal__close"
            aria-label="Cerrar"
            onClick={onClose}
          >
            ✕
          </button>
        </header>
        <div className="rp-modal__body">
          {selector}
          <PagoManual
            key={formKey}
            cuotaIds={seleccion}
            saldoTotal={saldoTotal}
            cuotasSeleccionadas={cuotasSeleccionadas}
            deportistaNombre={deportistaNombre}
            deportistaId={deportistaId}
            orgNombre={org?.nombre ?? 'LATINOSPORT'}
            onConfirmado={onConfirmado}
            onOtroPago={reiniciarParaOtroPago}
            onCerrar={onClose}
          />
        </div>
      </div>
    </div>
  );
}

// --- Pago manual: método (efectivo/QR) + fecha + monto; confirma y muestra comprobante ---
function PagoManual({
  cuotaIds,
  saldoTotal,
  cuotasSeleccionadas,
  deportistaNombre,
  deportistaId,
  orgNombre,
  onConfirmado,
  onOtroPago,
  onCerrar,
}: {
  cuotaIds: string[];
  // Σ saldo de lo seleccionado: default del "Monto recibido" (Abonos).
  saldoTotal: number;
  cuotasSeleccionadas: CuotaListItem[];
  deportistaNombre: string | null;
  deportistaId: string | null;
  orgNombre: string;
  onConfirmado?: () => void;
  // Vuelve al formulario para cobrar otra cuota / a otro deportista (sin cerrar).
  onOtroPago: () => void;
  // Cierra el modal por completo.
  onCerrar: () => void;
}) {
  const toast = useToast();
  const [pago, setPago] = useState<PagoOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Método del pago manual: efectivo o QR/transferencia (solo etiqueta; mismo flujo).
  const [metodo, setMetodo] = useState<'EFECTIVO' | 'QR'>('EFECTIVO');
  // Fecha real del pago: por defecto hoy, editable (permite cargar meses viejos).
  const [fechaPago, setFechaPago] = useState<string>(hoyISO());
  // "Monto recibido" en caja. Vacío => paga el total (Σ saldo). El backend
  // distribuye FIFO y guarda el sobrepago como crédito de la inscripción.
  const [montoRecibido, setMontoRecibido] = useState('');
  // Confirmación explícita del sobrepago: al pagar de más, pedir un OK antes de
  // generar saldo a favor (evita el error de tipear de más sin querer).
  const [confirmarSobrepago, setConfirmarSobrepago] = useState(false);

  const recibidoNum = montoRecibido.trim() === '' ? null : Number(montoRecibido);
  const recibidoInvalido =
    recibidoNum !== null && (Number.isNaN(recibidoNum) || recibidoNum <= 0);
  // Sobrepago que iría a crédito (preview; el backend tiene la última palabra).
  const excedente =
    recibidoNum !== null && !recibidoInvalido && recibidoNum > saldoTotal
      ? recibidoNum - saldoTotal
      : 0;
  const parcial =
    recibidoNum !== null && !recibidoInvalido && recibidoNum < saldoTotal;

  async function confirmar() {
    if (cuotaIds.length === 0 || recibidoInvalido || !fechaPago) return;
    // Sobrepago: exigir confirmación explícita antes de generar saldo a favor.
    if (excedente > 0 && !confirmarSobrepago) {
      setConfirmarSobrepago(true);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body: RegistrarPagoEfectivoBody = {
        cuota_ids: cuotaIds,
        metodo,
        fecha_pago: fechaPago,
      };
      // Vacío o igual al total => omitimos monto_recibido (camino "paga todo"
      // intacto). Solo lo mandamos cuando el operador escribió un valor distinto.
      if (recibidoNum !== null && recibidoNum !== saldoTotal) {
        body.monto_recibido = montoRecibido.trim();
      }
      const res = await api.pagoEfectivo(body);
      setPago(res);
      toast.success('Pago registrado');
      onConfirmado?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'No se pudo registrar el pago.';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  if (pago) {
    return (
      <Comprobante
        pago={pago}
        cuotas={cuotasSeleccionadas}
        deportistaNombre={deportistaNombre}
        deportistaId={deportistaId}
        orgNombre={orgNombre}
        metodo={metodo}
        onOtroPago={onOtroPago}
        onCerrar={onCerrar}
      />
    );
  }

  return (
    <div className="rp-method">
      <p className="rp-method__hint">
        Registra el cobro. Se aplicará a la(s) cuota(s) seleccionada(s) y se generará el
        comprobante.
      </p>

      <div className="rp-metodo">
        <span className="rp-section-label">Método de pago</span>
        <div className="rp-metodo__opts" role="radiogroup" aria-label="Método de pago">
          {(['EFECTIVO', 'QR'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={metodo === m}
              className={`rp-metodo__opt${metodo === m ? ' is-active' : ''}`}
              onClick={() => setMetodo(m)}
            >
              {m === 'EFECTIVO' ? 'Efectivo' : 'QR'}
            </button>
          ))}
        </div>
      </div>

      <Field
        type="date"
        label="Fecha de pago"
        value={fechaPago}
        max={hoyISO()}
        onChange={(e) => setFechaPago(e.target.value)}
        hint="Por defecto hoy. Cámbiala si el pago fue en otra fecha."
      />

      <Field
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        label="Monto recibido"
        value={montoRecibido}
        onChange={(e) => {
          setMontoRecibido(e.target.value);
          setConfirmarSobrepago(false);
        }}
        placeholder={saldoTotal > 0 ? String(saldoTotal) : '0'}
        error={recibidoInvalido ? 'Ingresa un monto mayor a 0.' : undefined}
        hint={
          recibidoInvalido
            ? undefined
            : excedente > 0
              ? `Sobrepago: ${formatMoney(excedente)} quedará como crédito a favor.`
              : parcial
                ? 'Pago parcial: el saldo restante queda pendiente.'
                : 'Vacío = cobrar el total seleccionado.'
        }
      />
      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}
      {confirmarSobrepago ? (
        <div className="rp-sobrepago" role="alert">
          <p className="rp-sobrepago__msg">
            ⚠️ Estás registrando <strong>{formatMoney(excedente)} de más</strong> sobre el
            total a cobrar. Ese excedente quedará como <strong>saldo a favor</strong> del
            deportista. Si fue un error, revisá el monto.
          </p>
          <div className="rp-sobrepago__actions">
            <Button
              variant="secondary"
              onClick={() => setConfirmarSobrepago(false)}
              disabled={submitting}
            >
              Revisar monto
            </Button>
            <Button variant="primary" onClick={confirmar} disabled={submitting}>
              {submitting ? 'Registrando…' : 'Registrar de todas formas'}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="primary"
          onClick={confirmar}
          disabled={submitting || cuotaIds.length === 0 || recibidoInvalido || !fechaPago}
        >
          {submitting ? 'Registrando…' : 'Confirmar pago'}
        </Button>
      )}
    </div>
  );
}

// --- Comprobante: descarga PDF (autenticada) + copiar mensaje para WhatsApp ---
function Comprobante({
  pago,
  cuotas,
  deportistaNombre,
  deportistaId,
  orgNombre,
  metodo,
  onOtroPago,
  onCerrar,
}: {
  pago: PagoOut;
  // Cuotas cobradas (con mes/vencimiento) para el texto de WhatsApp.
  cuotas: CuotaListItem[];
  deportistaNombre: string | null;
  deportistaId: string | null;
  orgNombre: string;
  metodo: 'EFECTIVO' | 'QR';
  onOtroPago: () => void;
  onCerrar: () => void;
}) {
  const navigate = useNavigate();
  const [pdfEnVuelo, setPdfEnVuelo] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);
  // Tutor responsable de pago (destinatario) — solo para el aviso "se enviará a …".
  const [tutorNombre, setTutorNombre] = useState<string | null>(null);
  // Estado del WhatsApp de la escuela: decide si se puede ENVIAR o hay que VINCULAR.
  const [waEstado, setWaEstado] = useState<WhatsAppEstado | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [envioOk, setEnvioOk] = useState(false);
  const [envioError, setEnvioError] = useState<string | null>(null);
  const aplicaciones = pago.cuotas_aplicadas ?? [];

  // Nombre del tutor responsable (para mostrar a quién se enviará el recibo).
  useEffect(() => {
    if (!deportistaId) return;
    const controller = new AbortController();
    let active = true;
    api
      .deportista(deportistaId, controller.signal)
      .then((d) => {
        if (!active) return;
        const conTel = d.tutores.filter((t) => t.telefono && t.telefono.trim());
        const elegido = conTel.find((t) => t.responsable_pago) ?? conTel[0] ?? null;
        if (elegido) setTutorNombre(elegido.nombres);
      })
      .catch(() => {
        /* el nombre del tutor es informativo; su ausencia no bloquea el envío */
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [deportistaId]);

  // Estado de la sesión de WhatsApp de la escuela (enviar vs vincular).
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api
      .whatsappEstado(controller.signal)
      .then((e) => {
        if (active) setWaEstado(e.estado);
      })
      .catch(() => {
        if (active) setWaEstado(null);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const creditoAplicado = Number(pago.credito_aplicado ?? 0);
  const creditoGenerado = Number(pago.credito_generado ?? 0);
  // ¿Quedó algo a medias? (saldo restante > 0 en alguna cuota → estado PARCIAL).
  const hayParcial = aplicaciones.some(
    (c) => c.estado === 'PARCIAL' || Number(c.saldo_restante) > 0,
  );

  // Descarga el PDF con el token Bearer: el endpoint es autenticado y un <a href>
  // simple NO manda el header (daba 401). Trae el blob y dispara la descarga.
  async function descargarPdf() {
    setPdfEnVuelo(true);
    setPdfError(null);
    try {
      const url = await api.comprobantePdfUrl(pago.id);
      const a = document.createElement('a');
      a.href = url;
      a.download = `recibo-${pago.numero_recibo ?? pago.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setPdfError('No se pudo descargar el PDF.');
    } finally {
      setPdfEnVuelo(false);
    }
  }

  // Texto listo para pegar en un chat de WhatsApp.
  function mensajeWhatsapp(): string {
    const lineas: (string | null)[] = [
      `🧾 *${orgNombre}* — Comprobante de pago`,
      pago.numero_recibo ? `Recibo: ${pago.numero_recibo}` : null,
      deportistaNombre ? `Deportista: ${deportistaNombre}` : null,
      ...cuotas.map(
        (c) =>
          `• Cuota ${mesLargo(c.vence_el)} ${c.vence_el.slice(0, 4)} (vence ${formatDate(c.vence_el)})`,
      ),
      `Monto: ${formatMoney(pago.monto)}`,
      `Método: ${metodo === 'EFECTIVO' ? 'Efectivo' : 'QR'}`,
      '¡Gracias por tu pago! 🙌',
    ];
    return lineas.filter((l): l is string => Boolean(l)).join('\n');
  }

  async function copiarMensaje() {
    const texto = mensajeWhatsapp();
    try {
      await navigator.clipboard.writeText(texto);
    } catch {
      // Fallback (navegador sin Clipboard API o contexto no seguro).
      const ta = document.createElement('textarea');
      ta.value = texto;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
      } catch {
        /* si tampoco funciona, no rompemos la UI */
      }
      ta.remove();
    }
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2500);
  }

  // Envía el recibo (imagen) + mensaje al tutor responsable DESDE el servidor, por el
  // WhatsApp vinculado de la escuela. El backend resuelve el número y arma la imagen.
  async function enviarWhatsapp() {
    setEnviando(true);
    setEnvioError(null);
    try {
      const res = await api.enviarComprobanteWhatsapp(pago.id);
      if (res.enviado) {
        setEnvioOk(true);
      } else if (res.motivo === 'sin_telefono') {
        setEnvioError('El tutor no tiene un teléfono registrado.');
      } else if (res.motivo === 'sin_whatsapp') {
        setEnvioError(
          'El número del tutor no está en WhatsApp (o está mal escrito). Revisá el teléfono del tutor responsable.',
        );
      } else if (res.motivo === 'error_envio') {
        setEnvioError(
          `No se pudo enviar por WhatsApp${res.detalle ? ` (${res.detalle})` : ''}. Reintentá; si persiste, revisá que el WhatsApp de la escuela siga vinculado.`,
        );
      } else {
        setEnvioError('No se pudo enviar el comprobante.');
      }
    } catch (err) {
      setEnvioError(
        err instanceof ApiError && err.isForbidden
          ? 'No tenés permiso para enviar.'
          : 'No se pudo enviar por WhatsApp.',
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="rp-comprobante">
      <Card>
        <div className="rp-comprobante__head">
          <Badge tone={hayParcial ? 'pending' : 'paid'}>
            {hayParcial ? 'Pago parcial registrado' : '✓ Pago registrado'}
          </Badge>
          <span className="rp-comprobante__monto tabular">{formatMoney(pago.monto)}</span>
        </div>
        {pago.numero_recibo && (
          <p className="rp-comprobante__recibo">Recibo {pago.numero_recibo}</p>
        )}
        <p className="rp-comprobante__text">
          Comprobante generado. Envialo al tutor por WhatsApp, descargá el PDF o copiá el
          mensaje.
        </p>

        {aplicaciones.length > 0 && (
          <ul className="rp-aplicaciones">
            {aplicaciones.map((c) => (
              <li key={c.cuota_id} className="rp-aplicacion">
                <span className="rp-aplicacion__top">
                  <EstadoBadge estado={c.estado} />
                  <span className="rp-aplicacion__aplicado tabular">
                    {formatMoney(c.monto_aplicado)}
                  </span>
                </span>
                {Number(c.saldo_restante) > 0 && (
                  <span className="rp-aplicacion__saldo tabular">
                    Saldo restante: {formatMoney(c.saldo_restante)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}

        {(creditoAplicado > 0 || creditoGenerado > 0) && (
          <div className="rp-credito">
            {creditoAplicado > 0 && (
              <p className="rp-credito__line">
                <span>Crédito aplicado</span>
                <span className="tabular">−{formatMoney(creditoAplicado)}</span>
              </p>
            )}
            {creditoGenerado > 0 && (
              <p className="rp-credito__line rp-credito__line--favor">
                <span>Saldo a favor generado</span>
                <span className="tabular">{formatMoney(creditoGenerado)}</span>
              </p>
            )}
          </div>
        )}

        {pdfError && (
          <div className="page-error" role="alert">
            {pdfError}
          </div>
        )}
        {envioError && (
          <div className="page-error" role="alert">
            {envioError}
          </div>
        )}

        <div className="rp-comprobante__actions">
          {/* Enviar directo por el WhatsApp de la escuela SOLO si está vinculado; si no,
              el botón lleva a Ajustes a vincular. PDF y Copiar son el respaldo. */}
          {waEstado === 'CONECTADA' ? (
            <Button
              variant="primary"
              onClick={enviarWhatsapp}
              disabled={enviando || envioOk}
            >
              {envioOk ? '✓ Enviado' : enviando ? 'Enviando…' : 'Enviar WhatsApp'}
            </Button>
          ) : (
            <Button variant="primary" onClick={() => navigate('/ajustes')}>
              Vincular WhatsApp
            </Button>
          )}
          <Button variant="secondary" onClick={descargarPdf} disabled={pdfEnVuelo}>
            {pdfEnVuelo ? 'Generando…' : 'Descargar PDF'}
          </Button>
          <Button variant="ghost" onClick={copiarMensaje}>
            {copiado ? '✓ Mensaje copiado' : 'Copiar mensaje'}
          </Button>
        </div>

        {waEstado === 'CONECTADA' && tutorNombre && !envioOk && (
          <p className="rp-comprobante__text">
            Se enviará el recibo a <strong>{tutorNombre}</strong> (tutor responsable).
          </p>
        )}
        {waEstado != null && waEstado !== 'CONECTADA' && (
          <p className="rp-comprobante__text">
            Para enviar por WhatsApp, primero <strong>vinculá el número de la escuela</strong> en
            Ajustes. Mientras tanto podés descargar el PDF o copiar el mensaje.
          </p>
        )}

        {/* Siguiente paso: cobrar otra cuota / a otro deportista SIN cerrar y
            reabrir, o terminar. Resuelve el "se queda trabado en el comprobante". */}
        <div className="rp-comprobante__next">
          <Button variant="primary" onClick={onOtroPago}>
            Registrar otro pago
          </Button>
          <Button variant="ghost" onClick={onCerrar}>
            Cerrar
          </Button>
        </div>
      </Card>
    </div>
  );
}
