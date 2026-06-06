import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '@/api/client';
import { Button, Field } from '@/components/ui';
import { usePlatformAuth } from './PlataformaAuth';
import './Plataforma.css';

interface LocationState {
  from?: { pathname: string };
}

// Login de la CONSOLA DE PLATAFORMA (rol SUPERADMIN). Guarda el token en su propia
// clave de storage (no pisa la sesión de escuela) y redirige a Escuelas.
export function PlataformaLogin() {
  const { login, token } = usePlatformAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from =
    (location.state as LocationState | null)?.from?.pathname ?? '/plataforma/escuelas';

  if (token) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.isUnauthorized
            ? 'Credenciales inválidas o cuenta inactiva.'
            : err.message,
        );
      } else {
        setError('No se pudo conectar con el servidor. Intenta de nuevo.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="plataforma-login">
      <form className="plataforma-login__card" onSubmit={handleSubmit} noValidate>
        <div className="plataforma-login__brand">
          <span className="plataforma-login__logo" aria-hidden="true">
            ⬡
          </span>
          <span className="plataforma-login__brand-name">LATINOSPORT</span>
        </div>
        <h1 className="plataforma-login__title">Consola de plataforma</h1>
        <p className="plataforma-login__subtitle">Acceso de super administrador</p>

        {error && (
          <div className="plataforma-login__error" role="alert">
            {error}
          </div>
        )}

        <Field
          label="Correo electrónico"
          type="email"
          name="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="operador@latinosport.com"
          required
        />
        <Field
          label="Contraseña"
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          required
        />

        <Button
          type="submit"
          variant="primary"
          className="plataforma-login__submit"
          disabled={submitting || !email || !password}
        >
          {submitting ? 'Entrando…' : 'Entrar'}
        </Button>
      </form>
    </div>
  );
}
