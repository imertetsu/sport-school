import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/client';
import { useAuth } from '@/auth/useAuth';
import { Button, Card, Field, Monogram } from '@/components/ui';
import { WhatsAppVinculacion } from './WhatsAppVinculacion';
import './AjustesEscuela.css';

// Paleta acotada de colores del monograma (chips). Hex #RRGGBB (el backend valida
// ese formato). Coherente con los acentos/estados del design-system. Además del
// chip, hay un <input type="color"> para libertad total dentro del mismo formato.
const PALETA: { hex: string; nombre: string }[] = [
  { hex: '#2563EB', nombre: 'Azul' },
  { hex: '#16A34A', nombre: 'Verde' },
  { hex: '#7C3AED', nombre: 'Violeta' },
  { hex: '#DB2777', nombre: 'Rosa' },
  { hex: '#EA580C', nombre: 'Naranja' },
  { hex: '#0891B2', nombre: 'Cian' },
  { hex: '#CA8A04', nombre: 'Ámbar' },
  { hex: '#DC2626', nombre: 'Rojo' },
  { hex: '#475569', nombre: 'Pizarra' },
  { hex: '#0F766E', nombre: 'Teal' },
];

const HEX_RE = /^#([0-9a-fA-F]{6})$/;

function normalizeHex(c: string): string {
  return c.trim().toUpperCase();
}

