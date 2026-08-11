import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '@/api/client';
import type {
  ChatConversacion,
  ChatConversacionesPage,
  ChatEnvioOut,
  ChatHilo,
  ChatMensaje,
  ChatTutor,
} from '@/api/types';
import { Button, useToast } from '@/components/ui';
import './ChatWhatsApp.css';

// Pantalla de chat estilo WhatsApp (epic chat-whatsapp). UNA sola implementación
// para las dos consolas: la de la escuela y la de plataforma. Lo que cambia entre
// ellas —qué endpoints pega y si puede asignar el hilo a una escuela— entra por
// `chatApi`, no por ramas dentro del componente.
//
// El alcance NO lo decide esta pantalla: lo impone RLS en el backend. La escuela
// recibe solo los hilos de sus tutores; los números que aún no se sabe de qué
// escuela son solo le llegan a la consola de plataforma.

// Cada cuánto se refresca. WhatsApp no nos empuja nada al navegador, así que el
// chat sondea; 8 s es el punto donde la conversación se siente viva sin castigar
// al servidor con una request por segundo y usuario.
const POLL_MS = 8000;

export interface EscuelaRef {
  id: string;
  nombre: string;
}

// Agenda de contactos: solo la consola de ESCUELA la tiene. Es lo que permite
// iniciar una conversación, porque la bandeja únicamente lista hilos ya abiertos y
// un hilo nace cuando el tutor escribe primero. Sin esto, a la mayoría de las
// familias no se les puede escribir nunca.
export interface ChatAgenda {
  tutores(buscar?: string, signal?: AbortSignal): Promise<ChatTutor[]>;
  abrir(telefono: string, signal?: AbortSignal): Promise<ChatHilo>;
}

export interface ChatApi {
  conversaciones(
    params: {
      buscar?: string;
      sinAsignar?: boolean;
      orgId?: string;
      cursorAt?: string;
      cursorId?: string;
    },
    signal?: AbortSignal,
  ): Promise<ChatConversacionesPage>;
  hilo(id: string, signal?: AbortSignal): Promise<ChatHilo>;
  responder(id: string, texto: string, signal?: AbortSignal): Promise<ChatEnvioOut>;
  media(id: string, signal?: AbortSignal): Promise<string>;
  // Solo la consola de plataforma: categorizar el hilo. Si falta, la UI no
  // muestra el selector de escuela.
  asignar?(id: string, orgId: string | null, signal?: AbortSignal): Promise<ChatConversacion>;
}

export interface ChatWhatsAppProps {
  chatApi: ChatApi;
  // Escuelas para el selector de asignación (solo consola de plataforma).
  escuelas?: EscuelaRef[];
  // Agenda de tutores (solo consola de escuela). Si falta, no hay "Nuevo mensaje".
  agenda?: ChatAgenda;
  // Título de la pantalla y texto del estado vacío.
  titulo: string;
  vacio: string;
}

// --------------------------------------------------------------------------- #
// Formato
// --------------------------------------------------------------------------- #
function horaCorta(iso: string): string {
  const d = new Date(iso);
  const hoy = new Date();
  const mismoDia =
    d.getFullYear() === hoy.getFullYear() &&
    d.getMonth() === hoy.getMonth() &&
    d.getDate() === hoy.getDate();
  return mismoDia
    ? d.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('es-BO', { day: '2-digit', month: '2-digit' });
}

