// Config de marca y API. El nombre sale de aquí, no hardcodeado por toda la app (C0).
export const APP_NAME: string = import.meta.env.VITE_APP_NAME ?? 'LATINOSPORT';

// Base del API sin slash final. El cliente le agrega el prefijo /api/v1.
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '');

export const API_PREFIX = '/api/v1';

// Clave de almacenamiento del token JWT.
export const TOKEN_STORAGE_KEY = 'latinosport.token';

// Acento por defecto del tema (AZUL) y alterno (verde). Intercambiable vía data-accent.
export type Accent = 'verde' | 'azul';
export const DEFAULT_ACCENT: Accent = 'azul';
export const ACCENT_STORAGE_KEY = 'latinosport.accent';
