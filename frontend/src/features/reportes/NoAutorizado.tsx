import { useNavigate } from 'react-router-dom';
import { Button, Card } from '@/components/ui';

// Pantalla mostrada cuando un usuario sin permisos (p. ej. ENTRENADOR) intenta
// abrir una ruta gerencial como /reportes. El backend ya impone el 403; esto es
// la barrera de UX equivalente en el cliente.
export function NoAutorizado() {
  const navigate = useNavigate();
  return (
    <div className="reportes">
      <Card title="Acceso no autorizado">
        <p>No tienes permiso para ver esta sección.</p>
        <p className="page-head__subtitle">
          Esta vista es solo para administradores.
        </p>
        <Button variant="primary" onClick={() => navigate('/panel')}>
          Volver al panel
        </Button>
      </Card>
    </div>
  );
}
