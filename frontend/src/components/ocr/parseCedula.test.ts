import { describe, expect, it } from 'vitest';
import {
  detectarFormato,
  mergeLados,
  normalizarFecha,
  parseAntiguo,
  parseCedula,
  parseMrz,
} from './parseCedula';
import { checkDigit } from './mrz';

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

// ===========================================================================
// Fixtures FICTICIOS (NO datos reales). Mismo formato/estructura que un CI real.
// Las MRZ se construyen con check digits calculados por `checkDigit`, así el
// test de "MRZ válida" pasa y el de "check inválido" corrompe uno a propósito.
// ===========================================================================

describe('checkDigit (ICAO 9303, pesos 7,3,1)', () => {
  it('calcula el dígito del nº de documento de ejemplo', () => {
    // "8942507<<" -> 5 (verificado contra el algoritmo ICAO).
    expect(checkDigit('8942507<<')).toBe(5);
  });
  it('calcula el dígito de una fecha YYMMDD', () => {
    expect(checkDigit('030405')).toBe(2);
  });
});

describe('parseMrz — CI nuevo (MRZ TD1, reverso)', () => {
  // Espécimen FICTICIO: doc 8942507, nac 2003-04-05 (030405), venc 280612.
  // Línea 3: RODRIGUEZ<GONZALEZ<<MARIA (ap. paterno RODRIGUEZ, materno GONZALEZ).
  const mrzValida = [
    'IDBOL8942507<<5<<<<<<<<<<<<<<<',
    '0304052F2806125BOL<<<<<<<<<<<8',
    'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
  ].join('\n');

  it('extrae numeroCi desde la línea 1 con check válido', () => {
    const f = parseMrz(mrzValida);
    expect(f?.numeroCi).toBe('8942507');
  });

  it('extrae la fecha de nacimiento en ISO con siglo correcto', () => {
    const f = parseMrz(mrzValida);
    expect(f?.fechaNacimiento).toBe('2003-04-05');
  });

  it('separa APELLIDOS<<NOMBRES en los tres campos', () => {
    const f = parseMrz(mrzValida);
    expect(f?.apellidoPaterno).toBe('RODRIGUEZ');
    expect(f?.apellidoMaterno).toBe('GONZALEZ');
    expect(f?.nombres).toBe('MARIA');
  });

  it('tolera ruido alrededor de la MRZ (líneas espurias y espacios)', () => {
    const conRuido = [
      'REPUBLICA DE BOLIVIA  -- reverso --',
      'I D B O L 8942507 << 5 <<<<<<<<<<<<<<<',
      '0304052F2806125BOL<<<<<<<<<<<8',
      'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
      'firma del titular',
    ].join('\n');
    const f = parseMrz(conRuido);
    expect(f?.numeroCi).toBe('8942507');
    expect(f?.fechaNacimiento).toBe('2003-04-05');
    expect(f?.nombres).toBe('MARIA');
  });

  it('rechaza numeroCi y fecha si el check del documento es inválido', () => {
    // Corrompe el check digit del documento (pos 15: 5 -> 9). El compuesto
    // tampoco cuadra, así que no debe propagar número ni fecha.
    const mrzCorrupta = [
      'IDBOL8942507<<9<<<<<<<<<<<<<<<',
      '0304052F2806125BOL<<<<<<<<<<<8',
      'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
    ].join('\n');
    const f = parseMrz(mrzCorrupta);
    expect(f?.numeroCi).toBeUndefined();
    expect(f?.fechaNacimiento).toBeUndefined();
    // Los nombres NO tienen check digit: se conservan.
    expect(f?.nombres).toBe('MARIA');
  });

  it('devuelve undefined cuando no hay MRZ', () => {
    expect(parseMrz('texto cualquiera sin zona legible por maquina')).toBeUndefined();
    expect(parseMrz('')).toBeUndefined();
  });
});

describe('detectarFormato', () => {
  it('detecta nuevo por MRZ válida', () => {
    const reverso = [
      'IDBOL8942507<<5<<<<<<<<<<<<<<<',
      '0304052F2806125BOL<<<<<<<<<<<8',
      'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
    ].join('\n');
    expect(detectarFormato(reverso)).toBe('nuevo');
  });

  it('detecta antiguo por marcas típicas del reverso', () => {
    const reverso = 'La presente cedula pertenece A: JUAN CARLOS MAMANI QUISPE\nNacido el 10 de Marzo de 2010';
    expect(detectarFormato(reverso)).toBe('antiguo');
  });

  it('desconocido si no hay señales', () => {
    expect(detectarFormato('foto borrosa sin texto util')).toBe('desconocido');
    expect(detectarFormato('')).toBe('desconocido');
  });
});

