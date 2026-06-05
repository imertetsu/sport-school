import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { DEFAULT_ACCENT } from './config';
import './theme/tokens.css';

// Aplica el acento por defecto (verde) antes del primer render; useAccent lo
// rehidrata desde almacenamiento dentro de la app.
document.documentElement.setAttribute('data-accent', DEFAULT_ACCENT);

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('No se encontró el elemento #root');
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
