import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type {
  EstadoPago,
  MetodoPago,
  PagoListItem,
  WhatsAppEstado,
} from '@/api/types';
import {
  Avatar,
  Badge,
  Button,
  Card,
  DataTable,
  useToast,
  type BadgeTone,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useAuth } from '@/auth/useAuth';
import { formatDate, formatMoney, mesLargo } from '@/lib/format';
import './PanelCobranza.css';
import './Pagos.css';

const PAGE_SIZE = 20;

const METODO_LABEL: Record<MetodoPago, string> = {
  EFECTIVO: 'Efectivo',
  QR: 'QR',
};

// Estado del PAGO (distinto del de la cuota). CONFIRMADO = "Pagado" (verde).
const ESTADO_PAGO: Record<EstadoPago, { label: string; tone: BadgeTone }> = {
  PENDIENTE: { label: 'Pendiente', tone: 'pending' },
  CONFIRMADO: { label: 'Pagado', tone: 'paid' },
  FALLIDO: { label: 'Fallido', tone: 'overdue' },
  ANULADO: { label: 'Anulado', tone: 'neutral' },
};

// Resumen del/los mes(es) que cubrió el pago (para el subtítulo del deportista).
function resumenCuotas(p: PagoListItem): string {
  if (p.cuotas.length === 0) return '—';
  if (p.cuotas.length === 1) {
    const c = p.cuotas[0];
    return `Cuota ${mesLargo(c.vence_el)} ${c.vence_el.slice(0, 4)}`;
  }
  return `${p.cuotas.length} cuotas`;
}

// Texto del comprobante listo para pegar en un chat de WhatsApp (mismo formato
// que el comprobante que se muestra al registrar el pago).
function mensajeWhatsapp(p: PagoListItem, orgNombre: string): string {
  const lineas: (string | null)[] = [
    `🧾 *${orgNombre}* — Comprobante de pago`,
    p.numero_recibo ? `Recibo: ${p.numero_recibo}` : null,
    p.deportista_nombre ? `Deportista: ${p.deportista_nombre}` : null,
    ...p.cuotas.map(
      (c) =>
        `• Cuota ${mesLargo(c.vence_el)} ${c.vence_el.slice(0, 4)} (vence ${formatDate(c.vence_el)})`,
    ),
    `Monto: ${formatMoney(p.monto)}`,
    `Método: ${METODO_LABEL[p.metodo] ?? p.metodo}`,
    '¡Gracias por tu pago! 🙌',
  ];
  return lineas.filter((l): l is string => Boolean(l)).join('\n');
}

async function copiarAlPortapapeles(texto: string) {
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
}

