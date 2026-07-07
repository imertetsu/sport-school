import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import './Toast.css';

// Sistema de "toast" global: un mensaje breve que aparece y se auto-oculta tras
// unos segundos, con el color de su tipo (verde=éxito, rojo=error, ámbar=aviso,
// azul=info). Sirve de confirmación al registrar / editar / eliminar / anular.
//
// Uso:  const toast = useToast();  toast.success('Pago registrado');
//
// El provider vive por encima del router (App.tsx), así el mensaje sobrevive a
// una navegación (p. ej. crear deportista → ir a su perfil y ahí verlo).

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface ToastOptions {
  message: string;
  variant?: ToastVariant;
  /** ms visibles; 0 = no auto-oculta (persistente hasta cerrar). */
  duration?: number;
}

interface ToastItem {
  id: number;
  message: string;
  variant: ToastVariant;
  /** true durante la animación de salida, antes de quitarlo del DOM. */
  leaving: boolean;
}

export interface ToastApi {
  show: (opts: ToastOptions) => number;
  success: (message: string, duration?: number) => number;
  error: (message: string, duration?: number) => number;
  warning: (message: string, duration?: number) => number;
  info: (message: string, duration?: number) => number;
  dismiss: (id: number) => void;
}

// Duración por tipo: los errores se quedan más tiempo para dar chance a leerlos.
const DEFAULT_DURATION: Record<ToastVariant, number> = {
  success: 3200,
  info: 3600,
  warning: 4500,
  error: 5200,
};

const ICON: Record<ToastVariant, string> = {
  success: '✓',
  error: '✕',
  warning: '!',
  info: 'i',
};

const MAX_VISIBLE = 4;
const EXIT_MS = 200; // debe coincidir con la animación .toast--leaving

// Fallback no-op: si algún componente usa useToast fuera del provider (p. ej. en
// un test aislado), no revienta — simplemente no muestra nada.
const NOOP: ToastApi = {
  show: () => 0,
  success: () => 0,
  error: () => 0,
  warning: () => 0,
  info: () => 0,
  dismiss: () => {},
};

const ToastContext = createContext<ToastApi>(NOOP);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const clearTimer = useCallback((id: number) => {
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  // Marca el toast como "saliendo" (dispara la animación) y lo quita del DOM al
  // terminar. Idempotente: si ya está saliendo, no reprograma.
  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id);
      let already = false;
      setToasts((list) =>
        list.map((t) => {
          if (t.id === id) {
            if (t.leaving) already = true;
            return { ...t, leaving: true };
          }
          return t;
        }),
      );
      if (already) return;
      const exit = setTimeout(() => {
        setToasts((list) => list.filter((x) => x.id !== id));
        timers.current.delete(id);
      }, EXIT_MS);
      timers.current.set(id, exit);
    },
    [clearTimer],
  );

  const show = useCallback(
    (opts: ToastOptions) => {
      const id = nextId++;
      const variant = opts.variant ?? 'info';
      const duration = opts.duration ?? DEFAULT_DURATION[variant];
      setToasts((list) => {
        const next = [...list, { id, message: opts.message, variant, leaving: false }];
        // Tope de mensajes visibles: descarta el más viejo si se acumulan.
        return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next;
      });
      if (duration > 0) {
        const timer = setTimeout(() => dismiss(id), duration);
        timers.current.set(id, timer);
      }
      return id;
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (message, duration) => show({ message, variant: 'success', duration }),
      error: (message, duration) => show({ message, variant: 'error', duration }),
      warning: (message, duration) => show({ message, variant: 'warning', duration }),
      info: (message, duration) => show({ message, variant: 'info', duration }),
      dismiss,
    }),
    [show, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-viewport" role="region" aria-label="Notificaciones">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast--${t.variant}${t.leaving ? ' toast--leaving' : ''}`}
          role={t.variant === 'error' ? 'alert' : 'status'}
          aria-live={t.variant === 'error' ? 'assertive' : 'polite'}
        >
          <span className="toast__icon" aria-hidden="true">
            {ICON[t.variant]}
          </span>
          <span className="toast__msg">{t.message}</span>
          <button
            type="button"
            className="toast__close"
            aria-label="Cerrar"
            onClick={() => onDismiss(t.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
