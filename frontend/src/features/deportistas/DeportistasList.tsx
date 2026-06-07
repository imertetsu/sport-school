import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type { DeportistaListItem } from '@/api/types';
import {
  Avatar,
  Badge,
  Button,
  Card,
  DataTable,
  type Column,
} from '@/components/ui';
import { useSucursales } from '@/components/shell/SucursalContext';
import { useSearch } from '@/components/shell/SearchContext';
import { nivelLabel } from '@/lib/format';
import './DeportistasList.css';

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function DeportistasList() {
  const navigate = useNavigate();
  const { selected: sucursalId } = useSucursales();
  const { query } = useSearch();
  const debouncedQuery = useDebounced(query.trim());

  const [items, setItems] = useState<DeportistaListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .deportistas(
        {
          q: debouncedQuery || undefined,
          sucursal_id: sucursalId || undefined,
          page: 1,
          page_size: 50,
        },
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
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los deportistas');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [debouncedQuery, sucursalId]);

  const columns = useMemo<Column<DeportistaListItem>[]>(
    () => [
      {
        key: 'deportista',
        header: 'Deportista',
        render: (a) => {
          const cat = a.categoria
            ? `${a.categoria.nombre} ${nivelLabel(a.categoria.nivel)}`.trim()
            : 'Sin categoría';
          return (
            <div className="deportista-cell">
              <Avatar name={a.nombre_completo} size="md" />
              <div className="deportista-cell__text">
                <span className="deportista-cell__name">{a.nombre_completo}</span>
                <span className="deportista-cell__meta">
                  {cat} · {a.disciplina}
                </span>
              </div>
            </div>
          );
        },
      },
      {
        key: 'ci',
        header: 'CI',
        hideOnNarrow: true,
        render: (a) => <span className="tabular">{a.ci}</span>,
      },
      {
        key: 'sucursal',
        header: 'Sucursal',
        render: (a) => a.sucursal.nombre,
      },
      {
        key: 'estado',
        header: 'Estado',
        align: 'center',
        // Cobranza es otro epic: placeholder "—".
        render: () => (
          <Badge tone="neutral" className="estado-placeholder">
            —
          </Badge>
        ),
      },
    ],
    [],
  );

  return (
    <div className="deportistas-list">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Deportistas</h1>
          <p className="page-head__subtitle">
            {loading ? 'Cargando…' : `${total} deportista${total === 1 ? '' : 's'}`}
            {sucursalId ? ' en la sucursal seleccionada' : ''}
          </p>
        </div>
        <Button variant="primary" onClick={() => navigate('/deportistas/nuevo')}>
          + Nuevo deportista
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de deportistas"
          columns={columns}
          rows={items}
          rowKey={(a) => a.id}
          loading={loading}
          onRowClick={(a) => navigate(`/deportistas/${a.id}`)}
          emptyMessage={
            debouncedQuery || sucursalId
              ? 'Sin deportistas para este filtro'
              : 'Aún no hay deportistas registrados'
          }
        />
      </Card>
    </div>
  );
}
