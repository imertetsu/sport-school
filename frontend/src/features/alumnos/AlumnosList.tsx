import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/api/client';
import type { AlumnoListItem } from '@/api/types';
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
import './AlumnosList.css';

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function AlumnosList() {
  const navigate = useNavigate();
  const { selected: sucursalId } = useSucursales();
  const { query } = useSearch();
  const debouncedQuery = useDebounced(query.trim());

  const [items, setItems] = useState<AlumnoListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    api
      .alumnos(
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
        setError(err instanceof ApiError ? err.message : 'No se pudieron cargar los alumnos');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [debouncedQuery, sucursalId]);

  const columns = useMemo<Column<AlumnoListItem>[]>(
    () => [
      {
        key: 'alumno',
        header: 'Alumno',
        render: (a) => {
          const cat = a.categoria
            ? `${a.categoria.nombre} ${nivelLabel(a.categoria.nivel)}`.trim()
            : 'Sin categoría';
          return (
            <div className="alumno-cell">
              <Avatar name={a.nombre_completo} size="md" />
              <div className="alumno-cell__text">
                <span className="alumno-cell__name">{a.nombre_completo}</span>
                <span className="alumno-cell__meta">
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
    <div className="alumnos-list">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Alumnos</h1>
          <p className="page-head__subtitle">
            {loading ? 'Cargando…' : `${total} alumno${total === 1 ? '' : 's'}`}
            {sucursalId ? ' en la sucursal seleccionada' : ''}
          </p>
        </div>
        <Button variant="primary" onClick={() => navigate('/alumnos/nuevo')}>
          + Nuevo alumno
        </Button>
      </header>

      {error && (
        <div className="page-error" role="alert">
          {error}
        </div>
      )}

      <Card padded={false}>
        <DataTable
          ariaLabel="Lista de alumnos"
          columns={columns}
          rows={items}
          rowKey={(a) => a.id}
          loading={loading}
          onRowClick={(a) => navigate(`/alumnos/${a.id}`)}
          emptyMessage={
            debouncedQuery || sucursalId
              ? 'Sin alumnos para este filtro'
              : 'Aún no hay alumnos registrados'
          }
        />
      </Card>
    </div>
  );
}
