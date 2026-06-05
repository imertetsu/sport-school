import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/auth/AuthContext';
import { ProtectedRoute, RoleRoute } from '@/auth/ProtectedRoute';
import { Login } from '@/auth/Login';
import { AppShell } from '@/components/shell/AppShell';
import { AlumnosList } from '@/features/alumnos/AlumnosList';
import { AlumnoPerfil } from '@/features/alumnos/AlumnoPerfil';
import { NuevoAlumno } from '@/features/alumnos/NuevoAlumno';
import { PanelCobranza } from '@/features/cobranza/PanelCobranza';
import { PagosHistorial } from '@/features/cobranza/PagosHistorial';
import { TomarAsistencia } from '@/features/asistencia/TomarAsistencia';
import { Egresos } from '@/features/egresos/Egresos';
import { Reportes } from '@/features/reportes/Reportes';
import { NoAutorizado } from '@/features/reportes/NoAutorizado';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/panel" replace />} />
            <Route path="/panel" element={<PanelCobranza />} />
            <Route path="/pagos" element={<PagosHistorial />} />
            <Route path="/alumnos" element={<AlumnosList />} />
            <Route path="/alumnos/nuevo" element={<NuevoAlumno />} />
            <Route path="/alumnos/:id" element={<AlumnoPerfil />} />
            <Route path="/asistencia" element={<TomarAsistencia />} />
            {/* Egresos (financiero) y Reportes (gerencial): gate de rol ADMIN. */}
            <Route
              path="/egresos"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <Egresos />
                </RoleRoute>
              }
            />
            <Route
              path="/reportes"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <Reportes />
                </RoleRoute>
              }
            />
            <Route path="/no-autorizado" element={<NoAutorizado />} />
          </Route>
          <Route path="*" element={<Navigate to="/panel" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
