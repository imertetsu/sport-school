/**
 * OcrSpike — página de DEV para validar la precisión del OCR de cédula con un
 * documento boliviano REAL.
 *
 * Sube/captura un CI y muestra: texto OCR crudo + campos parseados + tiempo.
 * Es una herramienta de desarrollo: vive en `/dev/ocr` y NO se agrega a `nav.ts`
 * ni a ningún menú. No requiere sesión ni backend.
 *
 * Privacidad: igual que el componente, la imagen se procesa en el navegador y no
 * se sube ni se guarda; el texto OCR solo se muestra en pantalla.
 */
import { useState } from 'react';
import { DocumentScanner, type CedulaFields } from '@/components/ocr/DocumentScanner';
import './OcrSpike.css';

const CAMPOS: { key: keyof CedulaFields; label: string }[] = [
  { key: 'numeroCi', label: 'Número de CI' },
  { key: 'nombres', label: 'Nombres' },
  { key: 'apellidoPaterno', label: 'Apellido paterno' },
  { key: 'apellidoMaterno', label: 'Apellido materno' },
  { key: 'fechaNacimiento', label: 'Fecha de nacimiento (ISO)' },
  { key: 'fechaNacimientoRaw', label: 'Fecha de nacimiento (cruda)' },
];

export function OcrSpike() {
  const [fields, setFields] = useState<CedulaFields | null>(null);
  const [rawText, setRawText] = useState<string>('');

  return (
    <div className="ocr-spike">
      <header className="ocr-spike__head">
        <h1 className="ocr-spike__title">Spike OCR — Cédula boliviana</h1>
        <p className="ocr-spike__subtitle">
          Herramienta de desarrollo para validar la precisión del escaneo con un
          documento real. La imagen se procesa en este navegador; no se sube ni se
          guarda.
        </p>
      </header>

      <section className="ocr-spike__scanner">
        <DocumentScanner
          label="Subir o capturar cédula"
          onExtract={setFields}
          onRawText={setRawText}
        />
      </section>

      <div className="ocr-spike__cols">
        <section className="ocr-spike__panel">
          <h2 className="ocr-spike__panel-title">Campos parseados</h2>
          {fields ? (
            <dl className="ocr-spike__fields">
              {CAMPOS.map(({ key, label }) => (
                <div className="ocr-spike__field" key={key}>
                  <dt>{label}</dt>
                  <dd className={fields[key] ? '' : 'ocr-spike__empty'}>
                    {fields[key] ?? '— (no detectado)'}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="ocr-spike__hint">Aún no hay resultados.</p>
          )}
        </section>

        <section className="ocr-spike__panel">
          <h2 className="ocr-spike__panel-title">Texto OCR crudo</h2>
          {rawText ? (
            <pre className="ocr-spike__raw">{rawText}</pre>
          ) : (
            <p className="ocr-spike__hint">Aún no hay texto reconocido.</p>
          )}
        </section>
      </div>
    </div>
  );
}