// Ajustes/Escuela (epic escuela-y-bajas, Fase 1) — SOLO ADMIN. Edita nombre +
// color del monograma de la escuela. La ruta está gateada con RoleRoute
// allow={['ADMIN']} y el backend impone que /mi-escuela sea solo ADMIN (403 a
// ENTRENADOR) y scopee SIEMPRE a user.org_id. Al guardar, refresca la org del
// AuthContext para que el TopBar se actualice al instante (sin re-login).
export function AjustesEscuela() {
  const { setOrg, orgId } = useAuth();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [nombre, setNombre] = useState('');
  const [color, setColor] = useState<string | null>(null);

  const [nombreError, setNombreError] = useState<string | null>(null);
  const [colorError, setColorError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);

  // Carga inicial con GET /mi-escuela.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(null);
    api
      .miEscuela(controller.signal)
      .then((data) => {
        if (!active) return;
        setNombre(data.nombre);
        setColor(data.color);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.isForbidden) {
          setLoadError('No tienes permiso para ver los ajustes de la escuela.');
        } else {
          setLoadError(
            err instanceof ApiError ? err.message : 'No se pudo cargar la escuela.',
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  function elegirColor(hex: string) {
    setColor(normalizeHex(hex));
    setColorError(null);
    setSavedOk(false);
  }

  function onColorInput(value: string) {
    setColor(normalizeHex(value));
    setColorError(null);
    setSavedOk(false);
  }

  function validar(): boolean {
    let ok = true;
    if (!nombre.trim()) {
      setNombreError('El nombre de la escuela no puede estar vacío.');
      ok = false;
    } else {
      setNombreError(null);
    }
    // color null/"" => válido (el front usa default). Si hay valor, debe ser #RRGGBB.
    if (color && !HEX_RE.test(color)) {
      setColorError('El color debe ser un hex válido (#RRGGBB).');
      ok = false;
    } else {
      setColorError(null);
    }
    return ok;
  }

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSavedOk(false);
    if (!validar()) return;
    setSaving(true);
    try {
      const actualizado = await api.actualizarMiEscuela({
        nombre: nombre.trim(),
        color: color ? normalizeHex(color) : null,
      });
      // Refresca el TopBar al instante: la org del AuthContext lleva {id,nombre,color}.
      // El id no cambia (mismo tenant); lo tomamos del contexto para no perderlo.
      setOrg({
        id: orgId ?? '',
        nombre: actualizado.nombre,
        color: actualizado.color,
      });
      setNombre(actualizado.nombre);
      setColor(actualizado.color);
      setSavedOk(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isForbidden) {
          setSaveError('No tienes permiso para editar la escuela.');
        } else if (err.isValidation) {
          setSaveError(err.message);
        } else {
          setSaveError(err.message);
        }
      } else {
        setSaveError('No se pudo guardar. Inténtalo de nuevo.');
      }
    } finally {
      setSaving(false);
    }
  }

  const colorActivo = color && HEX_RE.test(color) ? normalizeHex(color) : null;

  return (
    <div className="ajustes-escuela">
      <header className="page-head">
        <div>
          <h1 className="page-head__title">Ajustes de la escuela</h1>
          <p className="page-head__subtitle">
            Personaliza el nombre y el color del monograma de tu escuela.
          </p>
        </div>
      </header>

      {loadError && (
        <div className="page-error" role="alert">
          {loadError}
        </div>
      )}

      {!loadError && (
        <Card>
          {loading ? (
            <p className="ajustes-escuela__loading">Cargando…</p>
          ) : (
            <form className="ajustes-escuela__form" onSubmit={guardar} noValidate>
              {/* Vista previa del monograma con los valores actuales del formulario. */}
              <div className="ajustes-escuela__preview" aria-label="Vista previa">
                <Monogram name={nombre || 'Escuela'} color={colorActivo} size="lg" />
                <div className="ajustes-escuela__preview-text">
                  <span className="ajustes-escuela__preview-name">
                    {nombre.trim() || 'Nombre de la escuela'}
                  </span>
                  <span className="ajustes-escuela__preview-hint">
                    Así se verá en la barra superior.
                  </span>
                </div>
              </div>

              <Field
                label="Nombre de la escuela"
                value={nombre}
                onChange={(e) => {
                  setNombre(e.target.value);
                  setNombreError(null);
                  setSavedOk(false);
                }}
                error={nombreError ?? undefined}
                required
                maxLength={120}
                autoComplete="off"
              />

              <div className="field">
                <span className="field__label">Color del monograma</span>
                <div
                  className="ajustes-escuela__chips"
                  role="radiogroup"
                  aria-label="Color del monograma"
                >
                  {PALETA.map((c) => {
                    const activo = colorActivo === c.hex;
                    return (
                      <button
                        key={c.hex}
                        type="button"
                        role="radio"
                        aria-checked={activo}
                        className={`ajustes-escuela__chip${activo ? ' ajustes-escuela__chip--active' : ''}`}
                        style={{ backgroundColor: c.hex }}
                        title={c.nombre}
                        aria-label={c.nombre}
                        onClick={() => elegirColor(c.hex)}
                      />
                    );
                  })}
                </div>

                <div className="ajustes-escuela__color-custom">
                  <label className="ajustes-escuela__color-input">
                    <span className="sr-only">Color personalizado</span>
                    <input
                      type="color"
                      value={colorActivo ?? '#2563EB'}
                      onChange={(e) => onColorInput(e.target.value)}
                      aria-label="Elegir un color personalizado"
                    />
                  </label>
                  <span className="ajustes-escuela__color-code">
                    {colorActivo ?? 'Color automático (según el nombre)'}
                  </span>
                  {color && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setColor(null);
                        setColorError(null);
                        setSavedOk(false);
                      }}
                    >
                      Quitar color
                    </Button>
                  )}
                </div>
                {colorError && (
                  <p className="field__error" role="alert">
                    {colorError}
                  </p>
                )}
                {!colorError && (
                  <p className="field__hint">
                    Sin color elegido, el monograma usa un color automático derivado del nombre.
                  </p>
                )}
              </div>

              {saveError && (
                <div className="page-error" role="alert">
                  {saveError}
                </div>
              )}
              {savedOk && (
                <div className="ajustes-escuela__ok" role="status">
                  Cambios guardados.
                </div>
              )}

              <div className="ajustes-escuela__actions">
                <Button type="submit" variant="primary" disabled={saving}>
                  {saving ? 'Guardando…' : 'Guardar cambios'}
                </Button>
              </div>
            </form>
          )}
        </Card>
      )}

      {/* WhatsApp de la escuela (epic whatsapp-multitenant): vincular por QR,
          estado y desvincular. SOLO ADMIN (la ruta /ajustes ya gatea ADMIN y el
          backend impone require_role("ADMIN")). Carga su propio estado de forma
          independiente del editor de nombre/color. */}
      <WhatsAppVinculacion />
    </div>
  );
}
