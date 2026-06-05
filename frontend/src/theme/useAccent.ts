import { useCallback, useEffect, useState } from 'react';
import { ACCENT_STORAGE_KEY, DEFAULT_ACCENT, type Accent } from '@/config';

function readStoredAccent(): Accent {
  try {
    const v = localStorage.getItem(ACCENT_STORAGE_KEY);
    return v === 'azul' || v === 'verde' ? v : DEFAULT_ACCENT;
  } catch {
    return DEFAULT_ACCENT;
  }
}

function applyAccent(accent: Accent): void {
  document.documentElement.setAttribute('data-accent', accent);
}

// Hook de acento intercambiable (verde default / azul). Persiste y aplica el
// atributo data-accent en <html>, donde tokens.css lo recoge.
export function useAccent(): { accent: Accent; setAccent: (a: Accent) => void; toggle: () => void } {
  const [accent, setAccentState] = useState<Accent>(readStoredAccent);

  useEffect(() => {
    applyAccent(accent);
    try {
      localStorage.setItem(ACCENT_STORAGE_KEY, accent);
    } catch {
      /* noop */
    }
  }, [accent]);

  const setAccent = useCallback((a: Accent) => setAccentState(a), []);
  const toggle = useCallback(
    () => setAccentState((prev) => (prev === 'verde' ? 'azul' : 'verde')),
    [],
  );

  return { accent, setAccent, toggle };
}
