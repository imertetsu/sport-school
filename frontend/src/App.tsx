import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/auth/AuthContext';
import { ProtectedRoute } from '@/auth/ProtectedRoute';
import { Login } from '@/auth/Login';
import { AppShell } from '@/components/shell/AppShell';
import { AlumnosList } from '@/features/alumnos/AlumnosList';
import { AlumnoPerfil } from '@/features/alumnos/AlumnoPerfil';
import { NuevoAlumno } from '@/features/alumnos/NuevoAlumno';

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
            <Route index element={<Navigate to="/alumnos" replace />} />
            <Route path="/alumnos" element={<AlumnosList />} />
            <Route path="/alumnos/nuevo" element={<NuevoAlumno />} />
            <Route path="/alumnos/:id" element={<AlumnoPerfil />} />
          </Route>
          <Route path="*" element={<Navigate to="/alumnos" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
