// Config de marca y API. El nombre sale de aquí, no hardcodeado por toda la app (C0).
export const APP_NAME: string = import.meta.env.VITE_APP_NAME ?? 'LATINOSPORT';

// Base del API sin slash final. El cliente le agrega el prefijo /api/v1.
// Vacío ('') = MISMO ORIGEN: la SPA y la API se sirven tras el mismo host/puerto
// (nginx hace de proxy inverso a /api). En dev se fija VITE_API_URL a la API local.
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_URL ?? ''
).replace(/\/+$/, '');

export const API_PREFIX = '/api/v1';

// Clave de almacenamiento del token JWT (sesión de ESCUELA, roles ADMIN/ENTRENADOR).
export const TOKEN_STORAGE_KEY = 'latinosport.token';

// Org embebida en el login (epic escuela-y-bajas, C1): {id,nombre,color}. Se
// persiste junto al token para pintar nombre+monograma en el TopBar tras recargar
// sin una segunda llamada. Se limpia en el logout (igual que el token).
export const ORG_STORAGE_KEY = 'latinosport.org';

// Consola de PLATAFORMA (rol SUPERADMIN, token SIN org_id). Sesión SEPARADA de la
// de escuela: vive en claves de storage DISTINTAS para no pisarse mutuamente.
export const PLATFORM_TOKEN_STORAGE_KEY = 'latinosport.platform.token';
export const PLATFORM_ADMIN_STORAGE_KEY = 'latinosport.platform.admin';

// Acento por defecto del tema (AZUL) y alterno (verde). Intercambiable vía data-accent.
export type Accent = 'verde' | 'azul';
export const DEFAULT_ACCENT: Accent = 'azul';
export const ACCENT_STORAGE_KEY = 'latinosport.accent';