describe('parseAntiguo — CI antiguo (anverso + reverso)', () => {
  // Datos FICTICIOS plausibles. Decisión de producto (parser conservador): el CI
  // antiguo se ingresa A MANO; solo aceptamos un número CLARAMENTE etiquetado
  // ("No."/"C.I.") y NUNCA el patrón de serial "NNNNNNN NN-XX".
  const anverso = [
    'ESTADO PLURINACIONAL DE BOLIVIA',
    'SERVICIO GENERAL DE IDENTIFICACION PERSONAL',
    'No. 1234567',
    'CEDULA DE IDENTIDAD',
    'Emitida el 31 de Octubre de 2022',
  ].join('\n');
  // Reverso: nombre en orden NOMBRES -> APELLIDOS tras "pertenece A:".
  const reverso = [
    'La presente cedula de identidad pertenece A:',
    'JUAN CARLOS MAMANI QUISPE',
    'Nacido el 10 de Marzo de 2010',
    'Estado Civil SOLTERO',
    'Domicilio Calle Ficticia 123',
  ].join('\n');

  const f = parseAntiguo(anverso, reverso);

  it('toma el número etiquetado ("No."), sin complemento/serial', () => {
    expect(f.numeroCi).toBe('1234567');
  });

  it('extrae el nombre del reverso en orden nombres -> apellidos', () => {
    expect(f.nombres).toBe('JUAN CARLOS');
    expect(f.apellidoPaterno).toBe('MAMANI');
    expect(f.apellidoMaterno).toBe('QUISPE');
  });

  it('normaliza la fecha de nacimiento de la fecha larga', () => {
    expect(f.fechaNacimiento).toBe('2010-03-10');
  });

  it('NUNCA toma el patrón de serial "NNNNNNN NN-XX" como CI', () => {
    // Solo aparece el serial (sin etiqueta "No."/"C.I."): el CI queda vacío.
    const anversoSerial = ['CEDULA DE IDENTIDAD', '3727170 08-L3'].join('\n');
    const g = parseAntiguo(anversoSerial, 'pertenece A: ANA LUCIA TORRES VEGA');
    expect(g.numeroCi).toBeUndefined();
  });

  it('CI vacío si no hay número etiquetado como cédula', () => {
    const anversoSolo = ['CEDULA DE IDENTIDAD', 'serie 43333 seccion 42222'].join('\n');
    const g = parseAntiguo(anversoSolo, 'pertenece A: PEDRO ROJAS LIMA');
    expect(g.numeroCi).toBeUndefined();
  });
});

describe('campos OPCIONALES del reverso (domicilio / lugar nac / grupo sanguíneo)', () => {
  it('extrae DOMICILIO desde una línea claramente etiquetada', () => {
    const reverso = [
      'pertenece A: JUAN CARLOS MAMANI QUISPE',
      'DOMICILIO: AV X 123',
    ].join('\n');
    const f = parseAntiguo('', reverso);
    expect(f.domicilio).toBe('AV X 123');
  });

  it('extrae LUGAR DE NACIMIENTO y GRUPO SANGUINEO etiquetados', () => {
    const reverso = [
      'LUGAR DE NACIMIENTO: LA PAZ',
      'GRUPO SANGUINEO: O+',
    ].join('\n');
    const f = parseAntiguo('', reverso);
    expect(f.lugarNacimiento).toBe('LA PAZ');
    expect(f.grupoSanguineo).toBe('O+');
  });

  it('reverso BASURA: los 3 campos quedan undefined (conservador, sin basura)', () => {
    const reverso = [
      'ESTADO PLURINACIONAL DE BOLIVIA CEDULA DE ENTIDAD',
      'DOCUMENTOS REGISTRA DOS',
      'xZq 88 ## --',
    ].join('\n');
    const f = mergeLados('', reverso);
    expect(f.domicilio).toBeUndefined();
    expect(f.lugarNacimiento).toBeUndefined();
    expect(f.grupoSanguineo).toBeUndefined();
  });
});