// Acciones por pago: descargar recibo (PDF), copiar el mensaje de WhatsApp para
// pegarlo a mano, y enviar el recibo por WhatsApp (adjunta la imagen del recibo;
// solo ADMIN, requiere el WhatsApp de la escuela vinculado).
function PagoAcciones({
  pago,
  orgNombre,
  isAdmin,
  waEstado,
}: {
  pago: PagoListItem;
  orgNombre: string;
  isAdmin: boolean;
  waEstado: WhatsAppEstado | null;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const [descargando, setDescargando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [enviado, setEnviado] = useState(false);

  // Descarga autenticada del recibo (el endpoint pide Bearer; un <a href> no lo
  // manda). Trae el blob y dispara la descarga.
  async function descargar() {
    setDescargando(true);
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
      toast.error('No se pudo descargar el recibo.');
    } finally {
      setDescargando(false);
    }
  }

  async function copiar() {
    await copiarAlPortapapeles(mensajeWhatsapp(pago, orgNombre));
    toast.success('Mensaje copiado');
  }

  async function enviar() {
    // Sin WhatsApp vinculado no se puede enviar: guiamos a Ajustes.
    if (waEstado !== 'CONECTADA') {
      toast.info('Primero vinculá el WhatsApp de la escuela en Ajustes.');
      navigate('/ajustes');
      return;
    }
    setEnviando(true);
    try {
      const res = await api.enviarComprobanteWhatsapp(pago.id);
      if (res.enviado) {
        setEnviado(true);
        toast.success('Recibo enviado por WhatsApp');
      } else if (res.motivo === 'sin_telefono') {
        toast.error('El tutor no tiene un teléfono registrado.');
      } else if (res.motivo === 'sin_whatsapp') {
        toast.error(
          'El número del tutor no está en WhatsApp (o está mal escrito). Revisá el teléfono del tutor responsable.',
        );
      } else {
        toast.error(`No se pudo enviar${res.detalle ? ` (${res.detalle})` : ''}.`);
      }
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.isForbidden
          ? 'No tenés permiso para enviar.'
          : 'No se pudo enviar por WhatsApp.',
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="pago-acciones">
      <Button variant="ghost" size="sm" onClick={descargar} disabled={descargando}>
        {descargando ? 'Generando…' : 'Recibo'}
      </Button>
      <Button variant="ghost" size="sm" onClick={copiar}>
        Copiar
      </Button>
      {isAdmin && (
        <Button
          variant="ghost"
          size="sm"
          onClick={enviar}
          disabled={enviando || enviado}
          title="Enviar el recibo al tutor por WhatsApp"
        >
          {enviado ? '✓ Enviado' : enviando ? 'Enviando…' : 'Enviar WhatsApp'}
        </Button>
      )}
    </div>
  );
}

// "Pagos": lista de pagos registrados, ordenada por fecha y hora de REGISTRO
// (created_at DESC, lo impone el backend). Cada fila muestra su fecha de pago y
// ofrece descargar el recibo, copiar el mensaje de WhatsApp o enviarlo.
export function PagosHistorial() {
  const { selected: sucursalId } = useSucursales();
  const { org, viewRole } = useAuth();
  const isAdmin = viewRole === 'ADMIN';
  const orgNombre = org?.nombre ?? 'LATINOSPORT';

  const [items, setItems] = useState<PagoListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Estado del WhatsApp de la escuela (para habilitar "Enviar"); solo ADMIN.
  const [waEstado, setWaEstado] = useState<WhatsAppEstado | null>(null);

  // Al cambiar de sucursal, volvemos a la primera página.
  useEffect(() => {
    setPage(1);
  }, [sucursalId]);

  useEffect(() => {
    if (!isAdmin) return;
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
  }, [isAdmin]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listarPagos(page, PAGE_SIZE, sucursalId || undefined, controller.signal)
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los pagos');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId, page]);

  const columns = useMemo<Column<PagoListItem>[]>(
    () => [
      {
        key: 'deportista',
        header: 'Deportista',
        render: (p) => (
          <div className="cuota-cell">
            <Avatar name={p.deportista_nombre ?? '—'} size="md" />
            <div className="cuota-cell__text">
              <span className="cuota-cell__name">{p.deportista_nombre ?? '—'}</span>
              <span className="cuota-cell__meta">{resumenCuotas(p)}</span>
            </div>
          </div>
        ),
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        hideOnNarrow: true,
        render: (p) => p.sucursal_nombre ?? '—',
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        render: (p) => {
          const e = ESTADO_PAGO[p.estado] ?? { label: p.estado, tone: 'neutral' as BadgeTone };
          return <Badge tone={e.tone}>{e.label}</Badge>;
        },
      },
      {
        key: 'monto',
        header: 'Monto',
        align: 'right',
        render: (p) => <span className="tabular">{formatMoney(p.monto)}</span>,
      },
      {
        key: 'fecha',
        header: 'Fecha de pago',
        render: (p) => formatDate(p.fecha),
      },
      {
        key: 'metodo',
        header: 'Método',
        render: (p) => METODO_LABEL[p.metodo] ?? p.metodo,
      },
      {
        key: 'numero_recibo',
        header: 'N° recibo',
        hideOnNarrow: true,
        render: (p) => <span className="tabular">{p.numero_recibo ?? '—'}</span>,
      },
      {
        key: 'acciones',
        header: '',
        align: 'right',
        render: (p) => (
          <PagoAcciones
            pago={p}
            orgNombre={orgNombre}
            isAdmin={isAdmin}
            waEstado={waEstado}
          />
        ),
      },
    ],
    [orgNombre, isAdmin, waEstado],
  );

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="panel-cobranza">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Pagos</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} pago${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`}
          </p>
        </div>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Historial de pagos"
          columns={columns}
          rows={items}
          rowKey={(p) => p.id}
          loading={loading}
          emptyMessage="Aún no hay pagos registrados"
        />
      </Card>

      {total > PAGE_SIZE && (
        <div className="pagos-lista__pager">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Anterior
          </Button>
          <span>
            Página {page} de {lastPage}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= lastPage || loading}
            onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
          >
            Siguiente
          </Button>
        </div>
      )}
    </div>
  );
}
