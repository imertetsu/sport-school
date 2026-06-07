import { describe, expect, it } from 'vitest';
import { normalizarFecha, parseCedula } from './parseCedula';

// El parser es puro y NO importa tesseract.js, así que corre en CI aunque el
// paquete no esté instalado. Estos tests fijan el comportamiento de las
// heurísticas; el OCR real es ruidoso, aquí validamos el parseo del texto.

describe('normalizarFecha', () => {
  it('normaliza dd/mm/yyyy a ISO', () => {
    expect(normalizarFecha('15/03/1998')).toBe('1998-03-15');
  });

  it('acepta separadores con puntos y guiones', () => {
    expect(normalizarFecha('05.07.2001')).toBe('2001-07-05');
    expect(normalizarFecha('9-11-1990')).toBe('1990-11-09');
  });

  it('entiende "dd de <mes> de yyyy"', () => {
    expect(normalizarFecha('15 de marzo de 1998')).toBe('1998-03-15');
  });

  it('entiende mes abreviado', () => {
    expect(normalizarFecha('03 ABR 2010')).toBe('2010-04-03');
  });

  it('devuelve undefined ante texto sin fecha', () => {
    expect(normalizarFecha('sin fecha aqui')).toBeUndefined();
  });

  it('rechaza meses/días imposibles', () => {
    expect(normalizarFecha('40/13/2000')).toBeUndefined();
  });
});

describe('parseCedula — etiquetas explícitas', () => {
  const texto = [
    'ESTADO PLURINACIONAL DE BOLIVIA',
    'CEDULA DE IDENTIDAD',
    'No. 9123456',
    'Apellidos: GUTIERREZ MAMANI',
    'Nombres: JUAN CARLOS',
    'Fecha de nacimiento: 15/03/1998',
  ].join('\n');

  const f = parseCedula(texto);

  it('extrae el número de CI', () => {
    expect(f.numeroCi).toBe('9123456');
  });

  it('separa apellido paterno y materno', () => {
    expect(f.apellidoPaterno).toBe('GUTIERREZ');
    expect(f.apellidoMaterno).toBe('MAMANI');
  });

  it('extrae los nombres', () => {
    expect(f.nombres).toBe('JUAN CARLOS');
  });

  it('normaliza la fecha de nacimiento a ISO', () => {
    expect(f.fechaNacimiento).toBe('1998-03-15');
  });
});

describe('parseCedula — tolerancia y resultados parciales', () => {
  it('no rompe con texto vacío', () => {
    expect(parseCedula('')).toEqual({});
  });

  it('devuelve lo que pudo aunque falten campos', () => {
    const f = parseCedula('Nombres: MARIA\nbasura ilegible');
    expect(f.nombres).toBe('MARIA');
    expect(f.numeroCi).toBeUndefined();
    expect(f.fechaNacimiento).toBeUndefined();
  });

  it('toma el grupo de dígitos como CI sin etiqueta clara', () => {
    const f = parseCedula('ruido 12 y luego 8456321 al final');
    expect(f.numeroCi).toBe('8456321');
  });

  it('cae al fallback posicional sin etiquetas de nombre', () => {
    const f = parseCedula('QUISPE FLORES\nANA MARIA\n7654321');
    expect(f.apellidoPaterno).toBe('QUISPE');
    expect(f.apellidoMaterno).toBe('FLORES');
    expect(f.nombres).toBe('ANA MARIA');
  });
});
