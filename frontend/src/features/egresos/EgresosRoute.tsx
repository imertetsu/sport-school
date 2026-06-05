import { Navigate } from 'react-router-dom';
import { useAuth } from '@/auth/useAuth';
import { Egresos } from './Egresos';

// Gate de ruta para Egresos: SOLO ADMIN (defensa en profundidad; el backend ya
// responde 403). Un ENTRENADOR que escriba /egresos a mano vuelve al panel.
export function EgresosRoute() {
  const { viewRole } = useAuth();
  if (viewRole !== 'ADMIN') {
    return <Navigate to="/panel" replace />;
  }
  return <Egresos />;
}