describe('mergeLados — orquestación de dos lados', () => {
  it('CI nuevo: MRZ-first en el merge', () => {
    const anverso = [
      'ESTADO PLURINACIONAL DE BOLIVIA',
      'CEDULA DE IDENTIDAD',
      'APELLIDOS RODRIGUEZ GONZALEZ',
      'NOMBRES MARIA',
      'N° 8942507',
      'FECHA DE NACIMIENTO 05/04/2003',
    ].join('\n');
    const reverso = [
      'IDBOL8942507<<5<<<<<<<<<<<<<<<',
      '0304052F2806125BOL<<<<<<<<<<<8',
      'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
    ].join('\n');
    const f = mergeLados(anverso, reverso);
    expect(f.numeroCi).toBe('8942507');
    expect(f.fechaNacimiento).toBe('2003-04-05');
    expect(f.apellidoPaterno).toBe('RODRIGUEZ');
    expect(f.apellidoMaterno).toBe('GONZALEZ');
    expect(f.nombres).toBe('MARIA');
  });

  it('CI nuevo con MRZ corrupta: cae al anverso para número y fecha', () => {
    const anverso = [
      'CEDULA DE IDENTIDAD',
      'N° 8942507',
      'FECHA DE NACIMIENTO 05/04/2003',
    ].join('\n');
    const reverso = [
      'IDBOL8942507<<9<<<<<<<<<<<<<<<', // check de doc corrupto
      '0304052F2806125BOL<<<<<<<<<<<8',
      'RODRIGUEZ<GONZALEZ<<MARIA<<<<<',
    ].join('\n');
    const f = mergeLados(anverso, reverso);
    // El número/fecha vienen del anverso (la MRZ no los validó).
    expect(f.numeroCi).toBe('8942507');
    expect(f.fechaNacimiento).toBe('2003-04-05');
    // Los nombres sí salen de la MRZ (no tienen check).
    expect(f.nombres).toBe('MARIA');
  });

  it('CI antiguo: CI etiquetado del anverso, nombre y fecha del reverso', () => {
    const anverso = ['CEDULA DE IDENTIDAD', 'No. 1234567'].join('\n');
    const reverso = [
      'pertenece A: JUAN CARLOS MAMANI QUISPE',
      'Nacido el 10 de Marzo de 2010',
    ].join('\n');
    const f = mergeLados(anverso, reverso);
    expect(f.numeroCi).toBe('1234567');
    expect(f.nombres).toBe('JUAN CARLOS');
    expect(f.apellidoPaterno).toBe('MAMANI');
    expect(f.apellidoMaterno).toBe('QUISPE');
    expect(f.fechaNacimiento).toBe('2010-03-10');
  });

  it('un solo lado (solo anverso del nuevo) no rompe y entrega lo que pudo', () => {
    const anverso = [
      'CEDULA DE IDENTIDAD',
      'N° 8942507',
      'FECHA DE NACIMIENTO 05/04/2003',
    ].join('\n');
    const f = mergeLados(anverso, '');
    expect(f.numeroCi).toBe('8942507');
    expect(f.fechaNacimiento).toBe('2003-04-05');
  });

  it('textos vacíos: objeto vacío, sin lanzar', () => {
    expect(mergeLados('', '')).toEqual({});
  });
});

// ===========================================================================
// Fixtures con TEXTO OCR REAL capturado de cédulas físicas (anonimizado en su
// estructura, con el ruido real del OCR on-device). Objetivo: el CI NUEVO sigue
// rellenando bien y el CI ANTIGUO ya NO mete BASURA (ante duda, campo vacío).
// ===========================================================================

describe('REAL — CI nuevo (MRZ reverso, ruido real)', () => {
  // Ruido real: "B0L" con cero, espacio en línea 2, prefijo "MÍ " en línea 3.
  // Los check digits de doc/fecha de ESTA captura NO cuadran (OCR sobre foto),
  // así que la MRZ solo aporta los NOMBRES de forma fiable (no tienen check).
  const reverso = [
    'IDBOL8942507<<9<<<<<<<<<<<<<<<',
    '0304053F2806125B0L <<<<<<<<<<<6',
    'MÍ RODRIGUEZ<GONZALEZ<<MARIA<<<<R',
  ].join('\n');

  it('extrae apellidos y nombres pese al prefijo "MÍ " y la "R" colgando', () => {
    const f = parseMrz(reverso);
    expect(f?.apellidoPaterno).toBe('RODRIGUEZ');
    expect(f?.apellidoMaterno).toBe('GONZALEZ');
    expect(f?.nombres).toContain('MARIA');
  });

  it('no propaga numeroCi ni fecha si los check de ESTA captura no cuadran', () => {
    const f = parseMrz(reverso);
    expect(f?.numeroCi).toBeUndefined();
    expect(f?.fechaNacimiento).toBeUndefined();
  });
});

