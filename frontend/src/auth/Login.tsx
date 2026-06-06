import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate, Navigate } from 'react-router-dom';
import { BrandName } from '@/components/BrandName';
import { ApiError } from '@/api/client';
import { Button, Field } from '@/components/ui';
import { useAuth } from './useAuth';
import './Login.css';

interface LocationState {
  from?: { pathname: string };
}

export function Login() {
  const { login, token, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as LocationState | null)?.from?.pathname ?? '/alumnos';

  // Si ya hay sesión, no mostrar el login.
  if (token && !loading) {
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
            ? 'Credenciales inválidas. Revisa tu correo y contraseña.'
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
    <div className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <div className="login__brand">
          <span className="login__logo" aria-hidden="true">
            ⬡
          </span>
          <BrandName className="login__brand-name" />
        </div>
        <h1 className="login__title">Iniciar sesión</h1>
        <p className="login__subtitle">Panel de administración y entrenadores</p>

        {error && (
          <div className="login__error" role="alert">
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
          placeholder="admin@escuela.bo"
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
          className="login__submit"
          disabled={submitting || !email || !password}
        >
          {submitting ? 'Entrando…' : 'Entrar'}
        </Button>
      </form>
    </div>
  );
}
