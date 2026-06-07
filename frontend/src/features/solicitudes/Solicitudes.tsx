import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { EstadoSolicitud, SolicitudOut } from '@/api/types';
import { Badge, Button, Card, DataTable, SelectField } from '@/components/ui';
import type { BadgeTone, Column } from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useAuth } from '@/auth/useAuth';
import { formatDate } from '@/lib/format';
import { NuevaSolicitud } from './NuevaSolicitud';
import { AprobarSolicitud } from './AprobarSolicitud';
import { RechazarSolicitud } from './RechazarSolicitud';
import './Solicitudes.css';

const PAGE_SIZE = 20;

const ESTADO_OPCIONES: { value: EstadoSolicitud | ''; label: string }[] = [
  { value: 'PENDIENTE', label: 'Pendientes' },
  { value: 'APROBADA', label: 'Aprobadas' },
  { value: 'RECHAZADA', label: 'Rechazadas' },
  { value: '', label: 'Todas' },
];

const ESTADO_BADGE: Record<EstadoSolicitud, { tone: BadgeTone; label: string }> = {
  PENDIENTE: { tone: 'pending', label: 'Pendiente' },
  APROBADA: { tone: 'paid', label: 'Aprobada' },
  RECHAZADA: { tone: 'overdue', label: 'Rechazada' },
};

// Cola de solicitudes de auto-registro (versión EN SISTEMA, dentro del shell).
// Visible a ADMIN y ENTRENADOR. El backend filtra el alcance por rol; las
// acciones de aprobar/rechazar solo las muestra la UI a ADMIN (y el backend las
// exige). El entrenador solo lee y captura nuevas solicitudes.
export function Solicitudes() {
  const { sucursales } = useSucursales();
  // viewRole es la verdad de la UI; el backend impone los permisos reales.
  const { viewRole } = useAuth();
  const isAdmin = viewRole === 'ADMIN';

  const [items, setItems] = useState<SolicitudOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [estado, setEstado] = useState<EstadoSolicitud | ''>('PENDIENTE');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modales: alta / aprobar / rechazar.
  const [nuevaOpen, setNuevaOpen] = useState(false);
  const [aprobando, setAprobando] = useState<SolicitudOut | null>(null);
  const [rechazando, setRechazando] = useState<SolicitudOut | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Cambiar el filtro vuelve a la primera página.
  useEffect(() => {
    setPage(1);
  }, [estado]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .solicitudes(
        { estado: estado || undefined, page, page_size: PAGE_SIZE },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(
          err instanceof ApiError ? err.message : 'No se pudieron cargar las solicitudes',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [estado, page, reloadKey]);

  function recargar() {
    setPage(1);
    setReloadKey((k) => k + 1);
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns: Column<SolicitudOut>[] = [
    {
      key: 'deportista',
      header: 'Deportista',
      render: (s) => (
        <div className="solicitudes__deportista">
          <span className="solicitudes__nombre">
            {`${s.ap_paterno} ${s.ap_materno}, ${s.nombres}`.trim()}
          </span>
          <span className="solicitudes__sub">
            CI {s.ci || '—'} · {s.disciplina}
          </span>
        </div>
      ),
    },
    {
      key: 'tutor',
      header: 'Tutor',
      hideOnNarrow: true,
      render: (s) => (
        <div className="solicitudes__deportista">
          <span>{s.tutor.nombres}</span>
          <span className="solicitudes__sub">
            {s.tutor.telefono || '—'} · {s.tutor.parentesco || '—'}
          </span>
        </div>
      ),
    },
    {
      key: 'sugerencia',
      header: 'Sugerida',
      hideOnNarrow: true,
      render: (s) =>
        s.sucursal_sugerida ? (
          <span>
            {s.sucursal_sugerida.nombre}
            {s.categoria_sugerida ? ` · ${s.categoria_sugerida.nombre}` : ''}
          </span>
        ) : (
          <span className="solicitudes__sub">—</span>
        ),
    },
    {
      key: 'creado',
      header: 'Capturado',
      hideOnNarrow: true,
      render: (s) => (
        <div className="solicitudes__deportista">
          <span>{formatDate(s.created_at)}</span>
          {s.creado_por_nombre && (
            <span className="solicitudes__sub">por {s.creado_por_nombre}</span>
          )}
        </div>
      ),
    },
    {
      key: 'estado',
      header: 'Estado',
      render: (s) => {
        const b = ESTADO_BADGE[s.estado];
        return (
          <div className="solicitudes__estado">
            <Badge tone={b.tone}>{b.label}</Badge>
            {s.estado === 'RECHAZADA' && s.motivo_rechazo && (
              <span className="solicitudes__sub" title={s.motivo_rechazo}>
                {s.motivo_rechazo}
              </span>
            )}
          </div>
        );
      },
    },
    {
      key: 'acciones',
      header: '',
      align: 'right',
      render: (s) =>
        isAdmin && s.estado === 'PENDIENTE' ? (
          <div className="solicitudes__acciones">
            <Button variant="primary" size="sm" onClick={() => setAprobando(s)}>
              Aprobar
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setRechazando(s)}>
              Rechazar
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="solicitudes">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Solicitudes</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} solicitud${total === 1 ? '' : 'es'}${
                  estado ? ` · ${ESTADO_OPCIONES.find((o) => o.value === estado)?.label}` : ''
                }`}
          </p>
        </div>
        <Button variant="primary" onClick={() => setNuevaOpen(true)}>
          + Nueva solicitud
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <div className="solicitudes__filtros">
        <SelectField
          label="Estado"
          value={estado}
          onChange={(e) => setEstado(e.target.value as EstadoSolicitud | '')}
        >
          {ESTADO_OPCIONES.map((o) => (
            <option key={o.value || 'todas'} value={o.value}>
              {o.label}
            </option>
          ))}
        </SelectField>
      </div>

      <Card padded={false}>
        <DataTable
          columns={columns}
          rows={items}
          rowKey={(s) => s.id}
          loading={loading}
          ariaLabel="Cola de solicitudes"
          emptyMessage="No hay solicitudes con este filtro."
        />
      </Card>

      {total > PAGE_SIZE && (
        <div className="solicitudes__pager">
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

      {nuevaOpen && (
        <NuevaSolicitud
          sucursales={sucursales}
          onClose={() => setNuevaOpen(false)}
          onSaved={() => {
            setNuevaOpen(false);
            recargar();
          }}
        />
      )}

      {aprobando && (
        <AprobarSolicitud
          solicitud={aprobando}
          sucursales={sucursales}
          onClose={() => setAprobando(null)}
          onApproved={() => {
            setAprobando(null);
            recargar();
          }}
        />
      )}

      {rechazando && (
        <RechazarSolicitud
          solicitud={rechazando}
          onClose={() => setRechazando(null)}
          onRejected={() => {
            setRechazando(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}