function horaLarga(iso: string): string {
  return new Date(iso).toLocaleString('es-BO', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function etiqueta(conv: ChatConversacion): string {
  return conv.nombre_contacto || `+${conv.telefono}`;
}

function iniciales(conv: ChatConversacion): string {
  const nombre = conv.nombre_contacto?.trim();
  if (!nombre) return conv.telefono.slice(-2);
  return nombre
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

// Acuse de recibo del mensaje saliente, con el mismo vocabulario visual que
// WhatsApp: un check al salir, dos al entregarse, dos en color al leerse.
function Acuse({ estado }: { estado: ChatMensaje['estado'] }) {
  if (!estado) return null;
  if (estado === 'FALLIDO') {
    return (
      <span className="chat__acuse chat__acuse--fallido" title="No se pudo entregar">
        ⚠
      </span>
    );
  }
  const marcas = estado === 'ENVIADO' ? '✓' : '✓✓';
  const clase = estado === 'LEIDO' ? ' chat__acuse--leido' : '';
  const titulos = { ENVIADO: 'Enviado', ENTREGADO: 'Entregado', LEIDO: 'Leído' } as const;
  return (
    <span className={`chat__acuse${clase}`} title={titulos[estado]}>
      {marcas}
    </span>
  );
}

// --------------------------------------------------------------------------- #
// Burbuja con imagen: el binario está protegido por Bearer, así que un <img src>
// directo daría 401. Se baja por fetch a un blob: URL y se libera al desmontar.
// --------------------------------------------------------------------------- #
function BurbujaImagen({ mensaje, chatApi }: { mensaje: ChatMensaje; chatApi: ChatApi }) {
  const [url, setUrl] = useState<string | null>(null);
  const [fallo, setFallo] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    chatApi
      .media(mensaje.id, controller.signal)
      .then((u) => {
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFallo(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mensaje.id, chatApi]);

  if (fallo) return <p className="chat__media-fallo">No se pudo cargar la imagen</p>;
  if (!url) return <p className="chat__media-fallo">Cargando imagen…</p>;
  return <img className="chat__media" src={url} alt={mensaje.texto ?? 'Imagen recibida'} />;
}

// --------------------------------------------------------------------------- #
// --------------------------------------------------------------------------- #
// Agenda: elegir a qué tutor escribirle. Lista los contactos de la escuela — no la
// bandeja —, así que incluye a los que nunca escribieron, que son la mayoría.
// --------------------------------------------------------------------------- #
function DialogoAgenda({
  agenda,
  onElegir,
  onCerrar,
}: {
  agenda: ChatAgenda;
  onElegir: (telefono: string) => void;
  onCerrar: () => void;
}) {
  const [tutores, setTutores] = useState<ChatTutor[]>([]);
  const [buscar, setBuscar] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCargando(true);
    agenda
      .tutores(undefined, controller.signal)
      .then(setTutores)
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : 'No se pudo cargar la agenda');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCargando(false);
      });
    return () => controller.abort();
  }, [agenda]);

  // El filtro es local: la agenda de una escuela son decenas de tutores, no miles,
  // y así se busca sin ida y vuelta al servidor mientras se teclea.
  const patron = buscar.trim().toLowerCase();
  const visibles = patron
    ? tutores.filter((t) =>
        [t.nombres, t.telefono, ...t.deportistas].join(' ').toLowerCase().includes(patron),
      )
    : tutores;

  return (
    <div className="chat-agenda__backdrop" role="dialog" aria-modal="true" aria-label="Nuevo mensaje">
      <div className="chat-agenda">
        <header className="chat-agenda__head">
          <h2 className="chat-agenda__titulo">Nuevo mensaje</h2>
          <Button variant="ghost" size="sm" onClick={onCerrar}>
            Cerrar
          </Button>
        </header>
        <input
          className="chat__buscar"
          type="search"
          autoFocus
          placeholder="Buscar por tutor, deportista o número"
          value={buscar}
          onChange={(e) => setBuscar(e.target.value)}
        />
        <div className="chat-agenda__body">
          {cargando && <p className="chat__estado">Cargando agenda…</p>}
          {error && <p className="chat__estado chat__estado--error">{error}</p>}
          {!cargando && !error && visibles.length === 0 && (
            <p className="chat__estado">
              {tutores.length === 0
                ? 'No hay tutores con teléfono cargado en la escuela.'
                : 'Ningún contacto coincide con la búsqueda.'}
            </p>
          )}
          {visibles.map((t) => (
            <button
              key={t.tutor_id}
              type="button"
              className="chat-agenda__item"
              onClick={() => onElegir(t.telefono)}
            >
              <span className="chat-agenda__nombre">{t.nombres}</span>
              <span className="chat-agenda__meta">
                +{t.telefono}
                {t.deportistas.length > 0 && ` · ${t.deportistas.join(', ')}`}
              </span>
              {t.conversacion_id && <span className="chat-agenda__abierto">ya tiene chat</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ChatWhatsApp({ chatApi, escuelas, agenda, titulo, vacio }: ChatWhatsAppProps) {
  const toast = useToast();

  const [conversaciones, setConversaciones] = useState<ChatConversacion[]>([]);
  const [seleccionada, setSeleccionada] = useState<string | null>(null);
  const [hilo, setHilo] = useState<ChatHilo | null>(null);
  const [buscar, setBuscar] = useState('');
  const [soloSinAsignar, setSoloSinAsignar] = useState(false);
  // Filtro por escuela de la consola de plataforma ('' = todas). Sin él, el superadmin
  // recorre a mano los hilos de TODAS las escuelas para llegar al que busca.
  const [filtroEscuela, setFiltroEscuela] = useState('');
  const [cargando, setCargando] = useState(true);
  const [cargandoMas, setCargandoMas] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hayMas, setHayMas] = useState(false);
  const cursorRef = useRef<{ at: string; id: string } | null>(null);

  const [texto, setTexto] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [asignando, setAsignando] = useState(false);
  const [agendaAbierta, setAgendaAbierta] = useState(false);

  const finRef = useRef<HTMLDivElement | null>(null);
  const puedeAsignar = Boolean(chatApi.asignar && escuelas);

  // --- Bandeja (paginada, con sondeo) ---
  // Trae la PRIMERA página y la fusiona con lo que ya estaba: el sondeo no puede
  // descartar las páginas que el usuario cargó a mano. Los hilos que reaparecen arriba
  // (porque llegó un mensaje) se quitan de la cola para no duplicarse.
  const cargarBandeja = useCallback(
    async (signal?: AbortSignal) => {
      const page = await chatApi.conversaciones(
        {
          buscar: buscar.trim() || undefined,
          sinAsignar: soloSinAsignar || undefined,
          orgId: filtroEscuela || undefined,
        },
        signal,
      );
      setConversaciones((prev) => {
        const frescos = new Set(page.items.map((c) => c.id));
        return [...page.items, ...prev.filter((c) => !frescos.has(c.id))];
      });
      // El cursor solo se fija si NO se cargaron más páginas todavía; si no, "Cargar
      // más" volvería a pedir la segunda página en vez de la siguiente.
      if (cursorRef.current === null) {
        cursorRef.current =
          page.hay_mas && page.cursor_at && page.cursor_id
            ? { at: page.cursor_at, id: page.cursor_id }
            : null;
        setHayMas(page.hay_mas);
      }
      return page;
    },
    [chatApi, buscar, soloSinAsignar, filtroEscuela],
  );

  async function cargarMas() {
    const cursor = cursorRef.current;
    if (!cursor || cargandoMas) return;
    setCargandoMas(true);
    try {
      const page = await chatApi.conversaciones({
        buscar: buscar.trim() || undefined,
        sinAsignar: soloSinAsignar || undefined,
        orgId: filtroEscuela || undefined,
        cursorAt: cursor.at,
        cursorId: cursor.id,
      });
      setConversaciones((prev) => {
        const yaEstan = new Set(prev.map((c) => c.id));
        return [...prev, ...page.items.filter((c) => !yaEstan.has(c.id))];
      });
      cursorRef.current =
        page.hay_mas && page.cursor_at && page.cursor_id
          ? { at: page.cursor_at, id: page.cursor_id }
          : null;
      setHayMas(page.hay_mas);
    } catch (e: unknown) {
      toast.show({
        variant: 'error',
        message: e instanceof ApiError ? e.message : 'No se pudieron cargar más conversaciones',
      });
    } finally {
      setCargandoMas(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    let activo = true;
    setCargando(true);
    setError(null);
    // Cambiar de filtro o de búsqueda empieza una bandeja nueva: se descarta lo
    // acumulado y el cursor, o se mezclarían resultados de dos consultas distintas.
    setConversaciones([]);
    cursorRef.current = null;
    setHayMas(false);
    cargarBandeja(controller.signal)
      .catch((e: unknown) => {
        if (!activo || controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : 'No se pudo cargar el chat');
      })
      .finally(() => {
        if (activo) setCargando(false);
      });

    // Sondeo: los fallos del refresco se tragan a propósito (un corte de red
    // momentáneo no debe vaciar la pantalla ni tapar la conversación con un error).
    const id = window.setInterval(() => {
      cargarBandeja().catch(() => undefined);
    }, POLL_MS);

    return () => {
      activo = false;
      controller.abort();
      window.clearInterval(id);
    };
  }, [cargarBandeja]);

  // --- Hilo abierto (con sondeo) ---
  const cargarHilo = useCallback(
    async (id: string, signal?: AbortSignal) => {
      const data = await chatApi.hilo(id, signal);
      setHilo(data);
      // Abrir el chat limpia el badge en el servidor; se refleja ya en la lista
      // para no esperar al siguiente sondeo.
      setConversaciones((prev) =>
        prev.map((c) => (c.id === id ? { ...c, no_leidos: 0 } : c)),
      );
      return data;
    },
    [chatApi],
  );

  useEffect(() => {
    if (!seleccionada) {
      setHilo(null);
      return;
    }
    const controller = new AbortController();
    cargarHilo(seleccionada, controller.signal).catch((e: unknown) => {
      if (controller.signal.aborted) return;
      toast.show({
        variant: 'error',
        message: e instanceof ApiError ? e.message : 'No se pudo abrir la conversación',
      });
    });
    const id = window.setInterval(() => {
      cargarHilo(seleccionada).catch(() => undefined);
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(id);
    };
  }, [seleccionada, cargarHilo, toast]);

  // Bajar al último mensaje cuando cambia el hilo o llega uno nuevo.
  const cantidadMensajes = hilo?.mensajes.length ?? 0;
  useEffect(() => {
    finRef.current?.scrollIntoView({ block: 'end' });
  }, [cantidadMensajes, seleccionada]);

  // --- Enviar ---
  async function enviar() {
    const cuerpo = texto.trim();
    if (!cuerpo || !seleccionada || enviando) return;
    setEnviando(true);
    try {
      const out = await chatApi.responder(seleccionada, cuerpo);
      if (out.enviado) {
        setTexto('');
      } else if (out.motivo === 'ventana_expirada') {
        toast.show({
          variant: 'error',
          message:
            'Pasaron más de 24 h desde el último mensaje del contacto y este chat no ' +
            'tiene escuela asignada, así que WhatsApp no permite escribirle. Asignalo a ' +
            'una escuela o esperá a que escriba de nuevo.',
        });
      } else if (out.motivo === 'texto_largo_para_plantilla') {
        toast.show({
          variant: 'error',
          message:
            'El mensaje es muy largo para abrir una conversación. Acortalo (o esperá a ' +
            'que el contacto responda, y ahí no hay límite).',
        });
      } else {
        toast.show({ variant: 'error', message: out.detalle || 'No se pudo enviar el mensaje' });
      }
      await cargarHilo(seleccionada);
      await cargarBandeja();
    } catch (e: unknown) {
      toast.show({
        variant: 'error',
        message: e instanceof ApiError ? e.message : 'No se pudo enviar el mensaje',
      });
    } finally {
      setEnviando(false);
    }
  }

  // --- Asignar escuela (solo consola de plataforma) ---
  async function asignar(orgId: string | null) {
    if (!chatApi.asignar || !seleccionada) return;
    setAsignando(true);
    try {
      await chatApi.asignar(seleccionada, orgId);
      toast.show({
        variant: 'success',
        message: orgId
          ? 'Conversación asignada. La escuela ya la ve en su chat con todo el historial.'
          : 'Conversación devuelta a la cola de sin asignar.',
      });
      await cargarHilo(seleccionada);
      await cargarBandeja();
    } catch (e: unknown) {
      toast.show({
        variant: 'error',
        message: e instanceof ApiError ? e.message : 'No se pudo asignar la conversación',
      });
    } finally {
      setAsignando(false);
    }
  }

  // --- Abrir un chat desde la agenda ---
  async function abrirDesdeAgenda(telefono: string) {
    if (!agenda) return;
    setAgendaAbierta(false);
    try {
      const abierto = await agenda.abrir(telefono);
      setHilo(abierto);
      setSeleccionada(abierto.conversacion.id);
      await cargarBandeja();
    } catch (e: unknown) {
      toast.show({
        variant: 'error',
        message: e instanceof ApiError ? e.message : 'No se pudo abrir la conversación',
      });
    }
  }

  const conv = hilo?.conversacion ?? null;
  const sinAsignarCount = useMemo(
    () => conversaciones.filter((c) => c.org_id === null).length,
    [conversaciones],
  );

  // Se puede escribir si el contacto escribió hace menos de 24 h (texto libre) o si el
  // hilo tiene escuela (sale como plantilla de contacto aprobada).
  const puedeEscribir = Boolean(conv && (conv.ventana_abierta || conv.puede_iniciar));
  const saldraComoPlantilla = Boolean(conv && !conv.ventana_abierta && conv.puede_iniciar);

  return (
    <div className="chat">
      {/* ---- Bandeja ---- */}
      <aside className="chat__lista">
        <div className="chat__lista-head">
          <div className="chat__lista-titulo">
            <h1 className="chat__titulo">{titulo}</h1>
            {agenda && (
              <Button size="sm" onClick={() => setAgendaAbierta(true)}>
                Nuevo mensaje
              </Button>
            )}
          </div>
          <input
            className="chat__buscar"
            type="search"
            placeholder="Buscar por nombre o número"
            value={buscar}
            onChange={(e) => setBuscar(e.target.value)}
          />
          {/* La consola ve los hilos de TODAS las escuelas: sin acotar, la lista es un
              scroll interminable. Un solo selector cubre los dos modos de trabajo —
              atender la cola de sin clasificar, o mirar una escuela concreta. */}
          {puedeAsignar && (
            <select
              className="chat__filtro-escuela"
              value={soloSinAsignar ? 'SIN_ASIGNAR' : filtroEscuela}
              onChange={(e) => {
                const v = e.target.value;
                setSoloSinAsignar(v === 'SIN_ASIGNAR');
                setFiltroEscuela(v === 'SIN_ASIGNAR' ? '' : v);
              }}
            >
              <option value="">Todas las escuelas</option>
              <option value="SIN_ASIGNAR">
                Sin asignar{sinAsignarCount > 0 ? ` (${sinAsignarCount})` : ''}
              </option>
              {escuelas?.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nombre}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="chat__lista-body">
          {cargando && <p className="chat__estado">Cargando…</p>}
          {error && <p className="chat__estado chat__estado--error">{error}</p>}
          {!cargando && !error && conversaciones.length === 0 && (
            <p className="chat__estado">{vacio}</p>
          )}
          {conversaciones.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`chat__item${c.id === seleccionada ? ' chat__item--activo' : ''}`}
              onClick={() => setSeleccionada(c.id)}
            >
              <span className="chat__avatar" aria-hidden="true">
                {iniciales(c)}
              </span>
              <span className="chat__item-body">
                <span className="chat__item-top">
                  <span className="chat__item-nombre">{etiqueta(c)}</span>
                  <span className="chat__item-hora">{horaCorta(c.ultimo_mensaje_at)}</span>
                </span>
                <span className="chat__item-bottom">
                  <span className="chat__item-preview">{c.ultimo_mensaje_texto ?? '—'}</span>
                  {c.no_leidos > 0 && <span className="chat__badge">{c.no_leidos}</span>}
                </span>
                {puedeAsignar && (
                  <span
                    className={`chat__chip${c.org_id ? '' : ' chat__chip--pendiente'}`}
                  >
                    {c.org_nombre ?? 'Sin asignar'}
                  </span>
                )}
              </span>
            </button>
          ))}

          {hayMas && (
            <button
              type="button"
              className="chat__mas"
              onClick={() => void cargarMas()}
              disabled={cargandoMas}
            >
              {cargandoMas ? 'Cargando…' : 'Cargar más conversaciones'}
            </button>
          )}
        </div>
      </aside>

      {/* ---- Hilo ---- */}
      <section className="chat__hilo">
        {!conv && <div className="chat__placeholder">Elegí una conversación para verla acá.</div>}

        {conv && (
          <>
            <header className="chat__hilo-head">
              <div className="chat__hilo-id">
                <span className="chat__avatar" aria-hidden="true">
                  {iniciales(conv)}
                </span>
                <div>
                  <p className="chat__hilo-nombre">{etiqueta(conv)}</p>
                  <p className="chat__hilo-meta">
                    +{conv.telefono}
                    {conv.org_nombre ? ` · ${conv.org_nombre}` : ''}
                  </p>
                </div>
              </div>

              {puedeAsignar && (
                <label className="chat__asignar">
                  <span className="chat__asignar-label">Escuela</span>
                  <select
                    value={conv.org_id ?? ''}
                    disabled={asignando}
                    onChange={(e) => asignar(e.target.value || null)}
                  >
                    <option value="">Sin asignar</option>
                    {escuelas?.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.nombre}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </header>

            <div className="chat__mensajes">
              {hilo?.mensajes.length === 0 && (
                <p className="chat__estado">Todavía no hay mensajes en esta conversación.</p>
              )}
              {hilo?.mensajes.map((m) => (
                <div
                  key={m.id}
                  className={`chat__burbuja chat__burbuja--${m.direccion === 'OUT' ? 'out' : 'in'}`}
                >
                  {/* Se pinta por `tiene_media`, NO por el tipo: el recordatorio sale
                      como PLANTILLA y lleva el QR en la cabecera, así que atarlo a
                      tipo === 'IMAGEN' dejaba esas burbujas sin su imagen. */}
                  {m.tiene_media && <BurbujaImagen mensaje={m} chatApi={chatApi} />}
                  {m.texto && <p className="chat__texto">{m.texto}</p>}
                  <p className="chat__pie">
                    {m.direccion === 'OUT' && m.enviado_por_nombre && (
                      <span className="chat__autor">{m.enviado_por_nombre}</span>
                    )}
                    <span>{horaLarga(m.ocurrido_en)}</span>
                    <Acuse estado={m.estado} />
                  </p>
                  {m.estado === 'FALLIDO' && m.error_detalle && (
                    <p className="chat__error-detalle">{m.error_detalle}</p>
                  )}
                </div>
              ))}
              <div ref={finRef} />
            </div>

            {/* Fuera de la ventana de 24 h, WhatsApp no deja mandar texto libre; si el
                hilo tiene escuela igual se puede escribir, porque sale como plantilla
                de contacto aprobada. Solo cuando no hay ninguna de las dos vías se
                oculta el campo, en vez de dejar uno que fallaría al enviar. */}
            {puedeEscribir ? (
              <form
                className="chat__composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void enviar();
                }}
              >
                <textarea
                  className="chat__input"
                  rows={1}
                  placeholder="Escribí un mensaje"
                  value={texto}
                  onChange={(e) => setTexto(e.target.value)}
                  onKeyDown={(e) => {
                    // Enter envía; Shift+Enter hace salto de línea.
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void enviar();
                    }
                  }}
                />
                <Button type="submit" disabled={enviando || !texto.trim()}>
                  {enviando ? 'Enviando…' : 'Enviar'}
                </Button>
              </form>
            ) : (
              <div className="chat__cerrado">
                <strong>No se puede escribir a este contacto.</strong> Pasaron más de 24 h
                desde su último mensaje y el chat todavía no tiene escuela asignada.
                Asignalo a una escuela desde la cabecera y vas a poder escribirle.
              </div>
            )}

            {saldraComoPlantilla && (
              <p className="chat__nota">
                Este contacto no escribió en las últimas 24 h, así que el mensaje va a
                salir como <strong>mensaje de contacto</strong> aprobado por WhatsApp: se
                envía en una sola línea y encabezado por el nombre de la escuela. En
                cuanto responda, el chat pasa a texto libre normal.
              </p>
            )}
          </>
        )}
      </section>

      {agenda && agendaAbierta && (
        <DialogoAgenda
          agenda={agenda}
          onElegir={(telefono) => void abrirDesdeAgenda(telefono)}
          onCerrar={() => setAgendaAbierta(false)}
        />
      )}
    </div>
  );
}
