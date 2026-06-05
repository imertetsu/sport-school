import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { EgresoItem } from '@/api/types';
import {
  Button,
  Card,
  DataTable,
  Field,
  SelectField,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { formatDate, formatMoney } from '@/lib/format';
import { NuevoEgreso } from './NuevoEgreso';
import './Egresos.css';

const PAGE_SIZE = 20;

// Pantalla de egresos (RF-FIN-07): lista con filtros + total (Bs) y alta.
// SOLO ADMIN (la ruta y el item de nav ya están gateados; el backend da 403).
export function Egresos() {
  // Sucursales del usuario (su alcance); "" = todas las del alcance.
  const { sucursales } = useSucursales();

  // --- Filtros ---
  const [sucursalId, setSucursalId] = useState('');
  const [categoria, setCategoria] = useState('');
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [page, setPage] = useState(1);

  // --- Datos ---
  const [items, setItems] = useState<EgresoItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalMonto, setTotalMonto] = useState<string>('0');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // --- Alta + recarga ---
  const [modalOpen, setModalOpen] = useState(false);
  // Token que fuerza una recarga tras crear un egreso.
  const [reloadKey, setReloadKey] = useState(0);

  // Cualquier cambio de filtro vuelve a la primera página.
  useEffect(() => {
    setPage(1);
  }, [sucursalId, categoria, desde, hasta]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .listEgresos(
        {
          sucursal_id: sucursalId || undefined,
          categoria: categoria.trim() || undefined,
          desde: desde || undefined,
          hasta: hasta || undefined,
          page,
          page_size: PAGE_SIZE,
        },
        controller.signal,
      )
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
        // El total se muestra desde total_monto del servidor (suma de TODO el
        // filtro), NO se recalcula sumando la página visible.
        setTotalMonto(res.total_monto);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los egresos');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sucursalId, categoria, desde, hasta, page, reloadKey]);

  const hasFiltros = Boolean(sucursalId || categoria.trim() || desde || hasta);

  function limpiarFiltros() {
    setSucursalId('');
    setCategoria('');
    setDesde('');
    setHasta('');
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns = useMemo<Column<EgresoItem>[]>(
    () => [
      {
        key: 'fecha',
        header: 'Fecha',
        render: (e) => <span className="tabular">{formatDate(e.fecha)}</span>,
      },
      {
        key: 'categoria',
        header: 'Categoría',
        render: (e) => (
          <div className="egreso-cell">
            <span className="egreso-cell__cat">{e.categoria_gasto}</span>
            {e.descripcion && <span className="egreso-cell__desc">{e.descripcion}</span>}
          </div>
        ),
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        hideOnNarrow: true,
        render: (e) =>
          e.sucursal ? (
            e.sucursal.nombre
          ) : (
            <span className="egreso-cell__muted">— Organización</span>
          ),
      },
      {
        key: 'registrado_por',
        header: 'Registrado por',
        hideOnNarrow: true,
        render: (e) =>
          e.registrado_por_nombre ?? <span className="egreso-cell__muted">—</span>,
      },
      {
        key: 'monto',
        header: 'Monto',
        align: 'right',
        render: (e) => <span className="tabular">{formatMoney(e.monto)}</span>,
      },
    ],
    [],
  );

  return (
    <div className="egresos">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Egresos</h1>
          <p className="page-head__subtitle">
            {loading
              ? 'Cargando…'
              : `${total} egreso${total === 1 ? '' : 's'}${hasFiltros ? ' para este filtro' : ''}`}
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          + Registrar egreso
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card>
        <div className="egresos__filtros">
          <SelectField
            label="Sucursal"
            value={sucursalId}
            onChange={(e) => setSucursalId(e.target.value)}
          >
            <option value="">Todas</option>
            {sucursales.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </SelectField>
          <Field
            label="Categoría"
            value={categoria}
            onChange={(e) => setCategoria(e.target.value)}
            placeholder="Alquiler de cancha"
          />
          <Field
            label="Desde"
            type="date"
            value={desde}
            onChange={(e) => setDesde(e.target.value)}
          />
          <Field
            label="Hasta"
            type="date"
            value={hasta}
            onChange={(e) => setHasta(e.target.value)}
          />
        </div>
        {hasFiltros && (
          <div className="egresos__filtros-acciones">
            <Button variant="ghost" size="sm" onClick={limpiarFiltros}>
              Limpiar filtros
            </Button>
          </div>
        )}
      </Card>

      <Card>
        <div className="egresos__total">
          <span className="egresos__total-label">Total del filtro</span>
          <div>
            <span className="egresos__total-monto tabular">{formatMoney(totalMonto)}</span>
          </div>
          <span className="egresos__total-meta">
            {hasFiltros ? 'Suma de los egresos que cumplen el filtro' : 'Suma de todos los egresos'}
          </span>
        </div>
      </Card>

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de egresos"
          columns={columns}
          rows={items}
          rowKey={(e) => e.id}
          loading={loading}
          emptyMessage={
            hasFiltros ? 'Sin egresos para este filtro' : 'Aún no hay egresos registrados'
          }
        />
      </Card>

      {total > PAGE_SIZE && (
        <div className="egresos__pager">
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

      {modalOpen && (
        <NuevoEgreso
          sucursales={sucursales}
          onClose={() => setModalOpen(false)}
          onCreated={() => {
            setModalOpen(false);
            // Vuelve a la primera página y recarga para ver el nuevo egreso y el total.
            setPage(1);
            setReloadKey((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
