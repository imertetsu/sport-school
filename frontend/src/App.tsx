import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/auth/AuthContext';
import { ProtectedRoute, RoleRoute } from '@/auth/ProtectedRoute';
import { Login } from '@/auth/Login';
import { AppShell } from '@/components/shell/AppShell';
import { AlumnosList } from '@/features/alumnos/AlumnosList';
import { AlumnoPerfil } from '@/features/alumnos/AlumnoPerfil';
import { NuevoAlumno } from '@/features/alumnos/NuevoAlumno';
import { Solicitudes } from '@/features/solicitudes/Solicitudes';
import { PanelCobranza } from '@/features/cobranza/PanelCobranza';
import { PagosHistorial } from '@/features/cobranza/PagosHistorial';
import { TomarAsistencia } from '@/features/asistencia/TomarAsistencia';
import { Horarios } from '@/features/horarios/Horarios';
import { Muro } from '@/features/avisos/Muro';
import { Egresos } from '@/features/egresos/Egresos';
import { Reportes } from '@/features/reportes/Reportes';
import { Sucursales } from '@/features/sucursales/Sucursales';
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
            {/* Solicitudes (auto-registro EN SISTEMA): ruta protegida normal,
                visible a ADMIN y ENTRENADOR (sin gate de rol). El backend filtra
                la cola por rol; aprobar/rechazar solo lo muestra la UI a ADMIN y
                el backend lo exige (require_role). NO hay ruta pública. */}
            <Route path="/solicitudes" element={<Solicitudes />} />
            <Route path="/asistencia" element={<TomarAsistencia />} />
            {/* Horarios / programación de clases: visible a ADMIN y ENTRENADOR
                (sin gate de rol). El backend filtra la vista por rol; las
                acciones de escritura solo las muestra la UI a ADMIN y el backend
                las exige (require_role). */}
            <Route path="/horarios" element={<Horarios />} />
            {/* Muro de avisos: visible a ADMIN y ENTRENADOR (sin gate de rol).
                El feed lo filtra el backend; las acciones de escritura solo
                las muestra la UI a ADMIN y el backend las exige (require_role). */}
            <Route path="/avisos" element={<Muro />} />
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
            {/* Sucursales/Categorías (catálogo): gate de rol ADMIN. */}
            <Route
              path="/sucursales"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <Sucursales />
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
