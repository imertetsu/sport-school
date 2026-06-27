import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/auth/AuthContext';
import { ProtectedRoute, RoleRoute } from '@/auth/ProtectedRoute';
import { Login } from '@/auth/Login';
import { AppShell } from '@/components/shell/AppShell';
import { DeportistasList } from '@/features/deportistas/DeportistasList';
import { DeportistaPerfil } from '@/features/deportistas/DeportistaPerfil';
import { NuevoDeportista } from '@/features/deportistas/NuevoDeportista';
import { Solicitudes } from '@/features/solicitudes/Solicitudes';
import { PanelCobranza } from '@/features/cobranza/PanelCobranza';
import { PagosHistorial } from '@/features/cobranza/PagosHistorial';
import { Pagos } from '@/features/cobranza/Pagos';
import { PagosPorVerificar } from '@/features/cobranza/PagosPorVerificar';
import { TomarAsistencia } from '@/features/asistencia/TomarAsistencia';
import { Horarios } from '@/features/horarios/Horarios';
import { Muro } from '@/features/avisos/Muro';
import { Egresos } from '@/features/egresos/Egresos';
import { Entrenadores } from '@/features/entrenadores/Entrenadores';
import { Reportes } from '@/features/reportes/Reportes';
import { Sucursales } from '@/features/sucursales/Sucursales';
import { AjustesEscuela } from '@/features/escuela/AjustesEscuela';
import { NoAutorizado } from '@/features/reportes/NoAutorizado';
// Consola de PLATAFORMA (Epic A, rol SUPERADMIN). App separada del panel de
// escuela: su propio provider de sesión, guard y layout (sin el Sidebar de escuela).
import { PlatformAuthProvider } from '@/features/plataforma/PlataformaAuth';
import { PlataformaGuard, PlataformaShell } from '@/features/plataforma/PlataformaShell';
import { PlataformaLogin } from '@/features/plataforma/PlataformaLogin';
import { Escuelas } from '@/features/plataforma/Escuelas';
import { SuperAdmins } from '@/features/plataforma/SuperAdmins';
import { Disciplinas } from '@/features/plataforma/Disciplinas';
// Herramienta de DEV (spike OCR de cédula, STANDALONE): ruta suelta sin sesión
// ni nav. No forma parte del producto; sirve para validar precisión del OCR.
import { OcrSpike } from '@/features/dev/OcrSpike';

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
            {/* Lista de pagos buscable + anular pago efectivo (epic anular-pago):
                punto de acceso al botón "Anular". SOLO ADMIN (gate de rol; el
                backend impone require_role("ADMIN") y scopea por RLS). */}
            <Route
              path="/pagos-lista"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <Pagos />
                </RoleRoute>
              }
            />
            {/* Pagos por verificar (epic pagos-qr-comprobante): cola de
                comprobantes entrantes para confirmar/rechazar. SOLO ADMIN (gate
                de rol; el backend impone require_role("ADMIN")). */}
            <Route
              path="/pagos-por-verificar"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <PagosPorVerificar />
                </RoleRoute>
              }
            />
            <Route path="/deportistas" element={<DeportistasList />} />
            <Route path="/deportistas/nuevo" element={<NuevoDeportista />} />
            {/* Edición completa del deportista (epic escuela-y-bajas, Fase 3):
                reusa NuevoDeportista en modo edición (detecta :id). React Router v6
                rankea por especificidad, así que "/deportistas/:id/editar" gana
                sobre "/deportistas/:id". El backend exige ADMIN en el PUT (el
                perfil oculta el botón "Editar" a no-ADMIN). */}
            <Route path="/deportistas/:id/editar" element={<NuevoDeportista />} />
            <Route path="/deportistas/:id" element={<DeportistaPerfil />} />
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
            {/* Entrenadores (Epic B): gestión solo ADMIN. El backend deja listar
                a cualquier rol (pobla selectores) pero la pantalla de gestión y
                sus escrituras son ADMIN (require_role). */}
            <Route
              path="/entrenadores"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <Entrenadores />
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
            {/* Ajustes de la escuela (epic escuela-y-bajas): nombre + color del
                monograma. Gate de rol ADMIN; el backend impone que /mi-escuela
                sea solo ADMIN y scopee a user.org_id. */}
            <Route
              path="/ajustes"
              element={
                <RoleRoute allow={['ADMIN']}>
                  <AjustesEscuela />
                </RoleRoute>
              }
            />
            <Route path="/no-autorizado" element={<NoAutorizado />} />
          </Route>

          {/* Consola de PLATAFORMA (SUPERADMIN). Árbol separado: su propio provider
              de sesión (token en otra clave de storage) y su propio guard. NO usa
              ProtectedRoute/RoleRoute (sesión de escuela). */}
          <Route
            path="/plataforma"
            element={
              <PlatformAuthProvider>
                <Outlet />
              </PlatformAuthProvider>
            }
          >
            <Route index element={<Navigate to="/plataforma/escuelas" replace />} />
            <Route path="login" element={<PlataformaLogin />} />
            <Route element={<PlataformaGuard />}>
              <Route element={<PlataformaShell />}>
                <Route path="escuelas" element={<Escuelas />} />
                <Route path="admins" element={<SuperAdmins />} />
                <Route path="disciplinas" element={<Disciplinas />} />
              </Route>
            </Route>
          </Route>

          {/* DEV: spike OCR standalone. Sin guard/nav; herramienta de validación. */}
          <Route path="/dev/ocr" element={<OcrSpike />} />

          <Route path="*" element={<Navigate to="/panel" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
