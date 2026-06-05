import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import type { Role } from '@/api/types';
import { useAuth } from './useAuth';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="route-loading" role="status" aria-live="polite">
        Cargando…
      </div>
    );
  }

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}

// Gate de rol para rutas gerenciales (p. ej. /reportes, solo ADMIN). Usa el
// `viewRole` activo (respeta el toggle del prototipo). Si el rol no está
// permitido, redirige a una pantalla "no autorizado" en vez de mostrar datos.
export function RoleRoute({
  allow,
  children,
}: {
  allow: Role[];
  children: ReactNode;
}) {
  const { viewRole, loading } = useAuth();

  if (loading) {
    return (
      <div className="route-loading" role="status" aria-live="polite">
        Cargando…
      </div>
    );
  }

  if (!viewRole || !allow.includes(viewRole)) {
    return <Navigate to="/no-autorizado" replace />;
  }

  return <>{children}</>;
}
