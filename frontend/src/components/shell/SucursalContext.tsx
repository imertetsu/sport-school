import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, ApiError } from '@/api/client';
import type { Sucursal } from '@/api/types';

interface SucursalState {
  sucursales: Sucursal[];
  loading: boolean;
  error: string | null;
  // "" = Todas las sucursales
  selected: string;
  setSelected: (id: string) => void;
}

const SucursalContext = createContext<SucursalState | null>(null);

export function SucursalProvider({ children }: { children: ReactNode }) {
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>('');

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    api
      .sucursales(controller.signal)
      .then((data) => {
        if (active) {
          setSucursales(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        const msg =
          err instanceof ApiError ? err.message : 'No se pudieron cargar las sucursales';
        setError(msg);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const value = useMemo<SucursalState>(
    () => ({ sucursales, loading, error, selected, setSelected }),
    [sucursales, loading, error, selected],
  );

  return <SucursalContext.Provider value={value}>{children}</SucursalContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSucursales(): SucursalState {
  const ctx = useContext(SucursalContext);
  if (!ctx) throw new Error('useSucursales debe usarse dentro de <SucursalProvider>');
  return ctx;
}
