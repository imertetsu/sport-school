// Config de marca y API. El nombre sale de aquí, no hardcodeado por toda la app (C0).
export const APP_NAME: string = import.meta.env.VITE_APP_NAME ?? 'CanteraSport';

// Base del API sin slash final. El cliente le agrega el prefijo /api/v1.
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '');

export const API_PREFIX = '/api/v1';

// Clave de almacenamiento del token JWT.
export const TOKEN_STORAGE_KEY = 'canterasport.token';

// Acento por defecto del tema (verde) y alterno (azul). Intercambiable vía data-accent.
export type Accent = 'verde' | 'azul';
export const DEFAULT_ACCENT: Accent = 'verde';
export const ACCENT_STORAGE_KEY = 'canterasport.accent';