describe('REAL — CI nuevo (anverso + reverso, merge)', () => {
  const reverso = [
    'IDBOL8942507<<9<<<<<<<<<<<<<<<',
    '0304053F2806125B0L <<<<<<<<<<<6',
    'MÍ RODRIGUEZ<GONZALEZ<<MARIA<<<<R',
  ].join('\n');
  const anverso = [
    'ESTADO PLURINACIONAL DE BOLIVIA CÉDULA DE IDENTIDAD',
    'RODRIGUEZ GONZALEZ',
    '0504/2003',
    'N* 1234567',
  ].join('\n');

  const f = mergeLados(anverso, reverso);

  it('el CI sale del anverso (7 dígitos contiguos)', () => {
    expect(f.numeroCi).toBe('1234567');
  });

  it('la fecha de nacimiento sale del anverso "0504/2003"', () => {
    expect(f.fechaNacimiento).toBe('2003-04-05');
  });

  it('los nombres salen de la MRZ', () => {
    expect(f.apellidoPaterno).toBe('RODRIGUEZ');
    expect(f.apellidoMaterno).toBe('GONZALEZ');
    expect(f.nombres).toContain('MARIA');
  });
});

describe('REAL — CI antiguo (basura): NO debe rellenar basura', () => {
  it('anverso: NO toma el serial "3727170 08-L3" como CI', () => {
    const anverso = [
      '3727170 08-L3',
      'Emitida el 31 de Octubre de 2022',
      'Expira el 31 de Octubre de 2032',
      'serie 43333 seccion 42222',
    ].join('\n');
    const f = parseCedula(anverso);
    // El serial NO es el CI: ni el número entero ni su raíz.
    expect(f.numeroCi).not.toBe('372717008');
    expect(f.numeroCi).not.toBe('3727170');
    expect(f.numeroCi).toBeUndefined();
  });

  it('anverso: NO toma emisión/expiración como fecha de nacimiento', () => {
    const anverso = [
      '3727170 08-L3',
      'Emitida el 31 de Octubre de 2022',
      'Expira el 31 de Octubre de 2032',
      'serie 43333 seccion 42222',
    ].join('\n');
    const f = parseCedula(anverso);
    expect(f.fechaNacimiento).toBeUndefined();
  });

  it('reverso institucional: NO mete "DOCUMENTOS"/"REGISTRADOS"/"ESTADO" en nombre', () => {
    const reverso = [
      'ESTADO PLURINACIONAL DE BOLIVIA CEDULA DE ENTIDAD',
      'DOCUMENTOS REGISTRA DOS',
      'DOCUMENTOS REGISTRADOS',
    ].join('\n');
    const f = parseCedula(reverso);
    const todos = [f.apellidoPaterno, f.apellidoMaterno, f.nombres]
      .filter(Boolean)
      .join(' ')
      .toUpperCase();
    expect(todos).not.toContain('DOCUMENTOS');
    expect(todos).not.toContain('REGISTRADOS');
    expect(todos).not.toContain('ESTADO');
    expect(f.apellidoPaterno).toBeUndefined();
    expect(f.apellidoMaterno).toBeUndefined();
    expect(f.nombres).toBeUndefined();
  });

  it('merge de ambos lados basura: queda (casi) todo vacío, sin basura', () => {
    const anverso = [
      '3727170 08-L3',
      'Emitida el 31 de Octubre de 2022',
      'Expira el 31 de Octubre de 2032',
      'serie 43333 seccion 42222',
    ].join('\n');
    const reverso = [
      'ESTADO PLURINACIONAL DE BOLIVIA CEDULA DE ENTIDAD',
      'DOCUMENTOS REGISTRA DOS',
      'DOCUMENTOS REGISTRADOS',
    ].join('\n');
    const f = mergeLados(anverso, reverso);
    const todos = [f.apellidoPaterno, f.apellidoMaterno, f.nombres]
      .filter(Boolean)
      .join(' ')
      .toUpperCase();
    expect(todos).not.toContain('DOCUMENTOS');
    expect(todos).not.toContain('REGISTRADOS');
    expect(todos).not.toContain('ESTADO');
    expect(f.numeroCi).toBeUndefined();
    // Si hubiese fecha, jamás un año implausible.
    if (f.fechaNacimiento) {
      const anio = Number(f.fechaNacimiento.slice(0, 4));
      expect(anio).toBeGreaterThanOrEqual(1900);
      expect(anio).toBeLessThanOrEqual(new Date().getFullYear());
    }
  });
});
