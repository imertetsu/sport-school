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

// Gate de rol para rutas gerenciales (p. ej. /reportes, solo ADMIN). Gatea
// sobre el rol REAL del usuario autenticado (`role`), no sobre una vista
// modificable. Si el rol no está permitido, redirige a "no autorizado" en
// vez de montar la pantalla.
export function RoleRoute({
  allow,
  children,
}: {
  allow: Role[];
  children: ReactNode;
}) {
  const { role, loading } = useAuth();

  if (loading) {
    return (
      <div className="route-loading" role="status" aria-live="polite">
        Cargando…
      </div>
    );
  }

  if (!role || !allow.includes(role)) {
    return <Navigate to="/no-autorizado" replace />;
  }

  return <>{children}</>;
}
